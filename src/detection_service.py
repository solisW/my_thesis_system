from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import joblib
import numpy as np
import pandas as pd
import torch

from .config import FEATURE_COLUMNS, META_FILE, MODEL_FILE, SCALER_FILE, WINDOW_SIZE, ensure_directories
from .database import MeterReading
from .model import LSTMAutoEncoder
from .model_registry import active_model_version
from .preprocess import clean_dataset, transform_features
from .training_module import run_training_pipeline


@dataclass
class DetectionResult:
    anomaly_score: float
    threshold: float
    predicted_label: int
    anomaly_type: str
    description: str
    severity: str
    model_version: str | None


class DetectionService:
    def __init__(self) -> None:
        self.model: LSTMAutoEncoder | None = None
        self.scaler = None
        self.meta: dict[str, Any] | None = None
        self.device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        self.loaded_model_version: str | None = None

    def ensure_ready(self) -> None:
        ensure_directories()
        if not (MODEL_FILE.exists() and SCALER_FILE.exists() and META_FILE.exists()):
            run_training_pipeline(regenerate=True, reclean=True)

        current_version = active_model_version()
        needs_reload = self.model is None or self.loaded_model_version != current_version
        if needs_reload:
            self.scaler = joblib.load(SCALER_FILE)
            self.meta = json.loads(META_FILE.read_text(encoding="utf-8"))
            self.model = LSTMAutoEncoder(
                input_size=len(FEATURE_COLUMNS),
                hidden_size=self.meta["hidden_size"],
                num_layers=self.meta["num_layers"],
            ).to(self.device)
            self.model.load_state_dict(torch.load(MODEL_FILE, map_location=self.device))
            self.model.eval()
            self.loaded_model_version = current_version

    def score_recent_readings(self, readings: list[MeterReading]) -> DetectionResult:
        self.ensure_ready()
        if len(readings) < WINDOW_SIZE:
            latest = readings[-1]
            anomaly_score = self._bootstrap_score(latest, readings)
            threshold = 0.85
            predicted_label = int(anomaly_score > threshold and self._has_operational_anomaly(latest, readings))
            anomaly_type, description, severity = self._infer_anomaly_type(latest, readings, anomaly_score, threshold)
            return DetectionResult(
                anomaly_score,
                threshold,
                predicted_label,
                anomaly_type,
                description,
                severity,
                self.loaded_model_version,
            )

        frame = self._frame_from_readings(readings[-WINDOW_SIZE:])
        frame = clean_dataset(frame)
        transformed = transform_features(frame, self.scaler)
        window = transformed[FEATURE_COLUMNS].to_numpy(dtype=np.float32)

        with torch.no_grad():
            tensor = torch.tensor(window[None, :, :], dtype=torch.float32, device=self.device)
            reconstructed = self.model(tensor)
            anomaly_score = float(torch.mean((reconstructed - tensor) ** 2).cpu().item())

        latest = readings[-1]
        threshold = float(self.meta["threshold"])
        predicted_label = int(anomaly_score > threshold and self._has_operational_anomaly(latest, readings))
        anomaly_type, description, severity = self._infer_anomaly_type(latest, readings, anomaly_score, threshold)
        return DetectionResult(
            anomaly_score,
            threshold,
            predicted_label,
            anomaly_type,
            description,
            severity,
            self.loaded_model_version,
        )

    def reconstruction_trace(self, readings: list[MeterReading]) -> dict[str, Any]:
        self.ensure_ready()
        if len(readings) < WINDOW_SIZE:
            return {
                "ready": False,
                "required_window_size": WINDOW_SIZE,
                "available_points": len(readings),
                "model_version": self.loaded_model_version,
            }

        frame = self._frame_from_readings(readings[-WINDOW_SIZE:])
        cleaned = clean_dataset(frame)
        transformed = transform_features(cleaned, self.scaler)
        window = transformed[FEATURE_COLUMNS].to_numpy(dtype=np.float32)

        with torch.no_grad():
            tensor = torch.tensor(window[None, :, :], dtype=torch.float32, device=self.device)
            reconstructed = self.model(tensor).detach().cpu().numpy()[0]

        errors = np.mean((reconstructed - window) ** 2, axis=1)
        reconstructed_values = self.scaler.inverse_transform(reconstructed)
        reconstructed_frame = pd.DataFrame(reconstructed_values, columns=FEATURE_COLUMNS)

        return {
            "ready": True,
            "model_version": self.loaded_model_version,
            "threshold": float(self.meta["threshold"]),
            "feature_columns": FEATURE_COLUMNS,
            "timestamps": [item.isoformat() for item in cleaned["timestamp"]],
            "original": cleaned[FEATURE_COLUMNS].to_dict(orient="records"),
            "reconstructed": reconstructed_frame.to_dict(orient="records"),
            "error_series": [float(item) for item in errors],
            "anomaly_score": float(np.mean(errors)),
        }

    def _frame_from_readings(self, readings: list[MeterReading]) -> pd.DataFrame:
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
                for item in readings
            ]
        )
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
        return frame

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
        if len(recent_flows) >= 6 and max(recent_flows) < 0.01 and int(latest.valve_state) == 1:
            return "长时间流量静止", "阀门开启状态下最近窗口流量持续接近 0。", "medium"
        if latest.pressure < 1.4 or latest.pressure > 2.8:
            return "压力异常", f"管网压力为 {latest.pressure:.2f}。", "medium"
        if anomaly_score > threshold:
            return "综合异常", f"异常分数 {anomaly_score:.4f} 超过阈值 {threshold:.4f}。", "medium"
        return "正常", "数据处于正常波动范围。", "low"


detector = DetectionService()
