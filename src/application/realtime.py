from __future__ import annotations

from typing import Any

from ..domain.devices import devices_snapshot
from ..domain.identity import engineers_snapshot, users_snapshot
from ..domain.monitoring import alerts_snapshot, dashboard_snapshot, reports_snapshot, settings_snapshot
from ..domain.work_orders import work_orders_snapshot
from ..realtime import hub


def broadcast_named(event: str, payload: Any) -> None:
    hub.broadcast(event, payload)


def broadcast_device_state() -> None:
    dashboard = dashboard_snapshot()
    hub.broadcast("devices", devices_snapshot())
    hub.broadcast("dashboard", dashboard)
    hub.broadcast("map", dashboard["map_points"])


def broadcast_engineer_state() -> None:
    hub.broadcast("engineers", engineers_snapshot())
    hub.broadcast("work_orders", work_orders_snapshot())
    hub.broadcast("dashboard", dashboard_snapshot())
    hub.broadcast("reports", reports_snapshot())


def broadcast_user_state(include_settings: bool = False) -> None:
    hub.broadcast("users", users_snapshot())
    hub.broadcast("engineers", engineers_snapshot())
    if include_settings:
        hub.broadcast("settings", settings_snapshot())


def broadcast_work_order_state() -> None:
    hub.broadcast("work_orders", work_orders_snapshot())
    hub.broadcast("dashboard", dashboard_snapshot())
    hub.broadcast("reports", reports_snapshot())


def broadcast_alert_state() -> None:
    hub.broadcast("alerts", alerts_snapshot(limit=50, sort_by="time"))
    hub.broadcast("reports", reports_snapshot())


def broadcast_settings_state() -> None:
    hub.broadcast("settings", settings_snapshot())
