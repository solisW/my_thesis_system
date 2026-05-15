from __future__ import annotations

import hashlib
import os
import re
import secrets
import socket
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from typing import Any

from flask import current_app, has_app_context
from sqlalchemy.exc import IntegrityError, OperationalError

from .config import (
    ASYNC_DETECTION_ENABLED,
    ASYNC_DETECTION_WORKERS,
    DATABASE_FILE,
    ENGINEER_ONLINE_TIMEOUT_SECONDS,
    ONLINE_TIMEOUT_SECONDS,
    PHYSICAL_DATA_RETENTION_DAYS,
    WINDOW_SIZE,
    ensure_directories,
    get_database_uri,
)
from .detection_service import detector
from .model_registry import active_model_metadata
from .database import (
    AnomalyEvent,
    Device,
    Engineer,
    MeterReading,
    ModelMetadata,
    PhysicalDataRecord,
    TrainingCleanDataRecord,
    TrainingRawDataRecord,
    User,
    WorkOrder,
    WorkOrderRecord,
    db,
    work_order_stage_label,
)
from .realtime import hub
from .security import cipher
from .training_store import import_training_seed_data
from .training_repository import training_database_health


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}
DETECTION_EXECUTOR = ThreadPoolExecutor(max_workers=ASYNC_DETECTION_WORKERS, thread_name_prefix="gas-detect")
STATUS_STAGE_MAP = {
    "pending": "pending",
    "assigned": "assigned",
    "in_progress": "in_progress",
    "completed": "completed",
}
WORK_ORDER_FLOW = ["pending", "assigned", "in_progress", "completed"]
TRANSIENT_MYSQL_ERROR_CODES = {1205, 1213}
ROLE_LABELS = {
    "super_admin": "主管理员",
    "sub_admin": "管理员",
    "admin": "管理员",
    "engineer": "工程师",
}


def _is_transient_database_error(exc: Exception) -> bool:
    if not isinstance(exc, OperationalError):
        return False
    original = getattr(exc, "orig", None)
    code = None
    if original is not None and getattr(original, "args", None):
        code = original.args[0]
    return code in TRANSIENT_MYSQL_ERROR_CODES


def role_label(role: str | None) -> str:
    return ROLE_LABELS.get(role or "", role or "未知角色")


def username_lookup_value(username: str) -> str:
    return hashlib.sha256(username.strip().lower().encode("utf-8")).hexdigest()


def sensitive_lookup_value(value: str) -> str:
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()


def encrypted_placeholder(prefix: str, lookup: str | None) -> str:
    suffix = (lookup or "empty")[:16]
    return f"{prefix}-{suffix}"


def encrypted_text(record: Any, encrypted_attr: str, legacy_attr: str | None = None, default: str = "") -> str:
    token = getattr(record, encrypted_attr, None)
    if token:
        decrypted = cipher.decrypt(str(token))
        if decrypted is not None:
            return decrypted
    if legacy_attr is None:
        return default
    legacy = getattr(record, legacy_attr, None)
    if legacy in (None, "", "已加密用户", "已加密工程师", "[encrypted]"):
        return default
    legacy_text = str(legacy)
    if legacy_text.startswith(("user-", "emp-", "eng-", "region-")):
        return default
    return legacy_text


def user_username(user: User) -> str:
    return encrypted_text(user, "username_encrypted", "username")


def user_full_name(user: User) -> str:
    return encrypted_text(user, "full_name_encrypted", "full_name", "已加密用户")


def user_employee_no(user: User) -> str:
    return encrypted_text(user, "employee_no_encrypted", "employee_no")


def user_phone(user: User) -> str:
    return encrypted_text(user, "phone_encrypted", "phone")


def user_avatar_data(user: User) -> str:
    return encrypted_text(user, "avatar_data_encrypted", "avatar_data")


def engineer_name(engineer: Engineer) -> str:
    return encrypted_text(engineer, "name_encrypted", "name", "已加密工程师")


def engineer_employee_no(engineer: Engineer) -> str:
    return encrypted_text(engineer, "employee_no_encrypted", "employee_no")


def engineer_phone(engineer: Engineer) -> str:
    return encrypted_text(engineer, "phone_encrypted", "phone")


def engineer_avatar_data(engineer: Engineer) -> str:
    return encrypted_text(engineer, "avatar_data_encrypted", "avatar_data")


def engineer_region(engineer: Engineer) -> str:
    return encrypted_text(engineer, "region_encrypted", "region")


def engineer_address(engineer: Engineer) -> str:
    return encrypted_text(engineer, "address_encrypted", "address")


def coerce_bool(value: Any, default: bool = True) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled", "停用", "否"}


def sync_user_credentials(user: User, username: str, password: str | None = None) -> None:
    user.username_encrypted = cipher.encrypt(username)
    user.username_lookup = username_lookup_value(username)
    user.username = encrypted_placeholder("user", user.username_lookup)
    if password is not None:
        user.password_hash = cipher.encrypt(password)


def sync_user_profile(user: User, *, full_name: str, employee_no: str, phone: str, avatar_data: str = "") -> None:
    employee_lookup = sensitive_lookup_value(employee_no) if employee_no else None
    user.full_name_encrypted = cipher.encrypt(full_name)
    user.employee_no_encrypted = cipher.encrypt(employee_no) if employee_no else None
    user.employee_no_lookup = employee_lookup
    user.phone_encrypted = cipher.encrypt(phone) if phone else None
    user.avatar_data_encrypted = cipher.encrypt(avatar_data) if avatar_data else None
    user.full_name = "已加密用户"
    user.employee_no = encrypted_placeholder("emp", employee_lookup) if employee_lookup else None
    user.phone = "[encrypted]" if phone else ""
    user.avatar_data = "[encrypted]" if avatar_data else ""


def sync_engineer_profile(
    engineer: Engineer,
    *,
    employee_no: str,
    full_name: str,
    phone: str,
    avatar_data: str,
    region: str,
    address: str,
) -> None:
    employee_lookup = sensitive_lookup_value(employee_no)
    region_lookup = sensitive_lookup_value(region)
    engineer.employee_no_encrypted = cipher.encrypt(employee_no)
    engineer.employee_no_lookup = employee_lookup
    engineer.avatar_data_encrypted = cipher.encrypt(avatar_data) if avatar_data else None
    engineer.name_encrypted = cipher.encrypt(full_name)
    engineer.phone_encrypted = cipher.encrypt(phone)
    engineer.region_encrypted = cipher.encrypt(region)
    engineer.region_lookup = region_lookup
    engineer.address_encrypted = cipher.encrypt(address) if address else None
    engineer.employee_no = encrypted_placeholder("eng", employee_lookup)
    engineer.avatar_data = "[encrypted]" if avatar_data else ""
    engineer.name = "已加密工程师"
    engineer.phone = "[encrypted]"
    engineer.region = encrypted_placeholder("region", region_lookup)
    engineer.address = "[encrypted]" if address else ""


def migrate_sensitive_identity_fields() -> None:
    for user in User.query.all():
        if not user.username_lookup or not user.username_encrypted:
            sync_user_credentials(user, user.username)
        if not user.full_name_encrypted:
            sync_user_profile(
                user,
                full_name=encrypted_text(user, "full_name_encrypted", "full_name", user.username),
                employee_no=encrypted_text(user, "employee_no_encrypted", "employee_no"),
                phone=encrypted_text(user, "phone_encrypted", "phone"),
                avatar_data=encrypted_text(user, "avatar_data_encrypted", "avatar_data"),
            )
    for engineer in Engineer.query.all():
        if not engineer.employee_no_encrypted:
            sync_engineer_profile(
                engineer,
                employee_no=encrypted_text(engineer, "employee_no_encrypted", "employee_no"),
                full_name=encrypted_text(engineer, "name_encrypted", "name", "已加密工程师"),
                phone=encrypted_text(engineer, "phone_encrypted", "phone"),
                avatar_data=encrypted_text(engineer, "avatar_data_encrypted", "avatar_data"),
                region=encrypted_text(engineer, "region_encrypted", "region"),
                address=encrypted_text(engineer, "address_encrypted", "address"),
            )


def _jittered_coordinate(meter_id: str, latitude: float, longitude: float) -> tuple[float, float]:
    digest = hashlib.sha1(meter_id.encode("utf-8")).digest()
    lat_offset = ((digest[0] / 255.0) - 0.5) * 0.004
    lng_offset = ((digest[1] / 255.0) - 0.5) * 0.005
    return latitude + lat_offset, longitude + lng_offset


def _seed_system_users() -> None:
    super_admin_password = os.getenv("SUPER_ADMIN_PASSWORD", "777803wzw@")
    defaults = [
        {"username": "solisW", "full_name": "主管理员", "password": super_admin_password, "role": "super_admin"},
    ]
    for row in defaults:
        user = User.query.filter_by(username_lookup=username_lookup_value(row["username"])).first()
        if user is None:
            user = User.query.filter_by(username=row["username"]).first()
        if user is None:
            user = User(
                username=encrypted_placeholder("user", username_lookup_value(row["username"])),
                full_name="已加密用户",
                role=row["role"],
                is_active=True,
                phone="",
            )
            sync_user_credentials(user, row["username"], row["password"])
            sync_user_profile(user, full_name=row["full_name"], employee_no="", phone="", avatar_data="")
            db.session.add(user)
        if row["username"] == "solisW":
            sync_user_profile(
                user,
                full_name=row["full_name"],
                employee_no=user_employee_no(user),
                phone=user_phone(user),
                avatar_data=user_avatar_data(user),
            )
            user.role = "super_admin"
            user.is_active = True
            sync_user_credentials(user, row["username"], row["password"])
        elif user.role == "admin":
            user.role = "sub_admin"

    legacy_admin = User.query.filter_by(username_lookup=username_lookup_value("admin")).first()
    if legacy_admin is not None:
        has_related_orders = WorkOrder.query.filter(
            (WorkOrder.created_by_user_id == legacy_admin.id)
            | (WorkOrder.assigned_by_user_id == legacy_admin.id)
            | (WorkOrder.accepted_by_user_id == legacy_admin.id)
        ).first()
        if has_related_orders is None:
            db.session.delete(legacy_admin)


def _cleanup_legacy_default_engineers() -> None:
    legacy_rows = {
        ("张工", "13800010001", "A区"),
        ("李工", "13800010002", "B区"),
        ("王工", "13800010003", "C区"),
        ("赵工", "13800010004", "D区"),
    }
    engineers = Engineer.query.order_by(Engineer.id.asc()).all()
    for engineer in engineers:
        row_key = (engineer_name(engineer), engineer_phone(engineer), engineer_region(engineer))
        if row_key not in legacy_rows:
            continue
        if engineer.user_account is not None:
            continue
        WorkOrder.query.filter_by(engineer_id=engineer.id).update(
            {"engineer_id": None, "status": "pending", "current_stage": "pending"}
        )
        db.session.delete(engineer)


def import_seed_datasets() -> None:
    import_training_seed_data()


def normalize_device_metadata() -> None:
    Device.query.filter(Device.device_mode != "device").update({"device_mode": "device"}, synchronize_session=False)
    MeterReading.query.filter(MeterReading.source != "device").update({"source": "device"}, synchronize_session=False)


def _cleanup_legacy_simulation_devices() -> None:
    legacy_devices = [
        device
        for device in Device.query.filter(Device.meter_id.like("SIM%")).all()
        if re.fullmatch(r"SIM\d{3}", device.meter_id or "")
        and device.api_key == f"sim-key-{int(device.meter_id[3:]):03d}"
    ]
    if not legacy_devices:
        return

    legacy_device_ids = [device.id for device in legacy_devices]
    legacy_events = AnomalyEvent.query.filter(AnomalyEvent.device_id.in_(legacy_device_ids)).all()
    legacy_event_ids = [event.id for event in legacy_events]
    legacy_orders_query = WorkOrder.query.filter(WorkOrder.device_id.in_(legacy_device_ids))
    if legacy_event_ids:
        legacy_orders_query = legacy_orders_query.union(
            WorkOrder.query.filter(WorkOrder.anomaly_event_id.in_(legacy_event_ids))
        )
    legacy_order_ids = [order.id for order in legacy_orders_query.all()]

    if legacy_order_ids:
        WorkOrderRecord.query.filter(WorkOrderRecord.work_order_id.in_(legacy_order_ids)).delete(synchronize_session=False)
        WorkOrder.query.filter(WorkOrder.id.in_(legacy_order_ids)).delete(synchronize_session=False)
    if legacy_event_ids:
        AnomalyEvent.query.filter(AnomalyEvent.id.in_(legacy_event_ids)).delete(synchronize_session=False)
    PhysicalDataRecord.query.filter(PhysicalDataRecord.device_id.in_(legacy_device_ids)).delete(synchronize_session=False)
    MeterReading.query.filter(MeterReading.device_id.in_(legacy_device_ids)).delete(synchronize_session=False)
    Device.query.filter(Device.id.in_(legacy_device_ids)).delete(synchronize_session=False)


def seed_defaults() -> None:
    admin = User.query.filter(
        (User.username == "admin") | (User.username_lookup == username_lookup_value("admin"))
    ).first()
    if admin is not None and (not admin.username_lookup or not admin.username_encrypted):
        sync_user_credentials(admin, admin.username)

    try:
        db.session.commit()
    except IntegrityError:
        # Another process may have inserted the bootstrap account while this
        # process was starting. Roll back and normalize the row that won.
        db.session.rollback()
        admin = User.query.filter(
            (User.username == "admin") | (User.username_lookup == username_lookup_value("admin"))
        ).first()
        if admin is None:
            raise
        if not admin.username_lookup or not admin.username_encrypted:
            sync_user_credentials(admin, admin.username)
            db.session.commit()


def ensure_access_bootstrap() -> None:
    for attempt in range(2):
        try:
            _seed_system_users()
            _cleanup_legacy_default_engineers()
            normalize_device_metadata()
            _cleanup_legacy_simulation_devices()
            migrate_sensitive_identity_fields()
            import_seed_datasets()
            db.session.commit()
            return
        except IntegrityError:
            db.session.rollback()
            if attempt == 1:
                raise


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
        "region": order.region,
        "priority": order.priority,
        "status": order.status,
        "current_stage": current_stage,
        "current_stage_label": work_order_stage_label(current_stage),
        "device_id": order.device_id,
        "anomaly_event_id": order.anomaly_event_id,
        "anomaly_type": order.anomaly_event.anomaly_type if order.anomaly_event else None,
        "anomaly_score": order.anomaly_event.score if order.anomaly_event else None,
        "anomaly_threshold": order.anomaly_event.threshold if order.anomaly_event else None,
        "device_name": order.device.name if order.device else "未关联设备",
        "meter_id": order.device.meter_id if order.device else "-",
        "engineer_id": order.engineer_id,
        "engineer_name": engineer_name(order.engineer) if order.engineer else "未分配",
        "created_by_user_id": order.created_by_user_id,
        "created_by_name": user_full_name(order.created_by) if order.created_by else "系统",
        "assigned_by_user_id": order.assigned_by_user_id,
        "assigned_by_name": user_full_name(order.assigned_by) if order.assigned_by else None,
        "accepted_by_user_id": order.accepted_by_user_id,
        "accepted_by_name": user_full_name(order.accepted_by) if order.accepted_by else None,
        "accepted_at": order.accepted_at.isoformat() if order.accepted_at else None,
        "completion_note": order.completion_note,
        "dispatch_rank": order.dispatch_rank,
        "is_super_admin_priority": order.dispatch_rank >= 100,
        "priority_label": "最高优先" if order.dispatch_rank >= 100 else order.priority,
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
        next_status = "online" if device.is_enabled and device.last_seen_at and device.last_seen_at >= cutoff else "offline"
        if device.status != next_status:
            device.status = next_status
            changed = True
    if changed:
        db.session.commit()


def refresh_engineer_statuses() -> None:
    cutoff = datetime.now() - timedelta(seconds=ENGINEER_ONLINE_TIMEOUT_SECONDS)
    changed = False
    for engineer in Engineer.query.all():
        next_online = bool(engineer.last_online_at and engineer.last_online_at >= cutoff)
        if engineer.is_online != next_online:
            engineer.is_online = next_online
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
        "protocol": device.protocol,
        "ip_address": device.ip_address,
        "port": device.port,
        "firmware_version": device.firmware_version,
        "api_key": device.api_key,
        "is_enabled": bool(device.is_enabled),
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
        is_abnormal = bool(device.status == "online" and latest and latest["predicted_label"] == 1)
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
                "display_latitude": payload["latitude"],
                "display_longitude": payload["longitude"],
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
    rows: list[dict[str, Any]] = []
    for event in events:
        device = event.device
        rows.append(
            {
                "id": event.id,
                "meter_id": device.meter_id if device else "-",
                "device_name": device.name if device else "已删除设备",
                "location": device.location if device else "-",
                "severity": event.severity,
                "status": event.status,
                "anomaly_type": event.anomaly_type,
                "description": event.description,
                "score": event.score,
                "threshold": event.threshold,
                "model_version": event.model_version,
                "work_order_id": event.work_order.id if event.work_order else None,
                "confirmed_label": event.confirmed_label,
                "handled_at": event.handled_at.isoformat() if event.handled_at else None,
                "created_at": event.created_at.isoformat(),
            }
        )
    return rows


def update_alert_feedback(alert_id: int, confirmed_label: str) -> dict[str, Any]:
    event = AnomalyEvent.query.get_or_404(alert_id)
    normalized = confirmed_label.strip().lower()
    if normalized not in {"confirmed_anomaly", "false_positive", "ignored"}:
        raise ValueError("不支持的告警标记。")
    event.confirmed_label = normalized
    if normalized in {"false_positive", "ignored"}:
        event.status = "completed"
        event.handled_at = datetime.now()
    elif event.work_order is not None:
        event.status = event.work_order.status
    else:
        event.status = "open"
    db.session.commit()
    return {
        "id": event.id,
        "confirmed_label": event.confirmed_label,
        "status": event.status,
    }


def labeled_samples_snapshot(limit: int = 100) -> list[dict[str, Any]]:
    events = AnomalyEvent.query.filter(AnomalyEvent.confirmed_label.isnot(None)).all()
    events = sorted(
        events,
        key=lambda event: event.handled_at or event.created_at,
        reverse=True,
    )[:limit]
    rows: list[dict[str, Any]] = []
    for event in events:
        device = event.device
        rows.append(
            {
                "id": event.id,
                "meter_id": device.meter_id if device else "-",
                "device_name": device.name if device else "已删除设备",
                "anomaly_type": event.anomaly_type,
                "score": event.score,
                "threshold": event.threshold,
                "confirmed_label": event.confirmed_label,
                "status": event.status,
                "handled_at": event.handled_at.isoformat() if event.handled_at else None,
                "created_at": event.created_at.isoformat(),
                "model_version": event.model_version,
            }
        )
    return rows


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
                "threshold": item.threshold,
                "model_version": item.model_version,
            }
            for item in readings
        ],
        "meter_id": meter_id,
    }


def reconstruction_snapshot(meter_id: str | None = None) -> dict[str, Any]:
    query = Device.query
    if meter_id:
        query = query.filter(Device.meter_id == meter_id)
    device = query.order_by(Device.last_seen_at.desc(), Device.meter_id.asc()).first()
    if device is None:
        return {"ready": False, "message": "未找到可分析设备。"}

    readings = (
        MeterReading.query.filter_by(device_id=device.id)
        .order_by(MeterReading.timestamp.desc())
        .limit(WINDOW_SIZE)
        .all()
    )
    readings = list(reversed(readings))
    trace = detector.reconstruction_trace(readings)
    trace["meter_id"] = device.meter_id
    trace["device_name"] = device.name
    trace["location"] = device.location
    return trace


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
        device_mode="device",
        protocol=str(payload.get("protocol", "HTTP")).strip() or "HTTP",
        ip_address=str(payload.get("ip_address", "")).strip() or None,
        port=int(payload["port"]) if payload.get("port") not in (None, "") else None,
        firmware_version=str(payload.get("firmware_version", "v1.0.0")).strip() or "v1.0.0",
        api_key=api_key,
        is_enabled=coerce_bool(payload.get("is_enabled"), True),
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
    device.protocol = str(payload.get("protocol", device.protocol)).strip() or device.protocol
    device.ip_address = str(payload.get("ip_address", device.ip_address or "")).strip() or None
    device.port = int(payload["port"]) if payload.get("port") not in (None, "") else None
    device.firmware_version = (
        str(payload.get("firmware_version", device.firmware_version)).strip() or device.firmware_version
    )
    device.api_key = api_key
    if "is_enabled" in payload:
        device.is_enabled = coerce_bool(payload.get("is_enabled"), device.is_enabled)
        if not device.is_enabled:
            device.status = "offline"
    db.session.commit()
    return create_device_payload(device)


def set_device_enabled(device_id: int, is_enabled: bool) -> dict[str, Any]:
    device = Device.query.get_or_404(device_id)
    device.is_enabled = coerce_bool(is_enabled, device.is_enabled)
    if not device.is_enabled:
        device.status = "offline"
    db.session.commit()
    return create_device_payload(device)


def delete_device(device_id: int) -> None:
    device = Device.query.get_or_404(device_id)
    for order in WorkOrder.query.filter_by(device_id=device_id).all():
        db.session.delete(order)
    AnomalyEvent.query.filter_by(device_id=device_id).delete()
    MeterReading.query.filter_by(device_id=device_id).delete()
    PhysicalDataRecord.query.filter_by(device_id=device_id).delete()
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


def _serialize_user(user: User) -> dict[str, Any]:
    engineer = user.engineer_profile if user.role == "engineer" else None
    return {
        "id": user.id,
        "username": user_username(user),
        "full_name": user_full_name(user),
        "employee_no": user_employee_no(user),
        "phone": user_phone(user),
        "avatar_data": user_avatar_data(user),
        "role": "sub_admin" if user.role == "admin" else user.role,
        "role_label": role_label(user.role),
        "engineer_id": user.engineer_id,
        "engineer_region": engineer_region(engineer) if engineer else "",
        "engineer_address": engineer_address(engineer) if engineer else "",
        "is_active": bool(user.is_active),
        "created_at": user.created_at.isoformat(),
    }


def users_snapshot() -> list[dict[str, Any]]:
    users = User.query.order_by(User.created_at.asc(), User.id.asc()).all()
    return [_serialize_user(user) for user in users]


def _delete_engineer_profile(engineer_id: int | None) -> None:
    if not engineer_id:
        return
    WorkOrder.query.filter_by(engineer_id=engineer_id).update({"engineer_id": None, "status": "pending", "current_stage": "pending"})
    engineer = Engineer.query.get(engineer_id)
    if engineer is not None:
        db.session.delete(engineer)


def _ensure_engineer_profile_for_user(
    *,
    employee_no: str,
    full_name: str,
    phone: str,
    avatar_data: str,
    region: str,
    address: str,
    existing_engineer_id: int | None = None,
) -> Engineer:
    engineer = None
    if existing_engineer_id:
        engineer = Engineer.query.get(existing_engineer_id)
    if engineer is None:
        engineer = Engineer.query.filter_by(employee_no_lookup=sensitive_lookup_value(employee_no)).first()
    if engineer is None:
        engineer = Engineer(
            employee_no=encrypted_placeholder("eng", sensitive_lookup_value(employee_no)),
            avatar_data="",
            name="已加密工程师",
            phone="[encrypted]",
            specialty="",
            address="[encrypted]" if address else "",
            is_online=False,
            last_online_at=None,
            status="available",
            region=encrypted_placeholder("region", sensitive_lookup_value(region)),
        )
        db.session.add(engineer)
        db.session.flush()
    sync_engineer_profile(
        engineer,
        employee_no=employee_no,
        full_name=full_name,
        phone=phone,
        avatar_data=avatar_data,
        region=region,
        address=address,
    )
    return engineer


def create_user(payload: dict[str, Any]) -> dict[str, Any]:
    username = str(payload.get("username", "")).strip()
    full_name = str(payload.get("full_name", "")).strip()
    employee_no = str(payload.get("employee_no", "")).strip()
    phone = str(payload.get("phone", "")).strip()
    region = str(payload.get("region", "")).strip()
    address = str(payload.get("address", "")).strip()
    avatar_data = str(payload.get("avatar_data", "")).strip()
    password = str(payload.get("password", "")).strip()
    role = str(payload.get("role", "")).strip() or "sub_admin"
    role = "sub_admin" if role == "admin" else role
    if role not in {"sub_admin", "engineer"}:
        raise ValueError("不支持的账号角色。")
    if not username or not full_name or not employee_no or not password or not phone:
        raise ValueError("账户名、姓名、员工编号、电话和密码不能为空。")
    if role == "engineer" and (not region or not address):
        raise ValueError("工程师账号必须填写分管片区和住址，才能参与工单自动分配。")
    if User.query.filter_by(username_lookup=username_lookup_value(username)).first():
        raise ValueError("用户名已存在。")
    if User.query.filter_by(employee_no_lookup=sensitive_lookup_value(employee_no)).first():
        raise ValueError("员工编号已存在。")
    engineer_id = None
    if role == "engineer":
        engineer = Engineer.query.filter_by(employee_no_lookup=sensitive_lookup_value(employee_no)).first()
        if engineer is not None and User.query.filter_by(engineer_id=engineer.id).first():
            raise ValueError("该工程师档案已存在登录账号。")
        engineer_id = engineer.id if engineer is not None else None

    user = User(
        username=encrypted_placeholder("user", username_lookup_value(username)),
        full_name="已加密用户",
        employee_no=encrypted_placeholder("emp", sensitive_lookup_value(employee_no)),
        phone="[encrypted]",
        avatar_data="",
        role=role,
        engineer_id=engineer_id,
        is_active=bool(payload.get("is_active", True)),
    )
    sync_user_credentials(user, username, password)
    sync_user_profile(user, full_name=full_name, employee_no=employee_no, phone=phone, avatar_data=avatar_data)
    db.session.add(user)
    db.session.flush()
    if role == "engineer":
        engineer = _ensure_engineer_profile_for_user(
            employee_no=employee_no,
            full_name=full_name,
            phone=phone,
            avatar_data=avatar_data,
            region=region,
            address=address,
            existing_engineer_id=user.engineer_id,
        )
        user.engineer_id = engineer.id
    db.session.commit()
    return _serialize_user(user)


def update_user(user_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    user = User.query.get_or_404(user_id)
    role = str(payload.get("role", user.role)).strip() or user.role
    role = "sub_admin" if role == "admin" else role
    if user.role == "super_admin":
        role = "super_admin"
    elif role == "super_admin":
        raise ValueError("不能创建或提升为主管理员账号。")
    if role not in {"super_admin", "sub_admin", "engineer"}:
        raise ValueError("不支持的账号角色。")
    username = str(payload.get("username", user_username(user))).strip() or user_username(user)
    employee_no = str(payload.get("employee_no", user_employee_no(user) or "")).strip() or user_employee_no(user)
    duplicate = User.query.filter(User.username_lookup == username_lookup_value(username), User.id != user.id).first()
    if duplicate:
        raise ValueError("用户名已存在。")
    duplicate_employee = User.query.filter(
        User.employee_no_lookup == sensitive_lookup_value(employee_no), User.id != user.id
    ).first()
    if duplicate_employee:
        raise ValueError("员工编号已存在。")
    sync_user_credentials(user, username, str(payload["password"])) if payload.get("password") else sync_user_credentials(user, username)
    full_name = str(payload.get("full_name", user_full_name(user))).strip() or user_full_name(user)
    phone = str(payload.get("phone", user_phone(user) or "")).strip() or user_phone(user)
    avatar_data = str(payload.get("avatar_data", user_avatar_data(user) or "")).strip() or user_avatar_data(user)
    sync_user_profile(user, full_name=full_name, employee_no=employee_no, phone=phone, avatar_data=avatar_data)
    user.role = role
    user.is_active = bool(payload.get("is_active", user.is_active))

    if role == "engineer":
        region = str(payload.get("region", "")).strip()
        address = str(payload.get("address", "")).strip()
        existing_profile = Engineer.query.get(user.engineer_id) if user.engineer_id else None
        region = region or (engineer_region(existing_profile) if existing_profile else "")
        address = address or (engineer_address(existing_profile) if existing_profile else "")
        if not region or not address:
            raise ValueError("工程师账号必须填写分管片区和住址，才能参与工单自动分配。")
        engineer = Engineer.query.filter_by(employee_no_lookup=sensitive_lookup_value(employee_no)).first()
        if engineer is not None:
            conflict = User.query.filter(User.engineer_id == engineer.id, User.id != user.id).first()
            if conflict:
                raise ValueError("该工程师已绑定其他账号。")
        engineer = _ensure_engineer_profile_for_user(
            employee_no=employee_no,
            full_name=user_full_name(user),
            phone=user_phone(user) or "",
            avatar_data=user_avatar_data(user) or "",
            region=region,
            address=address,
            existing_engineer_id=user.engineer_id,
        )
        user.engineer_id = engineer.id
    else:
        _delete_engineer_profile(user.engineer_id)
        user.engineer_id = None

    db.session.commit()
    return _serialize_user(user)


def delete_user(user_id: int) -> None:
    user = User.query.get_or_404(user_id)
    if user.role == "super_admin":
        raise ValueError("主管理员账号不可删除。")
    _delete_engineer_profile(user.engineer_id if user.role == "engineer" else None)
    WorkOrder.query.filter_by(created_by_user_id=user.id).update({"created_by_user_id": None})
    WorkOrder.query.filter_by(assigned_by_user_id=user.id).update({"assigned_by_user_id": None})
    WorkOrder.query.filter_by(accepted_by_user_id=user.id).update({"accepted_by_user_id": None})
    db.session.delete(user)
    db.session.commit()


def engineers_snapshot() -> list[dict[str, Any]]:
    refresh_engineer_statuses()
    linked_engineer_ids = {
        item.engineer_id
        for item in User.query.filter_by(role="engineer").all()
        if item.engineer_id is not None
    }
    engineers = (
        Engineer.query.filter(Engineer.id.in_(linked_engineer_ids)).order_by(Engineer.created_at.asc(), Engineer.id.asc()).all()
        if linked_engineer_ids
        else []
    )
    rows: list[dict[str, Any]] = []
    for engineer in engineers:
        active_orders = WorkOrder.query.filter(
            WorkOrder.engineer_id == engineer.id, WorkOrder.status.in_(["assigned", "in_progress"])
        ).count()
        rows.append(
            {
                "id": engineer.id,
                "employee_no": engineer_employee_no(engineer),
                "avatar_data": engineer_avatar_data(engineer),
                "name": engineer_name(engineer),
                "phone": engineer_phone(engineer),
                "address": engineer_address(engineer),
                "is_online": bool(engineer.is_online),
                "last_online_at": engineer.last_online_at.isoformat() if engineer.last_online_at else None,
                "region": engineer_region(engineer),
                "active_orders": active_orders,
            }
        )
    return sorted(rows, key=lambda item: (item["region"], item["active_orders"], item["employee_no"]))


def create_engineer(payload: dict[str, Any]) -> dict[str, Any]:
    employee_no = str(payload.get("employee_no", "")).strip()
    avatar_data = str(payload.get("avatar_data", "")).strip()
    name = str(payload.get("name", "")).strip()
    phone = str(payload.get("phone", "")).strip()
    region = str(payload.get("region", "")).strip()
    address = str(payload.get("address", "")).strip()
    status = str(payload.get("status", "available")).strip() or "available"
    if not employee_no or not avatar_data or not name or not phone or not region or not address:
        raise ValueError("头像、员工编号、姓名、电话、分管片区和住址不能为空。")
    if Engineer.query.filter_by(employee_no_lookup=sensitive_lookup_value(employee_no)).first():
        raise ValueError("员工编号已存在。")
    engineer = Engineer(
        employee_no=encrypted_placeholder("eng", sensitive_lookup_value(employee_no)),
        avatar_data="",
        name="已加密工程师",
        phone="[encrypted]",
        specialty="",
        address="[encrypted]",
        is_online=False,
        last_online_at=None,
        status=status,
        region=encrypted_placeholder("region", sensitive_lookup_value(region)),
    )
    sync_engineer_profile(
        engineer,
        employee_no=employee_no,
        full_name=name,
        phone=phone,
        avatar_data=avatar_data,
        region=region,
        address=address,
    )
    db.session.add(engineer)
    db.session.commit()
    return next(item for item in engineers_snapshot() if item["id"] == engineer.id)


def update_engineer(engineer_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    engineer = Engineer.query.get_or_404(engineer_id)
    employee_no = str(payload.get("employee_no", engineer_employee_no(engineer))).strip() or engineer_employee_no(engineer)
    duplicate = Engineer.query.filter(
        Engineer.employee_no_lookup == sensitive_lookup_value(employee_no), Engineer.id != engineer_id
    ).first()
    if duplicate:
        raise ValueError("员工编号已存在。")
    avatar_data = str(payload.get("avatar_data", engineer_avatar_data(engineer) or "")).strip() or engineer_avatar_data(engineer)
    name = str(payload.get("name", engineer_name(engineer))).strip() or engineer_name(engineer)
    phone = str(payload.get("phone", engineer_phone(engineer))).strip() or engineer_phone(engineer)
    engineer.status = str(payload.get("status", engineer.status)).strip() or engineer.status
    region = str(payload.get("region", engineer_region(engineer))).strip() or engineer_region(engineer)
    address = str(payload.get("address", engineer_address(engineer) or "")).strip() or engineer_address(engineer)
    if not avatar_data:
        raise ValueError("请上传工程师头像。")
    sync_engineer_profile(
        engineer,
        employee_no=employee_no,
        full_name=name,
        phone=phone,
        avatar_data=avatar_data,
        region=region,
        address=address,
    )
    db.session.commit()
    return next(item for item in engineers_snapshot() if item["id"] == engineer.id)


def dispatch_candidate_engineers(region: str) -> list[dict[str, Any]]:
    normalized_region = region.strip()
    candidates = engineers_snapshot()
    if normalized_region:
        candidates = [item for item in candidates if item["region"] == normalized_region]
    return sorted(
        candidates,
        key=lambda item: (
            0 if item["is_online"] else 1,
            item["active_orders"],
            item["employee_no"],
        ),
    )


def delete_engineer(engineer_id: int) -> None:
    engineer = Engineer.query.get_or_404(engineer_id)
    WorkOrder.query.filter_by(engineer_id=engineer_id).update({"engineer_id": None, "status": "pending", "current_stage": "pending"})
    db.session.delete(engineer)
    db.session.commit()


def work_orders_snapshot() -> list[dict[str, Any]]:
    orders = WorkOrder.query.order_by(WorkOrder.dispatch_rank.desc(), WorkOrder.updated_at.desc()).all()
    return [_serialize_work_order(order) for order in orders]


def create_work_order(payload: dict[str, Any], actor: User | None = None) -> dict[str, Any]:
    device_id = int(payload.get("device_id"))
    engineer_id = payload.get("engineer_id")
    anomaly_event_id = payload.get("anomaly_event_id")
    status = str(payload.get("status", "pending")).strip() or "pending"
    region = str(payload.get("region", "")).strip()
    if engineer_id not in (None, "", 0, "0") and status == "pending":
        status = "assigned"
    dispatch_rank = 100 if actor and actor.role == "super_admin" else 10 if actor and actor.role == "sub_admin" else 0
    priority = str(payload.get("priority", "medium")).strip() or "medium"
    if dispatch_rank >= 100:
        priority = "high"

    if db.session.get(Device, device_id) is None:
        raise ValueError("关联设备不存在。")
    if engineer_id in (None, "", 0, "0") and region:
        candidates = dispatch_candidate_engineers(region)
        if candidates:
            engineer_id = candidates[0]["id"]
            if status == "pending":
                status = "assigned"
    anomaly_event = None
    if anomaly_event_id not in (None, "", 0, "0"):
        anomaly_event = db.session.get(AnomalyEvent, int(anomaly_event_id))
        if anomaly_event is None:
            raise ValueError("关联告警不存在。")
    if engineer_id not in (None, "", 0, "0") and db.session.get(Engineer, int(engineer_id)) is None:
        raise ValueError("分配工程师不存在。")

    order = WorkOrder(
        title=str(payload.get("title", "")).strip(),
        description=str(payload.get("description", "")).strip(),
        region=region,
        priority=priority,
        status=status,
        current_stage=STATUS_STAGE_MAP.get(status, "pending"),
        device_id=device_id,
        anomaly_event_id=anomaly_event.id if anomaly_event else None,
        engineer_id=int(engineer_id) if engineer_id not in (None, "", 0, "0") else None,
        created_by_user_id=actor.id if actor else None,
        assigned_by_user_id=actor.id if actor and engineer_id not in (None, "", 0, "0") else None,
        dispatch_rank=dispatch_rank,
    )
    if not order.title or not order.description or not order.region:
        raise ValueError("工单标题、工单描述和分配片区不能为空。")

    db.session.add(order)
    db.session.flush()

    _append_work_order_record(order, "创建工单", f"工单已创建，当前状态为 {work_order_stage_label(order.current_stage)}。")
    if order.engineer_id is not None:
        engineer = Engineer.query.get(order.engineer_id)
        assigned_engineer_name = engineer_name(engineer) if engineer else "已分派"
        _append_work_order_record(order, "派单", f"已分派给 {assigned_engineer_name}。", stage="assigned")
    if anomaly_event is not None:
        anomaly_event.status = "assigned" if order.engineer_id is not None else "open"

    db.session.commit()
    return _serialize_work_order(order)


def update_work_order(order_id: int, payload: dict[str, Any], actor: User | None = None) -> dict[str, Any]:
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

    region = str(payload.get("region", order.region or "")).strip() or order.region
    if region != order.region:
        changes.append(f"分配片区调整为 {region}")
    order.region = region

    priority = str(payload.get("priority", order.priority)).strip() or order.priority
    if order.dispatch_rank >= 100:
        priority = "high"
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
        if db.session.get(Device, device_id) is None:
            raise ValueError("关联设备不存在。")
        if device_id != order.device_id:
            changes.append("关联设备已调整")
        order.device_id = device_id

    anomaly_event_payload = payload.get("anomaly_event_id")
    if anomaly_event_payload not in (None, "", 0, "0"):
        anomaly_event = db.session.get(AnomalyEvent, int(anomaly_event_payload))
        if anomaly_event is None:
            raise ValueError("关联告警不存在。")
        order.anomaly_event_id = anomaly_event.id

    engineer_payload = payload.get("engineer_id")
    if engineer_payload in (None, "", 0, "0"):
        if order.engineer_id is not None:
            changes.append("已取消工程师分配")
        order.engineer_id = None
    elif engineer_payload is not None:
        engineer_id = int(engineer_payload)
        if db.session.get(Engineer, engineer_id) is None:
            raise ValueError("分配工程师不存在。")
        if engineer_id != order.engineer_id:
            changes.append("已重新分配工程师")
        order.engineer_id = engineer_id

    db.session.flush()
    if order.anomaly_event is not None:
        if order.status == "completed":
            order.anomaly_event.status = "completed"
            order.anomaly_event.handled_at = order.anomaly_event.handled_at or datetime.now()
        elif order.engineer_id is not None:
            order.anomaly_event.status = "assigned"
        else:
            order.anomaly_event.status = "open"
    note = "；".join(changes) if changes else "工单信息已同步。"
    _append_work_order_record(order, "更新工单", note, stage=order.current_stage)
    db.session.commit()
    return _serialize_work_order(order)


def engineer_accept_work_order(order_id: int, engineer_user: User) -> dict[str, Any]:
    order = WorkOrder.query.get_or_404(order_id)
    if engineer_user.role != "engineer" or engineer_user.engineer_id is None:
        raise ValueError("当前账号不是工程师账号。")
    if order.engineer_id != engineer_user.engineer_id:
        raise ValueError("该工单未派发给当前工程师。")

    order.status = "in_progress"
    order.current_stage = "in_progress"
    order.accepted_by_user_id = engineer_user.id
    order.accepted_at = datetime.now()
    _append_work_order_record(
        order,
        "工程师接单",
        f"{user_full_name(engineer_user)} 已确认接单。",
        operator_name=user_full_name(engineer_user),
        stage="in_progress",
    )
    db.session.commit()
    return _serialize_work_order(order)


def engineer_complete_work_order(order_id: int, engineer_user: User, note: str) -> dict[str, Any]:
    order = WorkOrder.query.get_or_404(order_id)
    if engineer_user.role != "engineer" or engineer_user.engineer_id is None:
        raise ValueError("当前账号不是工程师账号。")
    if order.engineer_id != engineer_user.engineer_id:
        raise ValueError("该工单未派发给当前工程师。")
    note = note.strip()
    if not note:
        raise ValueError("请填写处理情况。")

    order.status = "completed"
    order.current_stage = "completed"
    order.accepted_by_user_id = engineer_user.id
    order.accepted_at = order.accepted_at or datetime.now()
    order.completion_note = note
    if order.anomaly_event is not None:
        order.anomaly_event.status = "completed"
        order.anomaly_event.confirmed_label = "false_positive" if "误报" in note or "正常" in note else "confirmed_anomaly"
        order.anomaly_event.handled_at = datetime.now()
    _append_work_order_record(
        order,
        "工程师回单",
        note,
        operator_name=user_full_name(engineer_user),
        stage="completed",
    )
    db.session.commit()
    return _serialize_work_order(order)


def update_engineer_presence(engineer_user: User, online: bool = True) -> dict[str, Any]:
    if engineer_user.role != "engineer":
        raise ValueError("当前账号不是工程师账号。")
    engineer = Engineer.query.get(engineer_user.engineer_id) if engineer_user.engineer_id else None
    if engineer is None and user_employee_no(engineer_user):
        engineer = Engineer.query.filter_by(employee_no_lookup=sensitive_lookup_value(user_employee_no(engineer_user))).first()
    if engineer is None:
        raise ValueError("未找到对应的工程师档案。")
    engineer.is_online = bool(online)
    engineer.last_online_at = datetime.now() if online else None
    db.session.commit()
    return next(item for item in engineers_snapshot() if item["id"] == engineer.id)


def delete_work_order(order_id: int) -> None:
    order = WorkOrder.query.get_or_404(order_id)
    if order.anomaly_event is not None and order.anomaly_event.status != "completed":
        order.anomaly_event.status = "open"
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
    detector.ensure_ready()
    active_model = active_model_metadata() or {}
    active_eval = active_model.get("evaluation", {})
    return {
        "database_uri": get_database_uri(),
        "database_file": str(DATABASE_FILE),
        "device_register_api": "/api/device/register",
        "device_upload_api": "/api/device/upload",
        "carrier_webhook_api": "/api/carrier/webhook/<provider>",
        "mqtt_gateway_api": "/api/mqtt",
        "drift_monitor_api": "/api/drift",
        "websocket_url": "/ws",
        "user_count": User.query.count(),
        "training_raw_data_count": TrainingRawDataRecord.query.count(),
        "training_clean_data_count": TrainingCleanDataRecord.query.count(),
        "training_database_health": training_database_health(),
        "device_data_count": PhysicalDataRecord.query.count(),
        "device_data_retention_days": PHYSICAL_DATA_RETENTION_DAYS,
        "physical_data_count": PhysicalDataRecord.query.count(),
        "physical_data_retention_days": PHYSICAL_DATA_RETENTION_DAYS,
        "active_model_id": active_model.get("model_id"),
        "active_model_created_at": active_model.get("created_at"),
        "active_model_f1": active_eval.get("f1"),
        "active_model_accuracy": active_eval.get("accuracy"),
        "active_model_threshold": active_model.get("threshold"),
        "loaded_model_version": detector.loaded_model_version,
        "model_versions": [
            {
                "model_id": item.model_id,
                "created_at": item.created_at.isoformat() if item.created_at else None,
                "threshold": item.threshold,
                "accuracy": item.accuracy,
                "precision": item.precision_score,
                "recall": item.recall_score,
                "f1": item.f1_score,
                "final_loss": item.final_loss,
                "train_windows": item.train_windows,
                "valid_windows": item.valid_windows,
                "is_active": item.is_active,
                "activation_reason": item.activation_reason,
            }
            for item in ModelMetadata.query.order_by(ModelMetadata.created_at.desc()).limit(10).all()
        ],
    }


def _auto_create_work_order_for_event(event: AnomalyEvent) -> WorkOrder | None:
    existing = WorkOrder.query.filter(
        WorkOrder.device_id == event.device_id,
        WorkOrder.status.in_(["pending", "assigned", "in_progress"]),
    ).order_by(WorkOrder.updated_at.desc()).first()
    if existing is not None:
        if existing.anomaly_event_id is None:
            existing.anomaly_event_id = event.id
        event.status = "assigned" if existing.engineer_id is not None else "open"
        return existing

    device = event.device
    candidates = dispatch_candidate_engineers(device.area)
    engineer_id = candidates[0]["id"] if candidates else None
    status = "assigned" if engineer_id else "pending"
    priority = "high" if event.severity == "high" else "medium"
    order = WorkOrder(
        title=f"{event.anomaly_type}自动工单",
        description=(
            f"{device.meter_id} {event.description} "
            f"异常得分 {event.score:.4f}，阈值 {event.threshold:.4f}。"
        ),
        region=device.area,
        priority=priority,
        status=status,
        current_stage=STATUS_STAGE_MAP.get(status, "pending"),
        device_id=device.id,
        anomaly_event_id=event.id,
        engineer_id=engineer_id,
        dispatch_rank=80 if event.severity == "high" else 30,
    )
    db.session.add(order)
    db.session.flush()
    _append_work_order_record(order, "自动创建工单", "系统根据深度学习异常检测告警自动生成工单。")
    if engineer_id is not None:
        engineer = Engineer.query.get(engineer_id)
        assigned_engineer_name = engineer_name(engineer) if engineer else "已分派"
        _append_work_order_record(order, "自动派单", f"按片区和负载自动分派给 {assigned_engineer_name}。", stage="assigned")
        event.status = "assigned"
    else:
        event.status = "open"
    return order


def _run_detection_for_reading_once(reading_id: int, emit_event: bool = True) -> None:
    reading = db.session.get(MeterReading, reading_id)
    if reading is None:
        return

    recent_readings = (
        MeterReading.query.filter(
            MeterReading.device_id == reading.device_id,
            MeterReading.timestamp <= reading.timestamp,
        )
        .order_by(MeterReading.timestamp.asc())
        .all()
    )
    result = detector.score_recent_readings(recent_readings)
    reading.anomaly_score = result.anomaly_score
    reading.threshold = result.threshold
    reading.predicted_label = result.predicted_label
    reading.model_version = result.model_version

    if result.predicted_label == 1:
        existing_event = AnomalyEvent.query.filter_by(reading_id=reading.id).first()
        event = existing_event or AnomalyEvent(
            device_id=reading.device_id,
            reading_id=reading.id,
            anomaly_type=result.anomaly_type,
            description=result.description,
            score=result.anomaly_score,
            threshold=result.threshold,
            severity=result.severity,
            status="open",
            model_version=result.model_version,
        )
        event.anomaly_type = result.anomaly_type
        event.description = result.description
        event.score = result.anomaly_score
        event.threshold = result.threshold
        event.severity = result.severity
        event.model_version = result.model_version
        if existing_event is None:
            db.session.add(event)
            db.session.flush()
        _auto_create_work_order_for_event(event)

    db.session.commit()
    if emit_event:
        emit_realtime_updates()


def _run_detection_for_reading(reading_id: int, emit_event: bool = True, max_attempts: int = 4) -> None:
    for attempt in range(1, max_attempts + 1):
        try:
            _run_detection_for_reading_once(reading_id, emit_event=emit_event)
            return
        except OperationalError as exc:
            db.session.rollback()
            if not _is_transient_database_error(exc) or attempt >= max_attempts:
                raise
            time.sleep(0.08 * attempt)


def _run_detection_job(app: Any, reading_id: int, emit_event: bool) -> None:
    with app.app_context():
        try:
            _run_detection_for_reading(reading_id, emit_event=emit_event)
        except Exception:
            db.session.rollback()
            traceback.print_exc()


def _submit_detection_task(reading_id: int, emit_event: bool) -> None:
    if not has_app_context():
        _run_detection_for_reading(reading_id, emit_event=emit_event)
        return
    app = current_app._get_current_object()
    DETECTION_EXECUTOR.submit(_run_detection_job, app, reading_id, emit_event)


def ingest_reading(
    device: Device,
    payload: dict[str, Any],
    emit_event: bool = True,
    *,
    async_detection: bool | None = None,
) -> MeterReading:
    if not device.is_enabled:
        raise ValueError("设备已停用，暂不接收上报数据。")
    reading = MeterReading(
        device_id=device.id,
        source="device",
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
    db.session.commit()

    use_async = ASYNC_DETECTION_ENABLED if async_detection is None else async_detection
    if use_async:
        _submit_detection_task(reading.id, emit_event)
    else:
        _run_detection_for_reading(reading.id, emit_event=emit_event)
    return reading


def ensure_database() -> None:
    ensure_directories()
    if get_database_uri().startswith("sqlite:///"):
        DATABASE_FILE.touch(exist_ok=True)
