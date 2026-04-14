from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import joblib
import numpy as np
import pandas as pd
import torch

from .config import (
    DATABASE_FILE,
    FEATURE_COLUMNS,
    META_FILE,
    MODEL_FILE,
    ONLINE_TIMEOUT_SECONDS,
    SCALER_FILE,
    SIMULATION_DEVICE_COUNT,
    WINDOW_SIZE,
    ensure_directories,
    get_database_uri,
)
from .data_generator import GeneratorConfig, build_dataset
from .database import AnomalyEvent, Device, MeterReading, User, db
from .model import LSTMAutoEncoder
from .preprocess import clean_dataset, transform_features
from .realtime import hub
from .security import cipher
from .train import train_model


@dataclass
class DetectionResult:
    anomaly_score: float
    threshold: float
    predicted_label: int
    anomaly_type: str
    description: str


class DetectionService:
    def __init__(self) -> None:
        self.model: LSTMAutoEncoder | None = None
        self.scaler = None
        self.meta: dict[str, Any] | None = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    def ensure_ready(self) -> None:
        ensure_directories()
        if not (MODEL_FILE.exists() and SCALER_FILE.exists() and META_FILE.exists()):
            dataset = build_dataset(GeneratorConfig())
            train_model(dataset)

        if self.model is None:
            self.scaler = joblib.load(SCALER_FILE)
            self.meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            self.model = LSTMAutoEncoder(
                input_size=len(FEATURE_COLUMNS),
                hidden_size=self.meta["hidden_size"],
                num_layers=self.meta["num_layers"],
            ).to(self.device)
            self.model.load_state_dict(torch.load(MODEL_FILE, map_location=self.device))
            self.model.eval()

    def score_recent_readings(self, readings: list[MeterReading]) -> DetectionResult:
        self.ensure_ready()
        if len(readings) < WINDOW_SIZE:
            latest = readings[-1]
            anomaly_score = self._bootstrap_score(latest, readings)
            threshold = 0.85
            predicted_label = int(anomaly_score > threshold)
            anomaly_type, description = self._infer_anomaly_type(latest, readings, anomaly_score, threshold)
            return DetectionResult(anomaly_score, threshold, predicted_label, anomaly_type, description)

        frame = pd.DataFrame(
            [
                {
                    "timestamp": item.timestamp,
                    "meter_id": item.device.meter_id,
                    "instant_flow": item.instant_flow,
                    "cumulative_usage": item.cumulative_usage,
                    "battery_voltage": item.battery_voltage,
                    "signal_strength": item.signal_strength,
                    "valve_state": item.valve_state,
                    "temperature": item.temperature,
                    "pressure": item.pressure,
                }
                for item in readings[-WINDOW_SIZE:]
            ]
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        frame = clean_dataset(frame)
        transformed = transform_features(frame, self.scaler)
        window = transformed[FEATURE_COLUMNS].to_numpy(dtype=np.float32)

        with torch.no_grad():
            tensor = torch.tensor(window[None, :, :], dtype=torch.float32, device=self.device)
            reconstructed = self.model(tensor)
            anomaly_score = float(torch.mean((reconstructed - tensor) ** 2).cpu().item())

        latest = readings[-1]
        threshold = float(self.meta["threshold"])
        predicted_label = int(anomaly_score > threshold)
        anomaly_type, description = self._infer_anomaly_type(latest, readings, anomaly_score, threshold)
        return DetectionResult(anomaly_score, threshold, predicted_label, anomaly_type, description)

    def _bootstrap_score(self, latest: MeterReading, readings: list[MeterReading]) -> float:
        score = 0.0
        if latest.instant_flow > 1.4:
            score += 0.45
        if latest.battery_voltage < 2.8:
            score += 0.35
        if latest.signal_strength < 35:
            score += 0.25
        if latest.pressure < 1.5 or latest.pressure > 2.8:
            score += 0.2
        if len(readings) >= 3:
            recent_mean = np.mean([item.instant_flow for item in readings[-3:]])
            if latest.instant_flow > recent_mean * 2.2:
                score += 0.4
        return min(score, 1.5)

    def _infer_anomaly_type(
        self,
        latest: MeterReading,
        readings: list[MeterReading],
        anomaly_score: float,
        threshold: float,
    ) -> tuple[str, str]:
        recent_flows = [item.instant_flow for item in readings[-6:]]
        mean_flow = max(0.05, float(np.mean(recent_flows)))

        if latest.battery_voltage < 2.8:
            return "low_battery", f"Battery dropped to {latest.battery_voltage:.2f}V."
        if latest.signal_strength < 30:
            return "signal_issue", f"Signal strength is {latest.signal_strength:.1f}."
        if latest.instant_flow > mean_flow * 2.5 and latest.instant_flow > 0.8:
            return "flow_spike", f"Instant flow reached {latest.instant_flow:.3f}."
        if latest.pressure < 1.4 or latest.pressure > 2.8:
            return "pressure_issue", f"Pressure is {latest.pressure:.2f}."
        if anomaly_score > threshold:
            return "generic_anomaly", f"Score {anomaly_score:.4f} exceeds threshold {threshold:.4f}."
        return "normal", "Data is in normal range."


detector = DetectionService()


def _default_device_rows(total_count: int) -> list[tuple[str, str, str, str]]:
    rows: list[tuple[str, str, str, str]] = []
    for index in range(1, total_count + 1):
        meter_id = f"GM{index:03d}"
        name = f"Simulated Gas Meter {index:03d}"
        location = f"Zone-{(index - 1) // 10 + 1}"
        api_key = f"key-gm{index:03d}"
        rows.append((meter_id, name, location, api_key))
    return rows


def seed_defaults() -> None:
    admin = User.query.filter_by(username="admin").first()
    if admin is None:
        db.session.add(
            User(
                username="admin",
                full_name="System Administrator",
                password_hash=cipher.encrypt("admin123"),
            )
        )

    desired = _default_device_rows(SIMULATION_DEVICE_COUNT)
    existing_meter_ids = {item.meter_id for item in Device.query.all()}
    for meter_id, name, location, api_key in desired:
        if meter_id in existing_meter_ids:
            continue
        db.session.add(
            Device(
                meter_id=meter_id,
                name=name,
                location=location,
                api_key=api_key,
                status="offline",
            )
        )

    db.session.commit()


def emit_realtime_updates() -> None:
    hub.broadcast("dashboard", dashboard_snapshot())
    hub.broadcast("devices", devices_snapshot())
    hub.broadcast("alerts", alert_history(limit=30))
    hub.broadcast("settings", settings_snapshot())


def create_device_payload(device: Device) -> dict[str, Any]:
    latest = (
        MeterReading.query.filter_by(device_id=device.id)
        .order_by(MeterReading.timestamp.desc())
        .first()
    )
    anomaly_count = AnomalyEvent.query.filter_by(device_id=device.id).count()
    return {
        "id": device.id,
        "meter_id": device.meter_id,
        "name": device.name,
        "location": device.location,
        "api_key": device.api_key,
        "status": device.status,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "anomaly_count": anomaly_count,
        "latest_reading": None
        if latest is None
        else {
            "timestamp": latest.timestamp.isoformat(),
            "instant_flow": latest.instant_flow,
            "cumulative_usage": latest.cumulative_usage,
            "battery_voltage": latest.battery_voltage,
            "signal_strength": latest.signal_strength,
            "temperature": latest.temperature,
            "pressure": latest.pressure,
            "predicted_label": latest.predicted_label,
            "anomaly_score": latest.anomaly_score,
        },
    }


def create_device(payload: dict[str, Any]) -> dict[str, Any]:
    meter_id = str(payload.get("meter_id", "")).strip()
    name = str(payload.get("name", "")).strip()
    location = str(payload.get("location", "")).strip()
    api_key = str(payload.get("api_key", "")).strip() or f"key-{secrets.token_hex(8)}"

    if not meter_id or not name or not location:
        raise ValueError("meter_id, name and location are required.")
    if Device.query.filter_by(meter_id=meter_id).first():
        raise ValueError("meter_id already exists.")
    if Device.query.filter_by(api_key=api_key).first():
        raise ValueError("api_key already exists.")

    device = Device(meter_id=meter_id, name=name, location=location, api_key=api_key, status="offline")
    db.session.add(device)
    db.session.commit()
    return create_device_payload(device)


def update_device(device_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    device = Device.query.get_or_404(device_id)
    meter_id = str(payload.get("meter_id", device.meter_id)).strip()
    name = str(payload.get("name", device.name)).strip()
    location = str(payload.get("location", device.location)).strip()
    api_key = str(payload.get("api_key", device.api_key)).strip()

    if not meter_id or not name or not location or not api_key:
        raise ValueError("meter_id, name, location and api_key are required.")

    existing_meter = Device.query.filter(Device.meter_id == meter_id, Device.id != device_id).first()
    existing_key = Device.query.filter(Device.api_key == api_key, Device.id != device_id).first()
    if existing_meter:
        raise ValueError("meter_id already exists.")
    if existing_key:
        raise ValueError("api_key already exists.")

    device.meter_id = meter_id
    device.name = name
    device.location = location
    device.api_key = api_key
    db.session.commit()
    return create_device_payload(device)


def delete_device(device_id: int) -> None:
    device = Device.query.get_or_404(device_id)
    AnomalyEvent.query.filter_by(device_id=device_id).delete()
    MeterReading.query.filter_by(device_id=device_id).delete()
    db.session.delete(device)
    db.session.commit()


def ingest_reading(device: Device, payload: dict[str, Any], source: str, emit_event: bool = True) -> MeterReading:
    reading = MeterReading(
        device_id=device.id,
        source=source,
        timestamp=payload["timestamp"],
        instant_flow=float(payload["instant_flow"]),
        cumulative_usage=float(payload["cumulative_usage"]),
        battery_voltage=float(payload["battery_voltage"]),
        signal_strength=float(payload["signal_strength"]),
        valve_state=int(payload["valve_state"]),
        temperature=float(payload["temperature"]),
        pressure=float(payload["pressure"]),
    )
    db.session.add(reading)
    device.last_seen_at = reading.timestamp
    device.status = "online"
    db.session.flush()

    recent_readings = (
        MeterReading.query.filter_by(device_id=device.id)
        .order_by(MeterReading.timestamp.asc())
        .all()
    )
    result = detector.score_recent_readings(recent_readings)
    reading.anomaly_score = result.anomaly_score
    reading.threshold = result.threshold
    reading.predicted_label = result.predicted_label

    if result.predicted_label == 1:
        db.session.add(
            AnomalyEvent(
                device_id=device.id,
                reading_id=reading.id,
                anomaly_type=result.anomaly_type,
                description=result.description,
                score=result.anomaly_score,
                threshold=result.threshold,
            )
        )

    db.session.commit()
    if emit_event:
        emit_realtime_updates()
    return reading


def refresh_device_statuses() -> None:
    cutoff = datetime.now() - timedelta(seconds=ONLINE_TIMEOUT_SECONDS)
    changed = False
    for device in Device.query.all():
        next_status = "online" if device.last_seen_at and device.last_seen_at >= cutoff else "offline"
        if device.status != next_status:
            device.status = next_status
            changed = True
    if changed:
        db.session.commit()


def dashboard_snapshot() -> dict[str, Any]:
    refresh_device_statuses()
    devices = Device.query.order_by(Device.meter_id.asc()).all()
    recent_cutoff = datetime.now() - timedelta(hours=24)

    total_readings = MeterReading.query.count()
    anomalies_24h = AnomalyEvent.query.filter(AnomalyEvent.created_at >= recent_cutoff).count()
    latest_events = AnomalyEvent.query.order_by(AnomalyEvent.created_at.desc()).limit(20).all()
    latest_readings = MeterReading.query.order_by(MeterReading.timestamp.desc()).limit(200).all()

    chart_data = [
        {
            "timestamp": item.timestamp.isoformat(),
            "meter_id": item.device.meter_id,
            "instant_flow": item.instant_flow,
            "score": item.anomaly_score or 0,
        }
        for item in reversed(latest_readings)
    ]

    return {
        "summary": {
            "total_devices": len(devices),
            "online_devices": sum(1 for item in devices if item.status == "online"),
            "total_readings": total_readings,
            "anomalies_24h": anomalies_24h,
        },
        "devices": [create_device_payload(device) for device in devices],
        "alerts": [
            {
                "meter_id": event.device.meter_id,
                "device_name": event.device.name,
                "anomaly_type": event.anomaly_type,
                "description": event.description,
                "score": event.score,
                "threshold": event.threshold,
                "created_at": event.created_at.isoformat(),
            }
            for event in latest_events
        ],
        "chart": chart_data,
    }


def devices_snapshot() -> list[dict[str, Any]]:
    refresh_device_statuses()
    devices = Device.query.order_by(Device.meter_id.asc()).all()
    return [create_device_payload(device) for device in devices]


def alert_history(limit: int = 30) -> list[dict[str, Any]]:
    events = AnomalyEvent.query.order_by(AnomalyEvent.created_at.desc()).limit(limit).all()
    return [
        {
            "id": event.id,
            "meter_id": event.device.meter_id,
            "device_name": event.device.name,
            "location": event.device.location,
            "anomaly_type": event.anomaly_type,
            "description": event.description,
            "score": event.score,
            "threshold": event.threshold,
            "created_at": event.created_at.isoformat(),
        }
        for event in events
    ]


def device_history(meter_id: str | None = None, limit: int = 200) -> dict[str, Any]:
    query = MeterReading.query.join(Device).order_by(MeterReading.timestamp.desc())
    if meter_id:
        query = query.filter(Device.meter_id == meter_id)
    readings = query.limit(limit).all()

    rows = [
        {
            "meter_id": item.device.meter_id,
            "device_name": item.device.name,
            "timestamp": item.timestamp.isoformat(),
            "instant_flow": item.instant_flow,
            "cumulative_usage": item.cumulative_usage,
            "battery_voltage": item.battery_voltage,
            "signal_strength": item.signal_strength,
            "temperature": item.temperature,
            "pressure": item.pressure,
            "predicted_label": item.predicted_label,
            "anomaly_score": item.anomaly_score,
        }
        for item in readings
    ]
    return {"rows": rows, "meter_id": meter_id}


def settings_snapshot() -> dict[str, Any]:
    admin = User.query.filter_by(username="admin").first()
    return {
        "database_uri": get_database_uri(),
        "database_file": str(DATABASE_FILE),
        "device_upload_api": "/api/device/upload",
        "websocket_url": "/ws",
        "simulation_device_count": SIMULATION_DEVICE_COUNT,
        "default_admin": {
            "username": "admin",
            "password_encrypted": admin.password_hash if admin else "",
        },
        "sample_keys": [{"meter_id": item.meter_id, "api_key": item.api_key} for item in Device.query.all()[:20]],
    }


def ensure_database() -> None:
    ensure_directories()
    if get_database_uri().startswith("sqlite:///"):
        DATABASE_FILE.touch(exist_ok=True)
