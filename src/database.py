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
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    role = db.Column(db.String(20), default="admin", nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    meter_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(120), nullable=False)
    area = db.Column(db.String(80), nullable=False, default="A区")
    latitude = db.Column(db.Float, nullable=False, default=31.2304)
    longitude = db.Column(db.Float, nullable=False, default=121.4737)
    device_mode = db.Column(db.String(20), nullable=False, default="simulated")
    protocol = db.Column(db.String(20), nullable=False, default="HTTP")
    ip_address = db.Column(db.String(100), nullable=True)
    port = db.Column(db.Integer, nullable=True)
    firmware_version = db.Column(db.String(50), nullable=False, default="v1.0.0")
    api_key = db.Column(db.String(80), unique=True, nullable=False)
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
    created_at = db.Column(db.DateTime, default=now, nullable=False)


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
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    reading = db.relationship("MeterReading")


class Engineer(db.Model):
    __tablename__ = "engineers"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False)
    phone = db.Column(db.String(30), nullable=False)
    specialty = db.Column(db.String(100), nullable=False)
    status = db.Column(db.String(20), nullable=False, default="available")
    region = db.Column(db.String(80), nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    work_orders = db.relationship("WorkOrder", backref="engineer", lazy=True)


class WorkOrder(db.Model):
    __tablename__ = "work_orders"

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(120), nullable=False)
    description = db.Column(db.String(255), nullable=False)
    priority = db.Column(db.String(20), nullable=False, default="medium")
    status = db.Column(db.String(20), nullable=False, default="pending")
    current_stage = db.Column(db.String(30), nullable=False, default="pending")
    device_id = db.Column(db.Integer, db.ForeignKey("devices.id"), nullable=False)
    engineer_id = db.Column(db.Integer, db.ForeignKey("engineers.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)
    updated_at = db.Column(db.DateTime, default=now, onupdate=now, nullable=False)

    records = db.relationship("WorkOrderRecord", backref="work_order", lazy=True, cascade="all, delete-orphan")


class WorkOrderRecord(db.Model):
    __tablename__ = "work_order_records"

    id = db.Column(db.Integer, primary_key=True)
    work_order_id = db.Column(db.Integer, db.ForeignKey("work_orders.id"), nullable=False)
    stage = db.Column(db.String(30), nullable=False)
    action = db.Column(db.String(80), nullable=False)
    note = db.Column(db.String(255), nullable=False)
    operator_name = db.Column(db.String(80), nullable=False, default="系统")
    created_at = db.Column(db.DateTime, default=now, nullable=False)


def work_order_stage_label(status: str | None) -> str:
    return {
        "pending": "待受理",
        "assigned": "已派单",
        "in_progress": "处理中",
        "completed": "已完成",
    }.get(status or "", status or "待受理")


def run_sqlite_migrations() -> None:
    engine = db.engine
    if engine.url.get_backend_name() != "sqlite":
        return

    schema_updates = {
        "users": {
            "role": "VARCHAR(20) DEFAULT 'admin' NOT NULL",
        },
        "devices": {
            "area": "VARCHAR(80) DEFAULT 'A区' NOT NULL",
            "latitude": "FLOAT DEFAULT 31.2304 NOT NULL",
            "longitude": "FLOAT DEFAULT 121.4737 NOT NULL",
            "device_mode": "VARCHAR(20) DEFAULT 'simulated' NOT NULL",
            "protocol": "VARCHAR(20) DEFAULT 'HTTP' NOT NULL",
            "ip_address": "VARCHAR(100)",
            "port": "INTEGER",
            "firmware_version": "VARCHAR(50) DEFAULT 'v1.0.0' NOT NULL",
        },
        "anomaly_events": {
            "severity": "VARCHAR(20) DEFAULT 'medium' NOT NULL",
        },
        "work_orders": {
            "current_stage": "VARCHAR(30) DEFAULT 'pending' NOT NULL",
        },
    }

    inspector = inspect(engine)
    with engine.begin() as connection:
        for table_name, columns in schema_updates.items():
            if not inspector.has_table(table_name):
                continue
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, ddl in columns.items():
                if column_name in existing:
                    continue
                connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {ddl}"))

        if not inspector.has_table("work_order_records"):
            connection.execute(
                text(
                    """
                    CREATE TABLE work_order_records (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        work_order_id INTEGER NOT NULL,
                        stage VARCHAR(30) NOT NULL,
                        action VARCHAR(80) NOT NULL,
                        note VARCHAR(255) NOT NULL,
                        operator_name VARCHAR(80) NOT NULL DEFAULT '系统',
                        created_at DATETIME NOT NULL,
                        FOREIGN KEY(work_order_id) REFERENCES work_orders (id)
                    )
                    """
                )
            )
