from __future__ import annotations

import json
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, render_template, request, session, url_for

from .config import ensure_directories, get_database_uri
from .database import Device, User, db
from .realtime import hub, sock
from .security import cipher
from .services import (
    alert_history,
    create_device,
    dashboard_snapshot,
    delete_device,
    device_history,
    devices_snapshot,
    ensure_database,
    ingest_reading,
    seed_defaults,
    settings_snapshot,
    update_device,
)
from .simulator import MeterSimulator


PROJECT_ROOT = Path(__file__).resolve().parent.parent
simulator: MeterSimulator | None = None


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder=str(PROJECT_ROOT / "templates"),
        static_folder=str(PROJECT_ROOT / "static"),
    )
    app.config["SECRET_KEY"] = "gas-monitor-secret-key"
    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    ensure_directories()
    ensure_database()
    db.init_app(app)
    sock.init_app(app)

    with app.app_context():
        db.create_all()
        seed_defaults()

    register_routes(app)
    start_simulator(app)
    return app


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def nav_context(active_page: str) -> dict[str, str]:
    return {
        "user_name": session.get("username", "系统管理员"),
        "active_page": active_page,
        "ws_url": "/ws",
    }


def broadcast_full_state() -> None:
    hub.broadcast("dashboard", dashboard_snapshot())
    hub.broadcast("devices", devices_snapshot())
    hub.broadcast("alerts", alert_history(limit=30))
    hub.broadcast("settings", settings_snapshot())


def register_routes(app: Flask) -> None:
    @app.route("/")
    def home():
        if "user_id" in session:
            return redirect(url_for("dashboard"))
        return redirect(url_for("login"))

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = User.query.filter_by(username=username).first()
            if user:
                ok, migrated = cipher.verify(user.password_hash, password)
                if ok:
                    if migrated is not None:
                        user.password_hash = migrated
                        db.session.commit()
                    session["user_id"] = user.id
                    session["username"] = user.full_name
                    return redirect(url_for("dashboard"))
            flash("用户名或密码错误。", "error")
        return render_template("login.html")

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            full_name = request.form.get("full_name", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not username or not full_name or not password:
                flash("请完整填写注册信息。", "error")
            elif password != confirm_password:
                flash("两次输入的密码不一致。", "error")
            elif User.query.filter_by(username=username).first():
                flash("该用户名已存在。", "error")
            else:
                user = User(
                    username=username,
                    full_name=full_name,
                    password_hash=cipher.encrypt(password),
                )
                db.session.add(user)
                db.session.commit()
                flash("注册成功，请登录。", "success")
                return redirect(url_for("login"))
        return render_template("register.html")

    @app.route("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return render_template("dashboard.html", **nav_context("dashboard"))

    @app.route("/devices")
    @login_required
    def devices_page():
        return render_template("devices.html", **nav_context("devices"))

    @app.route("/alerts")
    @login_required
    def alerts_page():
        return render_template("alerts.html", **nav_context("alerts"))

    @app.route("/history")
    @login_required
    def history_page():
        meter_ids = [item.meter_id for item in Device.query.order_by(Device.meter_id.asc()).all()]
        return render_template("history.html", meter_ids=meter_ids, **nav_context("history"))

    @app.route("/settings")
    @login_required
    def settings_page():
        return render_template("settings.html", **nav_context("settings"))

    @app.route("/api/dashboard")
    @login_required
    def api_dashboard():
        return jsonify(dashboard_snapshot())

    @app.route("/api/devices", methods=["GET", "POST"])
    @login_required
    def api_devices():
        if request.method == "GET":
            return jsonify(devices_snapshot())

        payload = request.get_json(silent=True) or {}
        try:
            device = create_device(payload)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        broadcast_full_state()
        return jsonify({"ok": True, "device": device}), 201

    @app.route("/api/devices/<int:device_id>", methods=["PUT", "DELETE"])
    @login_required
    def api_device_detail(device_id: int):
        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            try:
                device = update_device(device_id, payload)
            except ValueError as exc:
                return jsonify({"ok": False, "message": str(exc)}), 400
            broadcast_full_state()
            return jsonify({"ok": True, "device": device})

        delete_device(device_id)
        broadcast_full_state()
        return jsonify({"ok": True})

    @app.route("/api/alerts")
    @login_required
    def api_alerts():
        limit = int(request.args.get("limit", 30))
        return jsonify(alert_history(limit=limit))

    @app.route("/api/history")
    @login_required
    def api_history():
        meter_id = request.args.get("meter_id", "").strip() or None
        limit = int(request.args.get("limit", 120))
        return jsonify(device_history(meter_id=meter_id, limit=limit))

    @app.route("/api/settings")
    @login_required
    def api_settings():
        return jsonify(settings_snapshot())

    @app.route("/api/simulator", methods=["GET", "POST"])
    @login_required
    def api_simulator():
        global simulator
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            action = payload.get("action", "").strip().lower()
            if simulator is None:
                simulator = MeterSimulator(app)
            if action == "start":
                simulator.start()
            elif action == "stop":
                simulator.stop()
            else:
                return jsonify({"ok": False, "message": "无效操作。"}), 400
            broadcast_full_state()
        return jsonify(
            {
                "ok": True,
                "running": bool(simulator and simulator.is_running()),
                "interval_seconds": simulator.interval_seconds if simulator else 0,
            }
        )

    @app.route("/api/device/upload", methods=["POST"])
    def api_device_upload():
        api_key = request.headers.get("X-API-Key", "").strip()
        payload = request.get_json(silent=True) or {}
        device = Device.query.filter_by(api_key=api_key).first()

        if device is None:
            return jsonify({"ok": False, "message": "无效设备密钥。"}), 401

        required_fields = [
            "timestamp",
            "instant_flow",
            "cumulative_usage",
            "battery_voltage",
            "signal_strength",
            "valve_state",
            "temperature",
            "pressure",
        ]
        if not all(field in payload for field in required_fields):
            return jsonify({"ok": False, "message": "上传数据字段不完整。"}), 400

        payload["timestamp"] = datetime.fromisoformat(payload["timestamp"])
        reading = ingest_reading(device, payload, source="device")
        return jsonify(
            {
                "ok": True,
                "meter_id": device.meter_id,
                "predicted_label": reading.predicted_label,
                "anomaly_score": reading.anomaly_score,
                "threshold": reading.threshold,
            }
        )

    @sock.route("/ws")
    def websocket(ws):
        hub.register(ws)
        try:
            ws.send(json.dumps({"event": "ready", "data": None}, ensure_ascii=False))
            while True:
                message = ws.receive()
                if message is None:
                    break
                if message == "bootstrap":
                    ws.send(
                        json.dumps(
                            {
                                "event": "bootstrap",
                                "data": {
                                    "dashboard": dashboard_snapshot(),
                                    "devices": devices_snapshot(),
                                    "alerts": alert_history(limit=30),
                                    "settings": settings_snapshot(),
                                },
                            },
                            ensure_ascii=False,
                        )
                    )
        finally:
            hub.unregister(ws)


def start_simulator(app: Flask) -> None:
    global simulator
    if simulator is None:
        simulator = MeterSimulator(app)
        simulator.start()


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
