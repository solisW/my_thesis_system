from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("DRIFT_MONITOR_ENABLED", "0")
os.environ.setdefault("ASYNC_DETECTION_ENABLED", "0")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import app
from src.carrier_gateway import ingest_carrier_payload
from src.domain.monitoring import settings_snapshot
from src.services import devices_snapshot


def assert_true(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def assert_response_ok(response, message: str, expected_status: int = 200):
    payload = response.get_json(silent=True) or {}
    assert_true(
        response.status_code == expected_status,
        f"{message}: expected HTTP {expected_status}, got {response.status_code}, payload={payload}",
    )
    return payload


def validate_frontend_assets() -> list[str]:
    frontend_root = PROJECT_ROOT / "frontend"
    index_path = frontend_root / "index.html"
    assert_true(index_path.exists(), "frontend/index.html is missing")
    html = index_path.read_text(encoding="utf-8")
    assert_true("<div id=\"app\">" in html, "frontend mount point is missing")
    assert_true("</title>" in html and "</html>" in html, "frontend HTML is incomplete")

    import re

    refs = re.findall(r"""(?:src|href)=["']([^"']+)["']""", html)
    checked: list[str] = []
    for ref in refs:
        parsed = urlparse(ref)
        if parsed.scheme or parsed.netloc:
            continue
        local_path = frontend_root / parsed.path.lstrip("./")
        assert_true(local_path.exists(), f"frontend asset is missing: {ref}")
        checked.append(ref)
    return checked


def validate_authenticated_api() -> dict[str, object]:
    payload = {
        "deviceId": "GM-HEALTH-001",
        "eventTime": int(time.time() * 1000),
        "properties": {
            "instantFlow": 0.42,
            "cumulativeUsage": 226.8,
            "batteryVoltage": 3.18,
            "RSSI": 78.0,
            "valveState": "open",
            "envTemperature": 21.3,
            "pipePressure": 2.12,
        },
    }
    reading_payload = {
        "meter_id": "GM-HEALTH-HTTP",
        "name": "Health Check Meter",
        "location": "Health Check Station",
        "area": "A区",
        "timestamp": datetime.now().isoformat(),
        "instant_flow": 0.35,
        "cumulative_usage": 128.4,
        "battery_voltage": 3.22,
        "signal_strength": 82.0,
        "valve_state": 1,
        "temperature": 20.5,
        "pressure": 2.04,
    }

    with app.test_client() as client:
        root = assert_response_ok(client.get("/"), "root API")
        assert_true(root.get("ok") is True, "root API did not return ok=true")
        assert_response_ok(client.get("/api/auth/session"), "anonymous session", expected_status=401)

        login = assert_response_ok(
            client.post(
                "/api/auth/login",
                json={
                    "username": os.getenv("SUPER_ADMIN_USERNAME", "solisW"),
                    "password": os.getenv("SUPER_ADMIN_PASSWORD", "777803wzw@"),
                },
            ),
            "admin login",
        )
        assert_true(login.get("authenticated") is True, "admin login did not create a session")

        endpoints = [
            "/api/dashboard",
            "/api/devices",
            "/api/alerts",
            "/api/work-orders",
            "/api/engineers",
            "/api/users",
            "/api/history",
            "/api/reconstruction",
            "/api/reports",
            "/api/settings",
            "/api/training",
            "/api/drift",
            "/api/mqtt",
            "/api/labeled-samples",
        ]
        for endpoint in endpoints:
            assert_response_ok(client.get(endpoint), endpoint)

        registered = assert_response_ok(
            client.post(
                "/api/device/register",
                json={
                    "meter_id": reading_payload["meter_id"],
                    "name": reading_payload["name"],
                    "location": reading_payload["location"],
                    "area": reading_payload["area"],
                    "protocol": "HTTP",
                },
            ),
            "device register",
        )
        assert_true(registered.get("api_key"), "device register did not return api_key")
        upload = assert_response_ok(
            client.post(
                "/api/device/upload",
                json=reading_payload,
                headers={"X-API-Key": registered["api_key"]},
            ),
            "device upload",
        )
        assert_true(upload.get("ok") is True, "device upload did not return ok=true")

    with app.app_context():
        carrier_result = ingest_carrier_payload("smoke", payload)
        settings = settings_snapshot()
        devices = devices_snapshot()

    assert_true(carrier_result["meter_id"] == "GM-HEALTH-001", "carrier webhook did not ingest the expected meter")
    assert_true(settings["device_upload_api"] == "/api/device/upload", "settings device upload API is wrong")
    assert_true(
        settings["carrier_webhook_api"] == "/api/carrier/webhook/<provider>",
        "settings carrier webhook API is wrong",
    )
    assert_true(
        any(item["meter_id"] == "GM-HEALTH-001" for item in devices),
        "carrier-ingested device is missing from device snapshot",
    )
    assert_true(
        any(item["meter_id"] == "GM-HEALTH-HTTP" for item in devices),
        "HTTP-ingested device is missing from device snapshot",
    )
    return {
        "carrier_result": carrier_result,
        "checked_endpoints": endpoints,
    }


def main() -> None:
    frontend_assets = validate_frontend_assets()
    api_result = validate_authenticated_api()
    print(
        {
            "ok": True,
            "checked_frontend_assets": len(frontend_assets),
            "checked_endpoints": len(api_result["checked_endpoints"]),
            "carrier_meter_id": api_result["carrier_result"]["meter_id"],
        }
    )


if __name__ == "__main__":
    main()
