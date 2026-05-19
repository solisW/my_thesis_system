from __future__ import annotations

import json
import os
import time
from pathlib import Path

from flask import Flask, flash, jsonify, redirect, request, session, url_for
from sqlalchemy.exc import OperationalError

from .application.auth import close_user_session, current_user, login_required, normalized_role, open_user_session, roles_required
from .application.http import register_cors
from .application.realtime import (
    broadcast_alert_state,
    broadcast_device_state,
    broadcast_engineer_state,
    broadcast_named,
    broadcast_settings_state,
    broadcast_user_state,
    broadcast_work_order_state,
)
from .application.runtime import RuntimeServices
from .config import ensure_directories, get_database_uri
from .database import Device, User, db, run_sqlite_migrations
from .domain.bootstrap import ensure_access_bootstrap, ensure_database, seed_defaults
from .domain.devices import (
    accept_device_reading,
    delete_device,
    devices_snapshot,
    purge_expired_physical_data,
    register_device_endpoint,
    set_device_enabled,
    test_device_connectivity,
)
from .domain.identity import (
    create_user,
    delete_engineer,
    delete_user,
    dispatch_candidate_engineers,
    engineers_snapshot,
    update_engineer,
    update_engineer_presence,
    update_user,
    user_full_name,
    user_username,
    username_lookup_value,
    users_snapshot,
)
from .domain.monitoring import (
    alerts_snapshot,
    dashboard_snapshot,
    device_history,
    reconstruction_snapshot,
    reports_snapshot,
    settings_snapshot,
)
from .domain.work_orders import (
    create_work_order,
    delete_work_order,
    engineer_accept_work_order,
    engineer_complete_work_order,
    update_work_order,
    work_orders_snapshot,
)
from .carrier_gateway import ingest_carrier_payload
from .model_registry import sync_active_model_metadata_to_db
from .realtime import hub, sock
from .security import cipher
from .services import labeled_samples_snapshot, update_alert_feedback


PROJECT_ROOT = Path(__file__).resolve().parent.parent
FRONTEND_ROOT = PROJECT_ROOT / "frontend"
runtime_services = RuntimeServices()
TRANSIENT_MYSQL_DDL_ERROR_CODES = {1205, 1213, 1684}


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.getenv("APP_SECRET_KEY", "gas-monitor-secret-key")
    app.config["SQLALCHEMY_DATABASE_URI"] = get_database_uri()
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_PERMANENT"] = False

    ensure_directories()
    ensure_database()
    db.init_app(app)
    sock.init_app(app)

    with app.app_context():
        initialize_database_with_retry(app)

    register_cors(app)
    register_routes(app)
    runtime_services.start_background_services(app)
    return app


def initialize_database_with_retry(
    app: Flask, retries: int = 6, delay_seconds: float = 1.5
) -> None:
    for attempt in range(1, retries + 1):
        try:
            db.create_all()
            run_sqlite_migrations()
            seed_defaults()
            ensure_access_bootstrap()
            sync_active_model_metadata_to_db()
            purge_expired_physical_data()
            return
        except OperationalError as exc:
            try:
                db.session.rollback()
            except Exception:
                db.session.remove()
            if not is_transient_mysql_startup_error(exc) or attempt >= retries:
                raise
            wait_seconds = delay_seconds * attempt
            app.logger.warning(
                "Database initialization is waiting for concurrent DDL to finish "
                "(attempt %s/%s, retrying in %.1fs): %s",
                attempt,
                retries,
                wait_seconds,
                exc.orig,
            )
            time.sleep(wait_seconds)


def is_transient_mysql_startup_error(exc: OperationalError) -> bool:
    original_error = getattr(exc, "orig", None)
    error_args = getattr(original_error, "args", ())
    error_code = error_args[0] if error_args else None
    message = " ".join(str(value) for value in error_args)
    if error_code in TRANSIENT_MYSQL_DDL_ERROR_CODES:
        return True
    return "concurrent DDL" in message or "being modified" in message


def register_routes(app: Flask) -> None:
    @app.route("/")
    def home():
        return jsonify(
            {
                "ok": True,
                "service": "smart-gas-monitor-api",
                "frontend": os.getenv("FRONTEND_URL", "http://127.0.0.1:5173"),
            }
        )

    @app.route("/api/auth/session")
    def api_auth_session():
        user = current_user()
        if user is None:
            return jsonify({"ok": False, "authenticated": False}), 401
        role = normalized_role(user)
        return jsonify(
            {
                "ok": True,
                "authenticated": True,
                "user": {
                    "id": user.id,
                    "username": user_username(user),
                    "full_name": user_full_name(user),
                    "role": role,
                    "engineer_id": user.engineer_id,
                },
                "ws_url": "/ws",
            }
        )

    @app.route("/api/auth/login", methods=["POST"])
    def api_auth_login():
        payload = request.get_json(silent=True) or {}
        username = str(payload.get("username", "")).strip()
        password = str(payload.get("password", ""))
        user = db.session.execute(
            db.select(User).filter_by(username_lookup=username_lookup_value(username))
        ).scalar_one_or_none()
        if not user:
            return jsonify({"ok": False, "message": "用户名或密码错误。"}), 401
        ok, migrated = cipher.verify(user.password_hash, password)
        if not ok or not user.is_active:
            return jsonify({"ok": False, "message": "用户名或密码错误。"}), 401
        if migrated is not None:
            user.password_hash = migrated
            db.session.commit()
        open_user_session(user)
        return api_auth_session()

    @app.route("/api/auth/logout", methods=["POST"])
    def api_auth_logout():
        close_user_session()
        return jsonify({"ok": True})

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "GET":
            return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = db.session.execute(
                db.select(User).filter_by(username_lookup=username_lookup_value(username))
            ).scalar_one_or_none()
            if user:
                ok, migrated = cipher.verify(user.password_hash, password)
                if ok and user.is_active:
                    if migrated is not None:
                        user.password_hash = migrated
                        db.session.commit()
                    open_user_session(user)
                    return redirect(url_for("dashboard"))
            flash("用户名或密码错误。", "error")
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173"))

    @app.route("/register", methods=["GET", "POST"])
    def register():
        if request.method == "GET":
            return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173"))
        user = current_user()
        role = normalized_role(user)
        if role != "super_admin":
            flash("请使用主管理员账号在用户管理中创建新账号。", "error")
            return redirect(url_for("login"))
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            full_name = request.form.get("full_name", "").strip()
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")

            if not username or not full_name or not password:
                flash("请完整填写注册信息。", "error")
            elif password != confirm_password:
                flash("两次输入的密码不一致。", "error")
            elif db.session.execute(
                db.select(User).filter_by(username_lookup=username_lookup_value(username))
            ).scalar_one_or_none():
                flash("该用户名已存在。", "error")
            else:
                db.session.add(
                    User(
                        username=f"user-{username_lookup_value(username)[:16]}",
                        username_encrypted=cipher.encrypt(username),
                        username_lookup=username_lookup_value(username),
                        full_name="已加密用户",
                        full_name_encrypted=cipher.encrypt(full_name),
                        password_hash=cipher.encrypt(password),
                        role="admin",
                    )
                )
                db.session.commit()
                flash("注册成功，请登录。", "success")
                return redirect(url_for("login"))
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173"))

    @app.route("/logout")
    def logout():
        close_user_session()
        return redirect(url_for("login"))

    @app.route("/api/session/close", methods=["POST"])
    def api_session_close():
        close_user_session()
        return ("", 204)

    @app.route("/dashboard")
    @login_required
    def dashboard():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/dashboard")

    @app.route("/devices")
    @login_required
    @roles_required("super_admin", "sub_admin")
    def devices_page():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/devices")

    @app.route("/engineers")
    @login_required
    @roles_required("super_admin", "sub_admin")
    def engineers_page():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/engineers")

    @app.route("/work-orders")
    @login_required
    def work_orders_page():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/work_orders")

    @app.route("/alerts")
    @login_required
    def alerts_page():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/alerts")

    @app.route("/reports")
    @login_required
    def reports_page():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/reports")

    @app.route("/history")
    @login_required
    def history_page():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/history")

    @app.route("/settings")
    @login_required
    @roles_required("super_admin", "sub_admin")
    def settings_page():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/settings")

    @app.route("/users")
    @login_required
    @roles_required("super_admin")
    def users_page():
        return redirect(os.getenv("FRONTEND_URL", "http://127.0.0.1:5173") + "#/users")

    @app.route("/api/dashboard")
    @login_required
    def api_dashboard():
        return jsonify(dashboard_snapshot())

    @app.route("/api/devices", methods=["GET", "POST"])
    @login_required
    def api_devices():
        if request.method == "GET":
            return jsonify(devices_snapshot())
        return jsonify({"ok": False, "message": "设备仅允许通过系统接入接口自动注册，管理端不支持手动新增。"}), 405

    @app.route("/api/devices/<int:device_id>", methods=["PUT", "DELETE"])
    @login_required
    def api_device_detail(device_id: int):
        if session.get("role") not in {"super_admin", "sub_admin"}:
            return jsonify({"ok": False, "message": "权限不足"}), 403
        if request.method == "PUT":
            payload = request.get_json(silent=True) or {}
            if "is_enabled" not in payload:
                return jsonify({"ok": False, "message": "管理端仅支持启用或停用设备。"}), 400
            result = set_device_enabled(device_id, payload.get("is_enabled"))
            broadcast_device_state()
            return jsonify({"ok": True, "device": result})
        if session.get("role") != "super_admin":
            return jsonify({"ok": False, "message": "只有主管理员可以删除设备。"}), 403
        delete_device(device_id)
        broadcast_device_state()
        broadcast_named("work_orders", work_orders_snapshot())
        broadcast_named("reports", reports_snapshot())
        return jsonify({"ok": True})

    @app.route("/api/devices/<int:device_id>/connectivity-test", methods=["POST"])
    @login_required
    @roles_required("super_admin", "sub_admin")
    def api_device_connectivity(device_id: int):
        return jsonify({"ok": True, **test_device_connectivity(device_id)})

    @app.route("/api/engineers", methods=["GET", "POST"])
    @login_required
    def api_engineers():
        if request.method == "GET":
            return jsonify(engineers_snapshot())
        return jsonify({"ok": False, "message": "工程师档案由用户管理中的工程师账号自动生成，当前页面不支持手动新增。"}), 405

    @app.route("/api/engineers/presence", methods=["POST"])
    @login_required
    @roles_required("engineer")
    def api_engineer_presence():
        payload = request.get_json(silent=True) or {}
        online = bool(payload.get("online", True))
        try:
            result = update_engineer_presence(current_user(), online=online)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        broadcast_named("engineers", engineers_snapshot())
        return jsonify({"ok": True, "engineer": result})

    @app.route("/api/engineers/<int:engineer_id>", methods=["PUT", "DELETE"])
    @login_required
    def api_engineer_detail(engineer_id: int):
        if session.get("role") not in {"super_admin", "sub_admin"}:
            return jsonify({"ok": False, "message": "权限不足"}), 403
        if request.method == "PUT":
            try:
                result = update_engineer(engineer_id, request.get_json(silent=True) or {})
            except ValueError as exc:
                return jsonify({"ok": False, "message": str(exc)}), 400
            broadcast_engineer_state()
            return jsonify({"ok": True, "engineer": result})
        delete_engineer(engineer_id)
        broadcast_engineer_state()
        return jsonify({"ok": True})

    @app.route("/api/users", methods=["GET", "POST"])
    @login_required
    @roles_required("super_admin")
    def api_users():
        if request.method == "GET":
            return jsonify(users_snapshot())
        try:
            result = create_user(request.get_json(silent=True) or {})
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        broadcast_user_state(include_settings=True)
        return jsonify({"ok": True, "user": result}), 201

    @app.route("/api/users/<int:user_id>", methods=["PUT", "DELETE"])
    @login_required
    @roles_required("super_admin")
    def api_user_detail(user_id: int):
        if request.method == "DELETE":
            try:
                delete_user(user_id)
            except ValueError as exc:
                return jsonify({"ok": False, "message": str(exc)}), 400
            broadcast_user_state(include_settings=True)
            return jsonify({"ok": True})
        try:
            result = update_user(user_id, request.get_json(silent=True) or {})
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        broadcast_user_state()
        return jsonify({"ok": True, "user": result})

    @app.route("/api/work-orders", methods=["GET", "POST"])
    @login_required
    def api_work_orders():
        user = current_user()
        if request.method == "GET":
            orders = work_orders_snapshot()
            if session.get("role") == "engineer" and user and user.engineer_id:
                orders = [item for item in orders if item["engineer_id"] == user.engineer_id]
            return jsonify(orders)
        if session.get("role") not in {"super_admin", "sub_admin"}:
            return jsonify({"ok": False, "message": "权限不足"}), 403
        try:
            result = create_work_order(request.get_json(silent=True) or {}, actor=user)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        broadcast_work_order_state()
        return jsonify({"ok": True, "work_order": result}), 201

    @app.route("/api/dispatch-candidates")
    @login_required
    @roles_required("super_admin", "sub_admin")
    def api_dispatch_candidates():
        region = request.args.get("region", "").strip()
        return jsonify(dispatch_candidate_engineers(region))

    @app.route("/api/work-orders/<int:order_id>", methods=["PUT", "DELETE"])
    @login_required
    def api_work_order_detail(order_id: int):
        if session.get("role") not in {"super_admin", "sub_admin"}:
            return jsonify({"ok": False, "message": "权限不足"}), 403
        if request.method == "PUT":
            try:
                result = update_work_order(order_id, request.get_json(silent=True) or {}, actor=current_user())
            except ValueError as exc:
                return jsonify({"ok": False, "message": str(exc)}), 400
            broadcast_work_order_state()
            return jsonify({"ok": True, "work_order": result})
        delete_work_order(order_id)
        broadcast_work_order_state()
        return jsonify({"ok": True})

    @app.route("/api/work-orders/<int:order_id>/accept", methods=["POST"])
    @login_required
    @roles_required("engineer")
    def api_work_order_accept(order_id: int):
        try:
            result = engineer_accept_work_order(order_id, current_user())
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        broadcast_named("work_orders", work_orders_snapshot())
        broadcast_named("reports", reports_snapshot())
        return jsonify({"ok": True, "work_order": result})

    @app.route("/api/work-orders/<int:order_id>/complete", methods=["POST"])
    @login_required
    @roles_required("engineer")
    def api_work_order_complete(order_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            result = engineer_complete_work_order(order_id, current_user(), str(payload.get("completion_note", "")))
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        broadcast_named("work_orders", work_orders_snapshot())
        broadcast_named("reports", reports_snapshot())
        return jsonify({"ok": True, "work_order": result})

    @app.route("/api/alerts")
    @login_required
    def api_alerts():
        sort_by = request.args.get("sort_by", "time").strip().lower()
        return jsonify(alerts_snapshot(limit=int(request.args.get("limit", 50)), sort_by=sort_by))

    @app.route("/api/alerts/<int:alert_id>/feedback", methods=["POST"])
    @login_required
    def api_alert_feedback(alert_id: int):
        payload = request.get_json(silent=True) or {}
        try:
            result = update_alert_feedback(alert_id, str(payload.get("confirmed_label", "")))
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        broadcast_alert_state()
        return jsonify({"ok": True, "alert": result})

    @app.route("/api/labeled-samples")
    @login_required
    @roles_required("super_admin", "sub_admin")
    def api_labeled_samples():
        return jsonify(labeled_samples_snapshot(limit=int(request.args.get("limit", 100))))

    @app.route("/api/reports")
    @login_required
    def api_reports():
        return jsonify(reports_snapshot())

    @app.route("/api/history")
    @login_required
    def api_history():
        meter_id = request.args.get("meter_id", "").strip() or None
        return jsonify(device_history(meter_id=meter_id, limit=int(request.args.get("limit", 200))))

    @app.route("/api/reconstruction")
    @login_required
    def api_reconstruction():
        meter_id = request.args.get("meter_id", "").strip() or None
        return jsonify(reconstruction_snapshot(meter_id=meter_id))

    @app.route("/api/settings")
    @login_required
    def api_settings():
        return jsonify(settings_snapshot())

    @app.route("/api/training", methods=["GET", "POST"])
    @login_required
    def api_training():
        trainer = runtime_services.trainer_service(app)
        if request.method == "POST":
            if session.get("role") not in {"super_admin", "sub_admin"}:
                return jsonify({"ok": False, "message": "权限不足"}), 403
            payload = request.get_json(silent=True) or {}
            action = str(payload.get("action", "")).strip().lower()
            if action == "start":
                trainer.start(
                    interval_seconds=payload.get("interval_seconds"),
                    meter_count=payload.get("meter_count"),
                    records_per_meter=payload.get("records_per_meter"),
                    seed=payload.get("seed"),
                )
            elif action == "stop":
                trainer.stop()
            else:
                return jsonify({"ok": False, "message": "无效训练操作。"}), 400
            broadcast_settings_state()
        return jsonify({"ok": True, "status": trainer.status()})

    @app.route("/api/simulator", methods=["GET", "POST"])
    @login_required
    def api_simulator():
        simulator = runtime_services.simulator
        if request.method == "POST":
            if session.get("role") not in {"super_admin", "sub_admin"}:
                return jsonify({"ok": False, "message": "权限不足"}), 403
            payload = request.get_json(silent=True) or {}
            action = payload.get("action", "").strip().lower()
            simulator = runtime_services.simulator_service(app)
            if action == "start":
                simulator.start()
            elif action == "stop":
                simulator.stop()
            else:
                return jsonify({"ok": False, "message": "无效操作。"}), 400
            broadcast_settings_state()
            broadcast_device_state()
        return jsonify(
            {
                "ok": True,
                "running": bool(simulator and simulator.is_running()),
                "interval_seconds": simulator.interval_seconds if simulator else 0,
                "registered_devices": simulator.registered_count() if simulator else 0,
            }
        )

    @app.route("/api/mqtt", methods=["GET", "POST"])
    @login_required
    @roles_required("super_admin", "sub_admin")
    def api_mqtt():
        mqtt_gateway = runtime_services.mqtt_service(app)
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            action = str(payload.get("action", "")).strip().lower()
            try:
                if action == "start":
                    mqtt_gateway.start()
                elif action == "stop":
                    mqtt_gateway.stop()
                else:
                    return jsonify({"ok": False, "message": "无效 MQTT 操作。"}), 400
            except RuntimeError as exc:
                return jsonify({"ok": False, "message": str(exc), "status": mqtt_gateway.status()}), 400
        return jsonify({"ok": True, "status": mqtt_gateway.status()})

    @app.route("/api/drift", methods=["GET", "POST"])
    @login_required
    @roles_required("super_admin", "sub_admin")
    def api_drift():
        drift_monitor = runtime_services.drift_monitor_service(app)
        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            action = str(payload.get("action", "check")).strip().lower()
            if action == "check":
                result = drift_monitor.check_once()
                return jsonify({"ok": True, "status": drift_monitor.status(), "result": result})
            if action == "start":
                drift_monitor.start()
            elif action == "stop":
                drift_monitor.stop()
            else:
                return jsonify({"ok": False, "message": "无效漂移监控操作。"}), 400
        return jsonify({"ok": True, "status": drift_monitor.status()})

    @app.route("/api/device/register", methods=["POST"])
    def api_device_register():
        payload = request.get_json(silent=True) or {}
        try:
            device = register_device_endpoint(payload)
        except ValueError as exc:
            return jsonify({"ok": False, "message": str(exc)}), 400
        return jsonify(
            {
                "ok": True,
                "meter_id": device.meter_id,
                "api_key": device.api_key,
                "protocol": device.protocol,
            }
        )

    @app.route("/api/device/upload", methods=["POST"])
    def api_device_upload():
        api_key = request.headers.get("X-API-Key", "").strip()
        payload = request.get_json(silent=True) or {}
        try:
            device, reading = accept_device_reading(api_key, payload, emit_event=True)
        except ValueError as exc:
            status = 401 if "密钥" in str(exc) else 400
            return jsonify({"ok": False, "message": str(exc)}), status
        return jsonify(
            {
                "ok": True,
                "meter_id": device.meter_id,
                "predicted_label": reading.predicted_label,
                "anomaly_score": reading.anomaly_score,
                "threshold": reading.threshold,
                "model_version": reading.model_version,
                "detection_status": "pending" if reading.anomaly_score is None else "completed",
            }
        )

    @app.route("/api/carrier/webhook/<provider>", methods=["POST"])
    def api_carrier_webhook(provider: str):
        payload = request.get_json(silent=True) or {}
        try:
            result = ingest_carrier_payload(provider, payload, request.headers.get("X-Carrier-Token", ""))
        except ValueError as exc:
            status = 401 if "令牌" in str(exc) else 400
            return jsonify({"ok": False, "message": str(exc)}), status
        return jsonify({"ok": True, **result})

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
                                    "alerts": alerts_snapshot(limit=50),
                                    "engineers": engineers_snapshot(),
                                    "users": users_snapshot() if session.get("role") == "super_admin" else [],
                                    "work_orders": work_orders_snapshot(),
                                    "reports": reports_snapshot(),
                                    "settings": settings_snapshot(),
                                },
                            },
                            ensure_ascii=False,
                        )
                    )
        finally:
            hub.unregister(ws)


app = create_app()


if __name__ == "__main__":
    app.run(debug=True, use_reloader=False)
