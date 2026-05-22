from __future__ import annotations

import math
import random
import threading
import traceback
from datetime import datetime

from flask import Flask

from .config import SIMULATION_DEVICE_COUNT, SIMULATION_INTERVAL_SECONDS
from .database import db
from .device_integration import accept_device_reading, register_device_endpoint


class SimulationModule:
    def __init__(self, app: Flask) -> None:
        self.app = app
        self.interval_seconds = SIMULATION_INTERVAL_SECONDS
        self.device_count = SIMULATION_DEVICE_COUNT
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._states: dict[str, dict[str, float]] = {}

    def start(self) -> None:
        if self.is_running():
            return
        with self.app.app_context():
            self._ensure_devices()
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

    def registered_count(self) -> int:
        return self.device_count

    def emit_once(self) -> None:
        with self.app.app_context():
            self._ensure_devices()
            self._emit_batch()

    def _ensure_devices(self) -> None:
        for index in range(1, self.device_count + 1):
            meter_id = self._meter_id(index)
            site = self._site_for(index)
            register_device_endpoint(
                {
                    "meter_id": meter_id,
                    "name": f"智能燃气表 {meter_id}",
                    "location": site["location"],
                    "area": site["area"],
                    "latitude": site["latitude"],
                    "longitude": site["longitude"],
                    "protocol": self._protocol_for(index),
                    "ip_address": f"10.42.{(index - 1) // 250}.{(index - 1) % 250 + 1}",
                    "port": 8600 + index,
                    "firmware_version": f"v2.{(index % 4) + 1}.{index % 9}",
                    "api_key": self._api_key(index),
                },
                trusted_update=True,
            )

    def _run_loop(self) -> None:
        with self.app.app_context():
            while not self._stop_event.is_set():
                self._emit_batch()
                self._stop_event.wait(self.interval_seconds)

    def _emit_batch(self) -> None:
        for index in range(1, self.device_count + 1):
            try:
                accept_device_reading(
                    self._api_key(index),
                    self._generate_payload(self._meter_id(index), index - 1),
                    emit_event=False,
                    async_detection=False,
                )
            except Exception:
                db.session.rollback()
                traceback.print_exc()
        from .services import emit_realtime_updates

        emit_realtime_updates()

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

    @staticmethod
    def _meter_id(index: int) -> str:
        return f"GM{9000 + index:04d}"

    @staticmethod
    def _api_key(index: int) -> str:
        return f"meter-key-{9000 + index:04d}"

    @staticmethod
    def _protocol_for(index: int) -> str:
        protocols = ["NB-IoT", "NB-IoT", "NB-IoT", "LoRa", "HTTP"]
        return protocols[(index - 1) % len(protocols)]

    @staticmethod
    def _site_for(index: int) -> dict[str, float | str]:
        sites = [
            ("静安区", "南京西路社区 1 号楼", 31.23187, 121.45474),
            ("静安区", "石门二路社区 2 号楼", 31.23510, 121.45989),
            ("静安区", "江宁路社区 3 号楼", 31.24008, 121.44861),
            ("黄浦区", "人民广场片区 4 号楼", 31.23012, 121.47536),
            ("黄浦区", "淮海中路社区 5 号楼", 31.22087, 121.46827),
            ("黄浦区", "打浦桥社区 6 号楼", 31.20724, 121.47036),
            ("徐汇区", "衡山路社区 7 号楼", 31.20451, 121.44624),
            ("徐汇区", "徐家汇社区 8 号楼", 31.19163, 121.43752),
            ("徐汇区", "田林社区 9 号楼", 31.17618, 121.41682),
            ("长宁区", "中山公园社区 10 号楼", 31.22018, 121.41729),
            ("长宁区", "虹桥路社区 11 号楼", 31.20072, 121.40325),
            ("长宁区", "天山路社区 12 号楼", 31.21524, 121.39816),
            ("普陀区", "长寿路社区 13 号楼", 31.24530, 121.43208),
            ("普陀区", "曹杨新村 14 号楼", 31.23880, 121.40772),
            ("普陀区", "真如社区 15 号楼", 31.24991, 121.39857),
            ("虹口区", "四川北路社区 16 号楼", 31.25612, 121.48572),
            ("虹口区", "鲁迅公园社区 17 号楼", 31.27031, 121.48396),
            ("杨浦区", "五角场社区 18 号楼", 31.30071, 121.51469),
            ("杨浦区", "控江路社区 19 号楼", 31.28266, 121.52918),
            ("杨浦区", "鞍山新村 20 号楼", 31.27962, 121.50931),
            ("浦东新区", "陆家嘴社区 21 号楼", 31.23593, 121.50252),
            ("浦东新区", "世纪公园社区 22 号楼", 31.21654, 121.55137),
            ("浦东新区", "花木社区 23 号楼", 31.20931, 121.54064),
            ("浦东新区", "金桥社区 24 号楼", 31.25594, 121.58912),
            ("浦东新区", "张江社区 25 号楼", 31.20702, 121.61039),
        ]
        area, location, lat, lng = sites[(index - 1) % len(sites)]
        lap = (index - 1) // len(sites)
        return {
            "area": area,
            "location": location if lap == 0 else f"{location} 东区 {lap + 1} 组",
            "latitude": lat + lap * 0.00045,
            "longitude": lng + lap * 0.00045,
        }
