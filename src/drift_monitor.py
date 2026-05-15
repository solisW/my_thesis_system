from __future__ import annotations

import threading
import traceback
from datetime import datetime
from typing import Any, Callable

import numpy as np
import pandas as pd
from flask import Flask

from .config import (
    DRIFT_CHECK_INTERVAL_SECONDS,
    DRIFT_MIN_RECENT_POINTS,
    DRIFT_SCORE_THRESHOLD,
    FEATURE_COLUMNS,
)
from .database import MeterReading, TrainingCleanDataRecord


def detect_data_drift() -> dict[str, Any]:
    recent_rows = (
        MeterReading.query.order_by(MeterReading.timestamp.desc())
        .limit(max(DRIFT_MIN_RECENT_POINTS, 1))
        .all()
    )
    if len(recent_rows) < DRIFT_MIN_RECENT_POINTS:
        return {
            "checked_at": datetime.now().isoformat(),
            "drift_detected": False,
            "ready": False,
            "reason": "实时上报数据不足，暂不执行漂移判断。",
            "recent_points": len(recent_rows),
            "required_points": DRIFT_MIN_RECENT_POINTS,
        }

    baseline_rows = (
        TrainingCleanDataRecord.query.filter_by(is_injected_anomaly=False)
        .order_by(TrainingCleanDataRecord.timestamp.desc())
        .limit(max(DRIFT_MIN_RECENT_POINTS * 4, 1))
        .all()
    )
    if len(baseline_rows) < DRIFT_MIN_RECENT_POINTS:
        return {
            "checked_at": datetime.now().isoformat(),
            "drift_detected": False,
            "ready": False,
            "reason": "训练清洗数据不足，暂不执行漂移判断。",
            "recent_points": len(recent_rows),
            "baseline_points": len(baseline_rows),
        }

    recent = _frame_from_records(recent_rows)
    baseline = _frame_from_records(baseline_rows)
    baseline_mean = baseline[FEATURE_COLUMNS].mean()
    baseline_std = baseline[FEATURE_COLUMNS].std().replace(0, np.nan).fillna(1.0)
    recent_mean = recent[FEATURE_COLUMNS].mean()
    feature_shift = ((recent_mean - baseline_mean).abs() / baseline_std).fillna(0.0)
    score = float(feature_shift.mean())
    top_features = [
        {"feature": feature, "shift": float(value)}
        for feature, value in feature_shift.sort_values(ascending=False).head(5).items()
    ]
    drift_detected = score >= DRIFT_SCORE_THRESHOLD or any(item["shift"] >= DRIFT_SCORE_THRESHOLD * 1.8 for item in top_features)
    return {
        "checked_at": datetime.now().isoformat(),
        "ready": True,
        "drift_detected": bool(drift_detected),
        "score": score,
        "threshold": DRIFT_SCORE_THRESHOLD,
        "recent_points": len(recent_rows),
        "baseline_points": len(baseline_rows),
        "top_features": top_features,
        "reason": "检测到实时数据分布偏移。" if drift_detected else "数据分布稳定。",
    }


def _frame_from_records(rows: list[Any]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "instant_flow": row.instant_flow,
                "cumulative_usage": row.cumulative_usage,
                "battery_voltage": row.battery_voltage,
                "signal_strength": row.signal_strength,
                "valve_state": row.valve_state,
                "temperature": row.temperature,
                "pressure": row.pressure,
            }
            for row in rows
        ]
    )


class DriftMonitorService:
    def __init__(
        self,
        app: Flask,
        *,
        on_drift: Callable[[dict[str, Any]], None] | None = None,
        interval_seconds: int = DRIFT_CHECK_INTERVAL_SECONDS,
    ) -> None:
        self.app = app
        self.on_drift = on_drift
        self.interval_seconds = max(30, int(interval_seconds))
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._last_result: dict[str, Any] | None = None
        self._last_error: str | None = None
        self._triggered_count = 0

    def start(self) -> None:
        if self.is_running():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5)
        if self._thread and not self._thread.is_alive():
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def check_once(self) -> dict[str, Any]:
        with self.app.app_context():
            result = detect_data_drift()
        self._last_result = result
        if result.get("drift_detected") and self.on_drift:
            self._triggered_count += 1
            self.on_drift(result)
        return result

    def status(self) -> dict[str, Any]:
        return {
            "running": self.is_running(),
            "interval_seconds": self.interval_seconds,
            "last_result": self._last_result,
            "last_error": self._last_error,
            "triggered_count": self._triggered_count,
        }

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            try:
                self.check_once()
                self._last_error = None
            except Exception:
                self._last_error = traceback.format_exc(limit=6)
