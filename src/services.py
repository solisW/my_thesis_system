from __future__ import annotations

import hashlib
import json
import secrets
import socket
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
from .database import (
    AnomalyEvent,
    Device,
    Engineer,
    MeterReading,
    User,
    WorkOrder,
    WorkOrderRecord,
    db,
    work_order_stage_label,
)
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
    severity: str


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
STATUS_STAGE_MAP = {
    "pending": "pending",
    "assigned": "assigned",
    "in_progress": "in_progress",
    "completed": "completed",
}
WORK_ORDER_FLOW = ["pending", "assigned", "in_progress", "completed"]


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
            predicted_label = int(anomaly_score > threshold and self._has_operational_anomaly(latest, readings))
            anomaly_type, description, severity = self._infer_anomaly_type(latest, readings, anomaly_score, threshold)
            return DetectionResult(anomaly_score, threshold, predicted_label, anomaly_type, description, severity)

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
        score_threshold = threshold * 1.35
        predicted_label = int(anomaly_score > score_threshold and self._has_operational_anomaly(latest, readings))
        anomaly_type, description, severity = self._infer_anomaly_type(latest, readings, anomaly_score, threshold)
        return DetectionResult(anomaly_score, threshold, predicted_label, anomaly_type, description, severity)

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

    def _has_operational_anomaly(self, latest: MeterReading, readings: list[MeterReading]) -> bool:
        recent_flows = [item.instant_flow for item in readings[-6:]]
        mean_flow = max(0.05, float(np.mean(recent_flows)))
        return any(
            [
                latest.battery_voltage < 2.85,
                latest.signal_strength < 28,
                latest.pressure < 1.45,
                latest.pressure > 2.75,
                latest.instant_flow > mean_flow * 2.8,
                latest.instant_flow < mean_flow * 0.28,
            ]
        )

    def _infer_anomaly_type(
        self,
        latest: MeterReading,
        readings: list[MeterReading],
        anomaly_score: float,
        threshold: float,
    ) -> tuple[str, str, str]:
        recent_flows = [item.instant_flow for item in readings[-6:]]
        mean_flow = max(0.05, float(np.mean(recent_flows)))

        if latest.battery_voltage < 2.8:
            return "低电压告警", f"设备电池电压降至 {latest.battery_voltage:.2f}V。", "high"
        if latest.signal_strength < 30:
            return "通信异常", f"设备信号强度仅 {latest.signal_strength:.1f}。", "medium"
        if latest.instant_flow > mean_flow * 2.5 and latest.instant_flow > 0.8:
            return "流量尖峰", f"瞬时流量升至 {latest.instant_flow:.3f}。", "high"
        if latest.pressure < 1.4 or latest.pressure > 2.8:
            return "压力异常", f"管网压力为 {latest.pressure:.2f}。", "medium"
        if anomaly_score > threshold:
            return "综合异常", f"异常分数 {anomaly_score:.4f} 超过阈值 {threshold:.4f}。", "medium"
        return "正常", "数据处于正常波动范围。", "low"


detector = DetectionService()


def _default_device_rows(total_count: int) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    base_latitude = 31.2304
    base_longitude = 121.4737
    for index in range(1, total_count + 1):
        rows.append(
            {
                "meter_id": f"GM{index:03d}",
                "name": f"燃气表设备 {index:03d}",
                "location": f"{(index - 1) // 10 + 1}号片区 {(index - 1) % 10 + 1}点位",
                "area": f"{chr(65 + ((index - 1) // 10))}区",
                "latitude": base_latitude + ((index - 1) // 10) * 0.004,
                "longitude": base_longitude + ((index - 1) % 10) * 0.004,
                "device_mode": "simulated",
                "protocol": "HTTP",
                "ip_address": f"192.168.1.{index}",
                "port": 8000 + index,
                "firmware_version": "v1.0.0",
                "api_key": f"key-gm{index:03d}",
            }
        )
    return rows


def _default_engineers() -> list[dict[str, str]]:
    return [
        {"name": "张工", "phone": "13800010001", "specialty": "计量维护", "status": "available", "region": "A区"},
        {"name": "李工", "phone": "13800010002", "specialty": "通信维护", "status": "busy", "region": "B区"},
        {"name": "王工", "phone": "13800010003", "specialty": "管网检修", "status": "available", "region": "C区"},
        {"name": "赵工", "phone": "13800010004", "specialty": "阀控维护", "status": "available", "region": "D区"},
    ]


def _jittered_coordinate(meter_id: str, latitude: float, longitude: float) -> tuple[float, float]:
    digest = hashlib.sha1(meter_id.encode("utf-8")).digest()
    lat_offset = ((digest[0] / 255.0) - 0.5) * 0.004
    lng_offset = ((digest[1] / 255.0) - 0.5) * 0.005
    return latitude + lat_offset, longitude + lng_offset


def seed_defaults() -> None:
    admin = User.query.filter_by(username="admin").first()
    if admin is None:
        db.session.add(
            User(
                username="admin",
                full_name="系统管理员",
                password_hash=cipher.encrypt("admin123"),
                role="admin",
            )
        )

    existing_meter_ids = {item.meter_id for item in Device.query.all()}
    for row in _default_device_rows(SIMULATION_DEVICE_COUNT):
        if row["meter_id"] in existing_meter_ids:
            continue
        db.session.add(Device(**row))

    existing_engineers = {item.name for item in Engineer.query.all()}
    for row in _default_engineers():
        if row["name"] in existing_engineers:
            continue
        db.session.add(Engineer(**row))

    db.session.commit()


def emit_realtime_updates() -> None:
    snapshot = dashboard_snapshot()
    hub.broadcast("dashboard", snapshot)
    hub.broadcast("devices", devices_snapshot())
    hub.broadcast("alerts", alerts_snapshot(limit=50, sort_by="time"))
    hub.broadcast("map", snapshot["map_points"])
    hub.broadcast("work_orders", work_orders_snapshot())
    hub.broadcast("engineers", engineers_snapshot())
    hub.broadcast("reports", reports_snapshot())


def _serialize_work_order_record(record: WorkOrderRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "stage": record.stage,
        "action": record.action,
        "note": record.note,
        "operator_name": record.operator_name,
        "created_at": record.created_at.isoformat(),
    }


def _append_work_order_record(
    work_order: WorkOrder,
    action: str,
    note: str,
    operator_name: str = "系统",
    stage: str | None = None,
) -> None:
    db.session.add(
        WorkOrderRecord(
            work_order_id=work_order.id,
            stage=stage or work_order.current_stage,
            action=action,
            note=note,
            operator_name=operator_name,
        )
    )


def _serialize_work_order(order: WorkOrder) -> dict[str, Any]:
    records = sorted(order.records, key=lambda item: item.created_at)
    current_stage = order.current_stage or STATUS_STAGE_MAP.get(order.status, "pending")
    current_index = WORK_ORDER_FLOW.index(current_stage) if current_stage in WORK_ORDER_FLOW else 0
    return {
        "id": order.id,
        "title": order.title,
        "description": order.description,
        "priority": order.priority,
        "status": order.status,
        "current_stage": current_stage,
        "current_stage_label": work_order_stage_label(current_stage),
        "device_id": order.device_id,
        "device_name": order.device.name,
        "meter_id": order.device.meter_id,
        "engineer_id": order.engineer_id,
        "engineer_name": order.engineer.name if order.engineer else "未分配",
        "created_at": order.created_at.isoformat(),
        "updated_at": order.updated_at.isoformat(),
        "records": [_serialize_work_order_record(record) for record in records],
        "flow_nodes": [
            {
                "stage": stage,
                "label": work_order_stage_label(stage),
                "active": index <= current_index,
                "current": stage == current_stage,
            }
            for index, stage in enumerate(WORK_ORDER_FLOW)
        ],
    }


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


def create_device_payload(device: Device) -> dict[str, Any]:
    latest = MeterReading.query.filter_by(device_id=device.id).order_by(MeterReading.timestamp.desc()).first()
    open_orders = WorkOrder.query.filter(
        WorkOrder.device_id == device.id, WorkOrder.status.in_(["pending", "assigned", "in_progress"])
    ).count()
    return {
        "id": device.id,
        "meter_id": device.meter_id,
        "name": device.name,
        "location": device.location,
        "area": device.area,
        "latitude": device.latitude,
        "longitude": device.longitude,
        "device_mode": device.device_mode,
        "protocol": device.protocol,
        "ip_address": device.ip_address,
        "port": device.port,
        "firmware_version": device.firmware_version,
        "api_key": device.api_key,
        "status": device.status,
        "last_seen_at": device.last_seen_at.isoformat() if device.last_seen_at else None,
        "anomaly_count": AnomalyEvent.query.filter_by(device_id=device.id).count(),
        "open_orders": open_orders,
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


def devices_snapshot() -> list[dict[str, Any]]:
    refresh_device_statuses()
    devices = Device.query.order_by(Device.meter_id.asc()).all()
    return [create_device_payload(device) for device in devices]


def dashboard_snapshot() -> dict[str, Any]:
    refresh_device_statuses()
    devices = Device.query.order_by(Device.meter_id.asc()).all()
    abnormal_devices = 0
    connected_devices = 0
    offline_devices = 0
    device_cards: list[dict[str, Any]] = []
    map_points: list[dict[str, Any]] = []

    for device in devices:
        payload = create_device_payload(device)
        latest = payload["latest_reading"]
        is_abnormal = bool(latest and latest["predicted_label"] == 1)
        if device.status == "online":
            connected_devices += 1
        else:
            offline_devices += 1
        if is_abnormal:
            abnormal_devices += 1

        device_cards.append(
            {
                "id": payload["id"],
                "meter_id": payload["meter_id"],
                "name": payload["name"],
                "location": payload["location"],
                "status": device.status,
                "status_text": "在线" if device.status == "online" else "离线",
                "anomaly": is_abnormal,
                "signal_strength": latest["signal_strength"] if latest else None,
                "instant_flow": latest["instant_flow"] if latest else None,
                "battery_voltage": latest["battery_voltage"] if latest else None,
                "updated_at": payload["last_seen_at"],
            }
        )
        map_points.append(
            {
                "id": payload["id"],
                "meter_id": payload["meter_id"],
                "name": payload["name"],
                "location": payload["location"],
                "latitude": payload["latitude"],
                "longitude": payload["longitude"],
                "display_latitude": _jittered_coordinate(payload["meter_id"], payload["latitude"], payload["longitude"])[0],
                "display_longitude": _jittered_coordinate(payload["meter_id"], payload["latitude"], payload["longitude"])[1],
                "status": device.status,
                "anomaly": is_abnormal,
                "area": payload["area"],
            }
        )

    alerts = alerts_snapshot(limit=20, sort_by="time")
    recent_alerts = AnomalyEvent.query.order_by(AnomalyEvent.created_at.desc()).limit(500).all()
    buckets: dict[str, dict[str, Any]] = {}
    for event in recent_alerts:
        bucket_time = event.created_at.replace(minute=0, second=0, microsecond=0)
        bucket_key = bucket_time.isoformat()
        bucket = buckets.setdefault(
            bucket_key,
            {
                "timestamp": bucket_key,
                "label": bucket_time.strftime("%m-%d %H:00"),
                "anomaly_count": 0,
                "total_count": 0,
            },
        )
        bucket["total_count"] += 1
        bucket["anomaly_count"] += 1
    trend = list(sorted(buckets.values(), key=lambda item: item["timestamp"]))[-24:]

    return {
        "summary": {
            "connected_devices": connected_devices,
            "offline_devices": offline_devices,
            "abnormal_devices": abnormal_devices,
            "total_devices": len(devices),
        },
        "device_cards": device_cards,
        "alerts": alerts,
        "map_points": map_points,
        "trend": trend,
    }


def alerts_snapshot(limit: int = 50, sort_by: str = "time") -> list[dict[str, Any]]:
    events = AnomalyEvent.query.all()
    if sort_by in {"severity", "urgent", "priority"}:
        events = sorted(
            events,
            key=lambda event: (
                SEVERITY_ORDER.get(event.severity, 99),
                -int(event.created_at.timestamp()),
                -event.id,
            ),
        )
    else:
        events = sorted(events, key=lambda event: event.created_at, reverse=True)

    events = events[:limit]
    return [
        {
            "id": event.id,
            "meter_id": event.device.meter_id,
            "device_name": event.device.name,
            "location": event.device.location,
            "severity": event.severity,
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
    return {
        "rows": [
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
        ],
        "meter_id": meter_id,
    }


def create_device(payload: dict[str, Any]) -> dict[str, Any]:
    meter_id = str(payload.get("meter_id", "")).strip()
    name = str(payload.get("name", "")).strip()
    location = str(payload.get("location", "")).strip()
    if not meter_id or not name or not location:
        raise ValueError("设备编号、设备名称和位置不能为空。")
    api_key = str(payload.get("api_key", "")).strip() or f"key-{secrets.token_hex(8)}"
    if Device.query.filter_by(meter_id=meter_id).first():
        raise ValueError("设备编号已存在。")
    if Device.query.filter_by(api_key=api_key).first():
        raise ValueError("API Key 已存在。")

    device = Device(
        meter_id=meter_id,
        name=name,
        location=location,
        area=str(payload.get("area", "扩展区")).strip() or "扩展区",
        latitude=float(payload.get("latitude", 31.2304)),
        longitude=float(payload.get("longitude", 121.4737)),
        device_mode=str(payload.get("device_mode", "physical")).strip() or "physical",
        protocol=str(payload.get("protocol", "HTTP")).strip() or "HTTP",
        ip_address=str(payload.get("ip_address", "")).strip() or None,
        port=int(payload["port"]) if payload.get("port") not in (None, "") else None,
        firmware_version=str(payload.get("firmware_version", "v1.0.0")).strip() or "v1.0.0",
        api_key=api_key,
        status="offline",
    )
    db.session.add(device)
    db.session.commit()
    return create_device_payload(device)


def update_device(device_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    device = Device.query.get_or_404(device_id)
    meter_id = str(payload.get("meter_id", device.meter_id)).strip()
    api_key = str(payload.get("api_key", device.api_key)).strip()
    duplicate_meter = Device.query.filter(Device.meter_id == meter_id, Device.id != device_id).first()
    duplicate_key = Device.query.filter(Device.api_key == api_key, Device.id != device_id).first()
    if duplicate_meter:
        raise ValueError("设备编号已存在。")
    if duplicate_key:
        raise ValueError("API Key 已存在。")

    device.meter_id = meter_id
    device.name = str(payload.get("name", device.name)).strip() or device.name
    device.location = str(payload.get("location", device.location)).strip() or device.location
    device.area = str(payload.get("area", device.area)).strip() or device.area
    device.latitude = float(payload.get("latitude", device.latitude))
    device.longitude = float(payload.get("longitude", device.longitude))
    device.device_mode = str(payload.get("device_mode", device.device_mode)).strip() or device.device_mode
    device.protocol = str(payload.get("protocol", device.protocol)).strip() or device.protocol
    device.ip_address = str(payload.get("ip_address", device.ip_address or "")).strip() or None
    device.port = int(payload["port"]) if payload.get("port") not in (None, "") else None
    device.firmware_version = (
        str(payload.get("firmware_version", device.firmware_version)).strip() or device.firmware_version
    )
    device.api_key = api_key
    db.session.commit()
    return create_device_payload(device)


def delete_device(device_id: int) -> None:
    device = Device.query.get_or_404(device_id)
    for order in WorkOrder.query.filter_by(device_id=device_id).all():
        db.session.delete(order)
    AnomalyEvent.query.filter_by(device_id=device_id).delete()
    MeterReading.query.filter_by(device_id=device_id).delete()
    db.session.delete(device)
    db.session.commit()


def test_device_connectivity(device_id: int) -> dict[str, Any]:
    device = Device.query.get_or_404(device_id)
    if device.status == "online" and device.last_seen_at and device.last_seen_at >= datetime.now() - timedelta(seconds=ONLINE_TIMEOUT_SECONDS):
        return {"success": True, "message": "设备最近有心跳上报，连通性正常。"}

    if device.ip_address and device.port:
        try:
            with socket.create_connection((device.ip_address, device.port), timeout=1.5):
                return {"success": True, "message": f"已成功连接 {device.ip_address}:{device.port}。"}
        except OSError:
            return {"success": False, "message": f"无法连接 {device.ip_address}:{device.port}。"}

    return {"success": False, "message": "设备暂无实时心跳，且未配置可测试的 IP/Port。"}


def engineers_snapshot() -> list[dict[str, Any]]:
    engineers = Engineer.query.order_by(Engineer.id.asc()).all()
    return [
        {
            "id": engineer.id,
            "name": engineer.name,
            "phone": engineer.phone,
            "specialty": engineer.specialty,
            "status": engineer.status,
            "region": engineer.region,
            "active_orders": WorkOrder.query.filter(
                WorkOrder.engineer_id == engineer.id, WorkOrder.status.in_(["assigned", "in_progress"])
            ).count(),
        }
        for engineer in engineers
    ]


def create_engineer(payload: dict[str, Any]) -> dict[str, Any]:
    engineer = Engineer(
        name=str(payload.get("name", "")).strip(),
        phone=str(payload.get("phone", "")).strip(),
        specialty=str(payload.get("specialty", "")).strip(),
        status=str(payload.get("status", "available")).strip() or "available",
        region=str(payload.get("region", "")).strip(),
    )
    if not engineer.name or not engineer.phone or not engineer.specialty or not engineer.region:
        raise ValueError("工程师姓名、电话、专长和片区不能为空。")
    db.session.add(engineer)
    db.session.commit()
    return engineers_snapshot()[-1]


def update_engineer(engineer_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    engineer = Engineer.query.get_or_404(engineer_id)
    engineer.name = str(payload.get("name", engineer.name)).strip() or engineer.name
    engineer.phone = str(payload.get("phone", engineer.phone)).strip() or engineer.phone
    engineer.specialty = str(payload.get("specialty", engineer.specialty)).strip() or engineer.specialty
    engineer.status = str(payload.get("status", engineer.status)).strip() or engineer.status
    engineer.region = str(payload.get("region", engineer.region)).strip() or engineer.region
    db.session.commit()
    return next(item for item in engineers_snapshot() if item["id"] == engineer.id)


def delete_engineer(engineer_id: int) -> None:
    engineer = Engineer.query.get_or_404(engineer_id)
    WorkOrder.query.filter_by(engineer_id=engineer_id).update({"engineer_id": None, "status": "pending", "current_stage": "pending"})
    db.session.delete(engineer)
    db.session.commit()


def work_orders_snapshot() -> list[dict[str, Any]]:
    orders = WorkOrder.query.order_by(WorkOrder.updated_at.desc()).all()
    return [_serialize_work_order(order) for order in orders]


def create_work_order(payload: dict[str, Any]) -> dict[str, Any]:
    device_id = int(payload.get("device_id"))
    engineer_id = payload.get("engineer_id")
    status = str(payload.get("status", "pending")).strip() or "pending"
    if engineer_id not in (None, "", 0, "0") and status == "pending":
        status = "assigned"

    order = WorkOrder(
        title=str(payload.get("title", "")).strip(),
        description=str(payload.get("description", "")).strip(),
        priority=str(payload.get("priority", "medium")).strip() or "medium",
        status=status,
        current_stage=STATUS_STAGE_MAP.get(status, "pending"),
        device_id=device_id,
        engineer_id=int(engineer_id) if engineer_id not in (None, "", 0, "0") else None,
    )
    if not order.title or not order.description:
        raise ValueError("工单标题和描述不能为空。")

    db.session.add(order)
    db.session.flush()

    _append_work_order_record(order, "创建工单", f"工单已创建，当前状态为 {work_order_stage_label(order.current_stage)}。")
    if order.engineer_id is not None:
        engineer = Engineer.query.get(order.engineer_id)
        engineer_name = engineer.name if engineer else "已分派"
        _append_work_order_record(order, "派单", f"已分派给 {engineer_name}。", stage="assigned")

    db.session.commit()
    return _serialize_work_order(order)


def update_work_order(order_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    order = WorkOrder.query.get_or_404(order_id)
    changes: list[str] = []

    title = str(payload.get("title", order.title)).strip() or order.title
    if title != order.title:
        changes.append(f"标题更新为“{title}”")
    order.title = title

    description = str(payload.get("description", order.description)).strip() or order.description
    if description != order.description:
        changes.append("描述已更新")
    order.description = description

    priority = str(payload.get("priority", order.priority)).strip() or order.priority
    if priority != order.priority:
        changes.append(f"优先级变更为 {priority}")
    order.priority = priority

    status = str(payload.get("status", order.status)).strip() or order.status
    if status != order.status:
        changes.append(f"状态切换为 {work_order_stage_label(status)}")
    order.status = status
    order.current_stage = STATUS_STAGE_MAP.get(status, order.current_stage)

    if payload.get("device_id") not in (None, "", 0, "0"):
        device_id = int(payload["device_id"])
        if device_id != order.device_id:
            changes.append("关联设备已调整")
        order.device_id = device_id

    engineer_payload = payload.get("engineer_id")
    if engineer_payload in (None, "", 0, "0"):
        if order.engineer_id is not None:
            changes.append("已取消工程师分配")
        order.engineer_id = None
    elif engineer_payload is not None:
        engineer_id = int(engineer_payload)
        if engineer_id != order.engineer_id:
            changes.append("已重新分配工程师")
        order.engineer_id = engineer_id

    db.session.flush()
    note = "；".join(changes) if changes else "工单信息已同步。"
    _append_work_order_record(order, "更新工单", note, stage=order.current_stage)
    db.session.commit()
    return _serialize_work_order(order)


def delete_work_order(order_id: int) -> None:
    order = WorkOrder.query.get_or_404(order_id)
    db.session.delete(order)
    db.session.commit()


def reports_snapshot() -> dict[str, Any]:
    total_orders = WorkOrder.query.count()
    open_orders = WorkOrder.query.filter(WorkOrder.status.in_(["pending", "assigned", "in_progress"])).count()
    completed_orders = WorkOrder.query.filter_by(status="completed").count()
    severity_counts = {"high": 0, "medium": 0, "low": 0}
    for event in AnomalyEvent.query.all():
        severity_counts[event.severity] = severity_counts.get(event.severity, 0) + 1
    return {
        "order_summary": {
            "total_orders": total_orders,
            "open_orders": open_orders,
            "completed_orders": completed_orders,
        },
        "severity_summary": severity_counts,
    }


def settings_snapshot() -> dict[str, Any]:
    return {
        "database_uri": get_database_uri(),
        "database_file": str(DATABASE_FILE),
        "device_upload_api": "/api/device/upload",
        "websocket_url": "/ws",
        "simulation_device_count": SIMULATION_DEVICE_COUNT,
    }


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

    recent_readings = MeterReading.query.filter_by(device_id=device.id).order_by(MeterReading.timestamp.asc()).all()
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
                severity=result.severity,
            )
        )

    db.session.commit()
    if emit_event:
        emit_realtime_updates()
    return reading


def ensure_database() -> None:
    ensure_directories()
    if get_database_uri().startswith("sqlite:///"):
        DATABASE_FILE.touch(exist_ok=True)
