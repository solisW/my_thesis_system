from __future__ import annotations

from functools import wraps

from flask import flash, jsonify, redirect, request, session, url_for

from ..database import User, db
from ..domain.identity import update_engineer_presence, user_full_name


def current_user() -> User | None:
    user_id = session.get("user_id")
    if not user_id:
        return None
    return db.session.get(User, user_id)


def normalized_role(user: User | None) -> str | None:
    role = user.role if user else None
    return "sub_admin" if role == "admin" else role


def open_user_session(user: User) -> None:
    if user.role == "engineer":
        try:
            update_engineer_presence(user, online=True)
        except ValueError:
            pass
    session["user_id"] = user.id
    session["username"] = user_full_name(user)
    session["role"] = normalized_role(user)
    session["engineer_id"] = user.engineer_id
    session.permanent = False


def close_user_session() -> None:
    user = current_user()
    if user and user.role == "engineer":
        try:
            update_engineer_presence(user, online=False)
        except ValueError:
            pass
    session.clear()


def login_required(view):
    @wraps(view)
    def wrapped_view(*args, **kwargs):
        if "user_id" not in session:
            if request.path.startswith("/api/"):
                return jsonify({"ok": False, "message": "未登录或会话已过期。"}), 401
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped_view


def roles_required(*allowed_roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped_view(*args, **kwargs):
            user = current_user()
            role = normalized_role(user)
            if user is None:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "message": "未登录或会话已过期。"}), 401
                return redirect(url_for("login"))
            if role not in allowed_roles:
                if request.path.startswith("/api/"):
                    return jsonify({"ok": False, "message": "权限不足"}), 403
                flash("当前账号没有访问该页面的权限。", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)

        return wrapped_view

    return decorator


def nav_context(active_page: str) -> dict[str, str]:
    user = current_user()
    return {
        "user_name": session.get("username", "系统管理员"),
        "user_role": normalized_role(user) or "guest",
        "engineer_id": str(user.engineer_id or "") if user else "",
        "active_page": active_page,
        "ws_url": "/ws",
    }
