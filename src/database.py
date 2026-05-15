from __future__ import annotations

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import inspect, text


db = SQLAlchemy()


def now() -> datetime:
    return datetime.now()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    username_encrypted = db.Column(db.Text, nullable=True)
    username_lookup = db.Column(db.String(64), unique=True, nullable=True)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    full_name_encrypted = db.Column(db.Text, nullable=True)
    employee_no = db.Column(db.String(40), unique=True, nullable=True)
    employee_no_encrypted = db.Column(db.Text, nullable=True)
    employee_no_lookup = db.Column(db.String(64), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    phone_encrypted = db.Column(db.Text, nullable=True)
    avatar_data = db.Column(db.Text, nullable=True)
    avatar_data_encrypted = db.Column(db.Text, nullable=True)
    role = db.Column(db.String(20), default="admin", nullable=False)
    engineer_id = db.Column(db.Integer, db.ForeignKey("engineers.id"), nullable=True)
    is_active = db.Column(db.Boolean, default=True, nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    engineer_profile = db.relationship("Engineer", back_populates="user_account", uselist=False)


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    meter_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(120), nullable=False)
    area = db.Column(db.String(80), nullable=False, default="A区")
    latitude = db.Column(db.Float, nullable=False, default=31.2304)
    longitude = db.Column(db.Float, nullable=False, default=121.4737)
    device_mode = db.Column(db.String(20), nullable=False, default="device")
    protocol = db.Column(db.String(20), nullable=False, default="HTTP")
    ip_address = db.Column(db.String(100), nullable=True)
    port = db.Column(db.Integer, nullable=True)
    firmware_version = db.Column(db.String(50), nullable=False, default="v1.0.0")
    api_key = db.Column(db.String(80), unique=True, nullable=False)
    is_enabled = db.Column(db.Boolean, default=True, nullable=False)
    status = db.Column(db.String(20), default="offline", nullable=False)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    readings = db.relationship("MeterReading", backref="device", lazy=True)
    anomalies = db.relationship("AnomalyEvent", backref="device", lazy=True)
    work_orders = db.relationship("WorkOrder", backref="device", lazy=True)


class MeterReading(db.Model):
    __tablename__ = "meter_readings"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False)
    source = db.Column(db.String(20), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False)
    instant_flow = db.Column(db.Float, nullable=False)
    cumulative_usage = db.Column(db.Float, nullable=False)
    battery_voltage = db.Column(db.Float, nullable=False)
    signal_strength = db.Column(db.Float, nullable=False)
    valve_state = db.Column(db.Integer, nullable=False)
    temperature = db.Column(db.Float, nullable=False)
    pressure = db.Column(db.Float, nullable=False)
    anomaly_score = db.Column(db.Float, nullable=True)
    threshold = db.Column(db.Float, nullable=True)
    predicted_label = db.Column(db.Integer, default=0, nullable=False)
    model_version = db.Column(db.String(80), nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class PhysicalDataRecord(db.Model):
    __tablename__ = "physical_data_records"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False)
    meter_id = db.Column(db.String(50), nullable=False, index=True)
    timestamp = db.Column(db.DateTime, nullable=False, index=True)
    instant_flow = db.Column(db.Float, nullable=False)
    cumulative_usage = db.Column(db.Float, nullable=False)
    battery_voltage = db.Column(db.Float, nullable=False)
    signal_strength = db.Column(db.Float, nullable=False)
    valve_state = db.Column(db.Integer, nullable=False)
    temperature = db.Column(db.Float, nullable=False)
    pressure = db.Column(db.Float, nullable=False)
    received_at = db.Column(db.DateTime, default=now, nullable=False, index=True)

    device = db.relationship("Device")


class AnomalyEvent(db.Model):
    __tablename__ = "anomaly_events"

    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False)
    reading_id = db.Column(db.Integer, db.ForeignKey("meter_readings.id"), nullable=False)
    anomaly_type = db.Column(db.String(60), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    score = db.Column(db.Float, nullable=False)
    threshold = db.Column(db.Float, nullable=False)
    severity = db.Column(db.String(20), nullable=False, default="medium")
    status = db.Column(db.String(20), nullable=False, default="open")
    model_version = db.Column(db.String(80), nullable=True)
    confirmed_label = db.Column(db.String(20), nullable=True)
    handled_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    reading = db.relationship("MeterReading")
    work_order = db.relationship("WorkOrder", back_populates="anomaly_event", uselist=False)


class ModelMetadata(db.Model):
    __tablename__ = "model_metadata"

    id = db.Column(db.Integer, primary_key=True)
    model_id = db.Column(db.String(80), unique=True, nullable=False)
    model_path = db.Column(db.String(500), nullable=False)
    scaler_path = db.Column(db.String(500), nullable=False)
    meta_path = db.Column(db.String(500), nullable=False)
    feature_columns = db.Column(db.Text, nullable=False)
    window_size = db.Column(db.Integer, nullable=False)
    hidden_size = db.Column(db.Integer, nullable=False)
    num_layers = db.Column(db.Integer, nullable=False)
    threshold = db.Column(db.Float, nullable=False)
    threshold_strategy = db.Column(db.String(80), nullable=True)
    accuracy = db.Column(db.Float, nullable=True)
    precision_score = db.Column(db.Float, nullable=True)
    recall_score = db.Column(db.Float, nullable=True)
    f1_score = db.Column(db.Float, nullable=True)
    final_loss = db.Column(db.Float, nullable=True)
    train_windows = db.Column(db.Integer, nullable=True)
    valid_windows = db.Column(db.Integer, nullable=True)
    raw_count = db.Column(db.Integer, nullable=True)
    clean_count = db.Column(db.Integer, nullable=True)
    is_active = db.Column(db.Boolean, default=False, nullable=False)
    activation_reason = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    activated_at = db.Column(db.DateTime, nullable=True)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)


class Engineer(db.Model):
    __tablename__ = "engineers"

    id = db.Column(db.Integer, primary_key=True)
    employee_no = db.Column(db.String(40), nullable=False, unique=True)
    employee_no_encrypted = db.Column(db.Text, nullable=True)
    employee_no_lookup = db.Column(db.String(64), nullable=True)
    avatar_data = db.Column(db.Text, nullable=True)
    avatar_data_encrypted = db.Column(db.Text, nullable=True)
    name = db.Column(db.String(80), nullable=False)
    name_encrypted = db.Column(db.Text, nullable=True)
    phone = db.Column(db.String(30), nullable=False)
    phone_encrypted = db.Column(db.Text, nullable=True)
    specialty = db.Column(db.String(100), nullable=True)
    address = db.Column(db.String(200), nullable=True)
    address_encrypted = db.Column(db.Text, nullable=True)
    is_online = db.Column(db.Boolean, default=False, nullable=False)
    last_online_at = db.Column(db.DateTime, nullable=True)
    status = db.Column(db.String(20), nullable=False, default="available")
    region = db.Column(db.String(80), nullable=False)
    region_encrypted = db.Column(db.Text, nullable=True)
    region_lookup = db.Column(db.String(64), nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    work_orders = db.relationship("WorkOrder", backref="engineer", lazy=True)
    user_account = db.relationship("User", back_populates="engineer_profile", uselist=False)


class WorkOrder(db.Model):
    __tablename__ = "work_orders"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    region = db.Column(db.String(80), nullable=True)
    priority = db.Column(db.String(20), nullable=False, default="medium")
    status = db.Column(db.String(20), nullable=False, default="pending")
    current_stage = db.Column(db.String(30), nullable=False, default="pending")
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False)
    anomaly_event_id = db.Column(db.Integer, db.ForeignKey("anomaly_events.id"), nullable=True)
    engineer_id = db.Column(db.Integer, db.ForeignKey("engineers.id"), nullable=True)
    created_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    assigned_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    accepted_by_user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    accepted_at = db.Column(db.DateTime, nullable=True)
    completion_note = db.Column(db.Text, nullable=True)
    dispatch_rank = db.Column(db.Integer, nullable=False, default=0)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

    records = db.relationship("WorkOrderRecord", backref="work_order", lazy=True, cascade="all, delete-orphan")
    created_by = db.relationship("User", foreign_keys=[created_by_user_id])
    assigned_by = db.relationship("User", foreign_keys=[assigned_by_user_id])
    accepted_by = db.relationship("User", foreign_keys=[accepted_by_user_id])
    anomaly_event = db.relationship("AnomalyEvent", back_populates="work_order")


class WorkOrderRecord(db.Model):
    __tablename__ = "work_order_records"

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"), nullable=False)
    stage = db.Column(db.String(30), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    note = db.Column(db.String(255), nullable=False)
    operator_name = db.Column(db.String(80), nullable=False, default="系统")
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class TrainingRawDataRecord(db.Model):
    __tablename__ = "training_raw_data_records"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, index=True)
    meter_id = db.Column(db.String(50), nullable=False, index=True)
    instant_flow = db.Column(db.Float, nullable=False)
    cumulative_usage = db.Column(db.Float, nullable=False)
    battery_voltage = db.Column(db.Float, nullable=False)
    signal_strength = db.Column(db.Float, nullable=False)
    valve_state = db.Column(db.Integer, nullable=False)
    temperature = db.Column(db.Float, nullable=False)
    pressure = db.Column(db.Float, nullable=False)
    is_injected_anomaly = db.Column(db.Boolean, default=False, nullable=False)
    imported_at = db.Column(db.DateTime, default=now, nullable=False)


class TrainingCleanDataRecord(db.Model):
    __tablename__ = "training_clean_data_records"

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, nullable=False, index=True)
    meter_id = db.Column(db.String(50), nullable=False, index=True)
    instant_flow = db.Column(db.Float, nullable=False)
    cumulative_usage = db.Column(db.Float, nullable=False)
    battery_voltage = db.Column(db.Float, nullable=False)
    signal_strength = db.Column(db.Float, nullable=False)
    valve_state = db.Column(db.Integer, nullable=False)
    temperature = db.Column(db.Float, nullable=False)
    pressure = db.Column(db.Float, nullable=False)
    is_injected_anomaly = db.Column(db.Boolean, default=False, nullable=False)
    cleaned_at = db.Column(db.DateTime, default=now, nullable=False)


def work_order_stage_label(status: str | None) -> str:
    return {
        "pending": "待处理",
        "assigned": "已派单",
        "in_progress": "处理中",
        "completed": "已完成",
    }.get(status or "", status or "待处理")


def _ensure_index(connection, inspector, table_name: str, index_name: str, columns: list[str]) -> None:
    existing_indexes = {index["name"] for index in inspector.get_indexes(table_name)}
    if index_name in existing_indexes:
        return
    column_sql = ", ".join(columns)
    connection.execute(text(f"CREATE INDEX {index_name} ON {table_name} ({column_sql})"))


def run_sqlite_migrations() -> None:
    engine = db.engine

    schema_updates = {
        "users": {
            "role": "VARCHAR(20) DEFAULT 'admin' NOT NULL",
            "engineer_id": "INTEGER",
            "is_active": "BOOLEAN DEFAULT 1 NOT NULL",
            "username_encrypted": "TEXT",
            "username_lookup": "VARCHAR(64)",
            "phone": "VARCHAR(30)",
            "phone_encrypted": "TEXT",
            "avatar_data": "TEXT",
            "avatar_data_encrypted": "TEXT",
            "employee_no": "VARCHAR(40)",
            "employee_no_encrypted": "TEXT",
            "employee_no_lookup": "VARCHAR(64)",
            "full_name_encrypted": "TEXT",
        },
        "engineers": {
            "employee_no": "VARCHAR(40)",
            "employee_no_encrypted": "TEXT",
            "employee_no_lookup": "VARCHAR(64)",
            "avatar_data": "TEXT",
            "avatar_data_encrypted": "TEXT",
            "name_encrypted": "TEXT",
            "phone_encrypted": "TEXT",
            "address": "VARCHAR(200)",
            "address_encrypted": "TEXT",
            "is_online": "BOOLEAN DEFAULT 0 NOT NULL",
            "last_online_at": "DATETIME",
            "region_encrypted": "TEXT",
            "region_lookup": "VARCHAR(64)",
        },
        "devices": {
            "area": "VARCHAR(80) DEFAULT 'A区' NOT NULL",
            "latitude": "FLOAT DEFAULT 31.2304 NOT NULL",
            "longitude": "FLOAT DEFAULT 121.4737 NOT NULL",
            "device_mode": "VARCHAR(20) DEFAULT 'device' NOT NULL",
            "protocol": "VARCHAR(20) DEFAULT 'HTTP' NOT NULL",
            "ip_address": "VARCHAR(100)",
            "port": "INTEGER",
            "firmware_version": "VARCHAR(50) DEFAULT 'v1.0.0' NOT NULL",
            "is_enabled": "BOOLEAN DEFAULT 1 NOT NULL",
        },
        "anomaly_events": {
            "severity": "VARCHAR(20) DEFAULT 'medium' NOT NULL",
            "status": "VARCHAR(20) DEFAULT 'open' NOT NULL",
            "model_version": "VARCHAR(80)",
            "confirmed_label": "VARCHAR(20)",
            "handled_at": "DATETIME",
        },
        "meter_readings": {
            "model_version": "VARCHAR(80)",
        },
        "work_orders": {
            "current_stage": "VARCHAR(30) DEFAULT 'pending' NOT NULL",
            "anomaly_event_id": "INTEGER",
            "created_by_user_id": "INTEGER",
            "assigned_by_user_id": "INTEGER",
            "accepted_by_user_id": "INTEGER",
            "accepted_at": "DATETIME",
            "completion_note": "TEXT",
            "dispatch_rank": "INTEGER DEFAULT 0 NOT NULL",
            "region": "VARCHAR(80)",
        },
        "model_metadata": {
            "threshold_strategy": "VARCHAR(80)",
        },
    }

    required_indexes = {
        "physical_data_records": {
            "idx_physical_data_records_meter_id": ["meter_id"],
            "idx_physical_data_records_received_at": ["received_at"],
        },
        "training_raw_data_records": {
            "idx_training_raw_meter_time": ["meter_id", "timestamp"],
        },
        "training_clean_data_records": {
            "idx_training_clean_meter_time": ["meter_id", "timestamp"],
        },
        "meter_readings": {
            "idx_meter_readings_device_time": ["device_id", "timestamp"],
        },
        "anomaly_events": {
            "idx_anomaly_events_status": ["status"],
            "idx_anomaly_events_model_version": ["model_version"],
        },
        "model_metadata": {
            "idx_model_metadata_active": ["is_active"],
        },
        "users": {
            "idx_users_employee_no_lookup": ["employee_no_lookup"],
        },
        "engineers": {
            "idx_engineers_employee_no_lookup": ["employee_no_lookup"],
            "idx_engineers_region_lookup": ["region_lookup"],
        },
    }

    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in schema_updates.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in columns.items():
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))

        for table_name, indexes in required_indexes.items():
            if not inspector.has_table(table_name):
                continue
            for index_name, columns in indexes.items():
                _ensure_index(connection, inspector, table_name, index_name, columns)
