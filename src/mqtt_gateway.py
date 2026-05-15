from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Any

from flask import Flask

from .config import MQTT_HOST, MQTT_PASSWORD, MQTT_PORT, MQTT_REGISTER_TOPIC, MQTT_UPLOAD_TOPIC, MQTT_USERNAME
from .device_integration import accept_device_reading, register_device_endpoint
from .services import emit_realtime_updates


class MqttGateway:
    def __init__(self, app: Flask) -> None:
        self.app = app
        self._client: Any | None = None
        self._lock = threading.Lock()
        self._running = False
        self._last_error: str | None = None
        self._last_message_at: str | None = None
        self._received_messages = 0

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            try:
                import paho.mqtt.client as mqtt
            except ImportError as exc:
                self._last_error = "未安装 paho-mqtt，无法启动 MQTT 网关。"
                raise RuntimeError(self._last_error) from exc

            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
            if MQTT_USERNAME:
                client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD or None)
            client.on_connect = self._on_connect
            client.on_message = self._on_message
            client.on_disconnect = self._on_disconnect
            client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
            client.loop_start()
            self._client = client
            self._running = True
            self._last_error = None

    def stop(self) -> None:
        with self._lock:
            if self._client is not None:
                self._client.loop_stop()
                self._client.disconnect()
            self._client = None
            self._running = False

    def status(self) -> dict[str, Any]:
        return {
            "running": self._running,
            "host": MQTT_HOST,
            "port": MQTT_PORT,
            "register_topic": MQTT_REGISTER_TOPIC,
            "upload_topic": MQTT_UPLOAD_TOPIC,
            "last_error": self._last_error,
            "last_message_at": self._last_message_at,
            "received_messages": self._received_messages,
        }

    def _on_connect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        if int(reason_code) != 0:
            self._last_error = f"MQTT 连接失败: {reason_code}"
            return
        client.subscribe(MQTT_REGISTER_TOPIC)
        client.subscribe(MQTT_UPLOAD_TOPIC)

    def _on_disconnect(self, client: Any, userdata: Any, flags: Any, reason_code: Any, properties: Any = None) -> None:
        self._running = False
        if int(reason_code) != 0:
            self._last_error = f"MQTT 连接断开: {reason_code}"

    def _on_message(self, client: Any, userdata: Any, message: Any) -> None:
        try:
            payload = json.loads(message.payload.decode("utf-8"))
            topic = str(message.topic)
            with self.app.app_context():
                if topic == MQTT_REGISTER_TOPIC:
                    register_device_endpoint(payload)
                else:
                    api_key = str(payload.pop("api_key", "")).strip()
                    if not api_key:
                        raise ValueError("MQTT 上报报文必须包含 api_key 字段。")
                    accept_device_reading(api_key, payload, emit_event=False, async_detection=True)
                emit_realtime_updates()
            self._received_messages += 1
            self._last_message_at = datetime.now().isoformat()
            self._last_error = None
        except Exception as exc:
            self._last_error = str(exc)
