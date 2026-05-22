from __future__ import annotations

from datetime import datetime
from typing import Any

from .config import CARRIER_WEBHOOK_TOKEN
from .database import Device
from .device_integration import accept_device_reading, register_device_endpoint


FIELD_ALIASES = {
    "meter_id": ("meter_id", "meterId", "device_id", "deviceId", "imei", "IMEI"),
    "timestamp": ("timestamp", "time", "eventTime", "reportTime", "created_at"),
    "instant_flow": ("instant_flow", "instantFlow", "flow", "flowRate", "flow_rate"),
    "cumulative_usage": ("cumulative_usage", "cumulativeUsage", "totalUsage", "total_usage", "totalFlow"),
    "battery_voltage": ("battery_voltage", "batteryVoltage", "battery", "voltage", "cellVoltage"),
    "signal_strength": ("signal_strength", "signalStrength", "rssi", "RSSI", "rsrp"),
    "valve_state": ("valve_state", "valveState", "valve", "valveOpen"),
    "temperature": ("temperature", "temp", "envTemperature"),
    "pressure": ("pressure", "pipePressure", "networkPressure"),
}


def ingest_carrier_payload(
    provider: str,
    payload: dict[str, Any],
    request_token: str = "",
    *,
    async_detection: bool = True,
) -> dict[str, Any]:
    if CARRIER_WEBHOOK_TOKEN and request_token.strip() != CARRIER_WEBHOOK_TOKEN:
        raise ValueError("运营商接口令牌无效。")

    flat_payload = _flatten_payload(payload)
    meter_id = str(_pick(flat_payload, FIELD_ALIASES["meter_id"], "")).strip()
    if not meter_id:
        raise ValueError("运营商报文缺少设备编号。")

    device = Device.query.filter_by(meter_id=meter_id).first()
    if device is None:
        device = register_device_endpoint(
            {
                "meter_id": meter_id,
                "name": str(payload.get("name") or f"智能燃气表 {meter_id}"),
                "location": str(payload.get("location") or "运营商接入设备"),
                "area": str(payload.get("area") or "运营商片区"),
                "protocol": provider.upper(),
                "firmware_version": str(payload.get("firmware_version") or payload.get("firmwareVersion") or "unknown"),
            }
        )

    reading_payload = {
        "timestamp": _coerce_timestamp(_pick(flat_payload, FIELD_ALIASES["timestamp"], datetime.now())),
        "instant_flow": _pick(flat_payload, FIELD_ALIASES["instant_flow"]),
        "cumulative_usage": _pick(flat_payload, FIELD_ALIASES["cumulative_usage"]),
        "battery_voltage": _pick(flat_payload, FIELD_ALIASES["battery_voltage"]),
        "signal_strength": _pick(flat_payload, FIELD_ALIASES["signal_strength"]),
        "valve_state": _coerce_valve_state(_pick(flat_payload, FIELD_ALIASES["valve_state"], 1)),
        "temperature": _pick(flat_payload, FIELD_ALIASES["temperature"]),
        "pressure": _pick(flat_payload, FIELD_ALIASES["pressure"]),
    }
    device, reading = accept_device_reading(device.api_key, reading_payload, emit_event=True, async_detection=async_detection)
    return {
        "meter_id": device.meter_id,
        "provider": provider,
        "predicted_label": reading.predicted_label,
        "anomaly_score": reading.anomaly_score,
        "threshold": reading.threshold,
        "model_version": reading.model_version,
        "detection_status": "pending" if reading.anomaly_score is None else "completed",
    }


def _flatten_payload(payload: dict[str, Any]) -> dict[str, Any]:
    result = dict(payload)
    for key in ("data", "payload", "properties", "serviceData", "notifyData", "params"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            for nested_key, nested_value in nested.items():
                result.setdefault(nested_key, _unwrap_value(nested_value))
        elif isinstance(nested, list):
            for item in nested:
                if isinstance(item, dict):
                    name = item.get("name") or item.get("identifier") or item.get("key")
                    if name:
                        result.setdefault(str(name), _unwrap_value(item))
    return {key: _unwrap_value(value) for key, value in result.items()}


def _unwrap_value(value: Any) -> Any:
    if isinstance(value, dict):
        for key in ("value", "val", "data", "current"):
            if key in value:
                return value[key]
    return value


def _pick(payload: dict[str, Any], aliases: tuple[str, ...], default: Any = None) -> Any:
    for alias in aliases:
        if alias in payload and payload[alias] not in (None, ""):
            return payload[alias]
    if default is not None:
        return default
    raise ValueError(f"运营商报文缺少字段: {aliases[0]}")


def _coerce_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        number = float(value)
        if number > 10_000_000_000:
            number /= 1000
        return datetime.fromtimestamp(number)
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)


def _coerce_valve_state(value: Any) -> int:
    if isinstance(value, bool):
        return 1 if value else 0
    text = str(value).strip().lower()
    if text in {"open", "opened", "on", "true", "1", "开启", "打开"}:
        return 1
    if text in {"closed", "off", "false", "0", "关闭"}:
        return 0
    return int(float(text))
