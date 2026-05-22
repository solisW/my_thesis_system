from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from typing import Any

from .config import PHYSICAL_DATA_RETENTION_DAYS
from .database import Device, PhysicalDataRecord, db
from .services import ingest_reading


REQUIRED_READING_FIELDS = {
    "timestamp",
    "instant_flow",
    "cumulative_usage",
    "battery_voltage",
    "signal_strength",
    "valve_state",
    "temperature",
    "pressure",
}


def _coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled", "停用", "否"}


def register_device_endpoint(payload: dict[str, Any], *, trusted_update: bool = False) -> Device:
    meter_id = str(payload.get("meter_id", "")).strip()
    name = str(payload.get("name", "")).strip() or meter_id
    location = str(payload.get("location", "")).strip() or "未设置"
    requested_api_key = str(payload.get("api_key", "")).strip()
    current_api_key = str(payload.get("current_api_key", "")).strip()

    if not meter_id:
        raise ValueError("设备编号不能为空。")

    device = Device.query.filter_by(meter_id=meter_id).first()
    if device is None:
        api_key = requested_api_key or f"key-{secrets.token_hex(8)}"
        duplicate_key = Device.query.filter_by(api_key=api_key).first()
        if duplicate_key is not None:
            raise ValueError("API Key 已存在。")
        device = Device(
            meter_id=meter_id,
            name=name,
            location=location,
            area=str(payload.get("area", "扩展区")).strip() or "扩展区",
            latitude=float(payload.get("latitude", 31.2304)),
            longitude=float(payload.get("longitude", 121.4737)),
            device_mode="device",
            protocol=str(payload.get("protocol", "HTTP")).strip() or "HTTP",
            ip_address=str(payload.get("ip_address", "")).strip() or None,
            port=int(payload["port"]) if payload.get("port") not in (None, "") else None,
            firmware_version=str(payload.get("firmware_version", "v1.0.0")).strip() or "v1.0.0",
            api_key=api_key,
            is_enabled=_coerce_bool(payload.get("is_enabled"), True),
            status="offline",
        )
        db.session.add(device)
    else:
        presented_api_key = current_api_key or requested_api_key
        if not trusted_update and presented_api_key != device.api_key:
            raise ValueError("Invalid device API key.")
        api_key = requested_api_key or device.api_key
        if requested_api_key and api_key != device.api_key:
            duplicate_key = Device.query.filter(Device.api_key == api_key, Device.id != device.id).first()
            if duplicate_key is not None:
                raise ValueError("API Key 已存在。")
        device.name = name or device.name
        device.location = location or device.location
        device.area = str(payload.get("area", device.area)).strip() or device.area
        device.latitude = float(payload.get("latitude", device.latitude))
        device.longitude = float(payload.get("longitude", device.longitude))
        device.protocol = str(payload.get("protocol", device.protocol)).strip() or device.protocol
        device.ip_address = str(payload.get("ip_address", device.ip_address or "")).strip() or None
        device.port = int(payload["port"]) if payload.get("port") not in (None, "") else device.port
        device.firmware_version = str(payload.get("firmware_version", device.firmware_version)).strip() or device.firmware_version
        device.device_mode = "device"
        device.api_key = api_key
        if "is_enabled" in payload:
            device.is_enabled = _coerce_bool(payload.get("is_enabled"), device.is_enabled)
            if not device.is_enabled:
                device.status = "offline"

    db.session.commit()
    return device


def accept_device_reading(
    api_key: str,
    payload: dict[str, Any],
    *,
    emit_event: bool = True,
    async_detection: bool | None = None,
) -> tuple[Device, Any]:
    device = Device.query.filter_by(api_key=api_key.strip()).first()
    if device is None:
        raise ValueError("无效设备密钥。")

    normalized = _normalize_payload(payload)
    reading = ingest_reading(device, normalized, emit_event=emit_event, async_detection=async_detection)
    db.session.add(
        PhysicalDataRecord(
            device_id=device.id,
            meter_id=device.meter_id,
            timestamp=reading.timestamp,
            instant_flow=reading.instant_flow,
            cumulative_usage=reading.cumulative_usage,
            battery_voltage=reading.battery_voltage,
            signal_strength=reading.signal_strength,
            valve_state=reading.valve_state,
            temperature=reading.temperature,
            pressure=reading.pressure,
        )
    )
    db.session.commit()
    purge_expired_physical_data()
    return device, reading


def purge_expired_physical_data(retention_days: int = PHYSICAL_DATA_RETENTION_DAYS) -> int:
    cutoff = datetime.now() - timedelta(days=retention_days)
    deleted = PhysicalDataRecord.query.filter(PhysicalDataRecord.received_at < cutoff).delete()
    if deleted:
        db.session.commit()
    return int(deleted or 0)


def _normalize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    missing = sorted(REQUIRED_READING_FIELDS.difference(payload))
    if missing:
        raise ValueError(f"上传数据字段不完整: {', '.join(missing)}")

    normalized = dict(payload)
    normalized["timestamp"] = _coerce_datetime(payload["timestamp"])
    normalized["instant_flow"] = float(payload["instant_flow"])
    normalized["cumulative_usage"] = float(payload["cumulative_usage"])
    normalized["battery_voltage"] = float(payload["battery_voltage"])
    normalized["signal_strength"] = float(payload["signal_strength"])
    normalized["valve_state"] = int(payload["valve_state"])
    normalized["temperature"] = float(payload["temperature"])
    normalized["pressure"] = float(payload["pressure"])
    return normalized


def _coerce_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value))
