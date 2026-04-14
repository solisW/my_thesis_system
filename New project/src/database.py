from __future__ import annotations

from datetime import datetime

from flask_sqlalchemy import SQLAlchemy


db = SQLAlchemy()


def now() -> datetime:
    return datetime.now()


class User(db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    full_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=now, nullable=False)


class Device(db.Model):
    __tablename__ = "devices"

    id = db.Column(db.Integer, primary_key=True)
    meter_id = db.Column(db.String(50), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    location = db.Column(db.String(120), nullable=False)
    api_key = db.Column(db.String(80), unique=True, nullable=False)
    status = db.Column(db.String(20), default="offline", nullable=False)
    last_seen_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    readings = db.relationship("MeterReading", backref="device", lazy=True)
    anomalies = db.relationship("AnomalyEvent", backref="device", lazy=True)


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
    created_at = db.Column(db.DateTime, default=now, nullable=False)

    reading = db.relationship("MeterReading")
