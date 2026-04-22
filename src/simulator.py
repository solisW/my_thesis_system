from __future__ import annotations

import math
import random
import threading
from datetime import datetime

from flask import Flask

from .config import SIMULATION_INTERVAL_SECONDS
from .database import Device
from .services import emit_realtime_updates, ingest_reading


class MeterSimulator:
    def __init__(self, app: Flask) -> None:
        self.app = app
        self.interval_seconds = SIMULATION_INTERVAL_SECONDS
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._states: dict[str, dict[str, float]] = {}

    def start(self) -> None:
        if self._thread and self._thread.is_alive() and not self._stop_event.is_set():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.interval_seconds + 1)
        if self._thread and not self._thread.is_alive():
            self._thread = None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and not self._stop_event.is_set()

    def _run_loop(self) -> None:
        with self.app.app_context():
            while not self._stop_event.is_set():
                devices = Device.query.order_by(Device.meter_id.asc()).all()
                for index, device in enumerate(devices):
                    payload = self._generate_payload(device.meter_id, index)
                    ingest_reading(device, payload, source="simulated", emit_event=False)
                emit_realtime_updates()
                self._stop_event.wait(self.interval_seconds)

    def _generate_payload(self, meter_id: str, offset: int) -> dict[str, float | int | datetime]:
        state = self._states.setdefault(
            meter_id,
            {
                "step": 0.0,
                "cumulative_usage": 30 + random.uniform(0, 80),
                "battery_voltage": 3.55 - random.uniform(0, 0.08),
                "signal_strength": random.uniform(70, 88),
            },
        )

        state["step"] += 1
        phase = (state["step"] + offset * 2) / 10
        base_flow = 0.18 + 0.08 * math.sin(phase) + 0.04 * math.cos(phase / 2)
        instant_flow = max(0.02, base_flow + random.uniform(-0.03, 0.03))

        anomaly_trigger = random.random()
        if anomaly_trigger < 0.04:
            instant_flow *= random.uniform(2.5, 4.0)
        if anomaly_trigger > 0.95:
            state["battery_voltage"] -= random.uniform(0.10, 0.20)
        else:
            state["battery_voltage"] = max(2.55, state["battery_voltage"] - random.uniform(0.0003, 0.002))
        if 0.88 < anomaly_trigger < 0.92:
            state["signal_strength"] = random.uniform(10, 28)
        else:
            state["signal_strength"] = min(95, max(40, state["signal_strength"] + random.uniform(-3, 3)))

        temperature = 17 + 6 * math.sin(phase / 3) + random.uniform(-1.2, 1.2)
        pressure = 2.1 + 0.15 * math.sin(phase / 4) + random.uniform(-0.05, 0.05)
        if anomaly_trigger > 0.98:
            pressure += random.uniform(0.65, 0.95)

        state["cumulative_usage"] += instant_flow

        return {
            "timestamp": datetime.now(),
            "instant_flow": round(instant_flow, 4),
            "cumulative_usage": round(state["cumulative_usage"], 4),
            "battery_voltage": round(state["battery_voltage"], 3),
            "signal_strength": round(state["signal_strength"], 2),
            "valve_state": 1,
            "temperature": round(temperature, 2),
            "pressure": round(pressure, 3),
        }
