from __future__ import annotations

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("DB_BACKEND", "sqlite")
os.environ.setdefault("DRIFT_MONITOR_ENABLED", "0")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app import app
from src.carrier_gateway import ingest_carrier_payload
from src.domain.monitoring import settings_snapshot
from src.services import devices_snapshot


def main() -> None:
    payload = {
        "deviceId": "GM-SMOKE-001",
        "eventTime": 1777608000000,
        "properties": {
            "instantFlow": 0.326,
            "cumulativeUsage": 180.52,
            "batteryVoltage": 3.21,
            "RSSI": 74.8,
            "valveState": "open",
            "envTemperature": 19.2,
            "pipePressure": 2.06,
        },
    }

    with app.app_context():
        result = ingest_carrier_payload("smoke", payload)
        settings = settings_snapshot()
        devices = devices_snapshot()

    ok = (
        result["meter_id"] == "GM-SMOKE-001"
        and settings["device_upload_api"] == "/api/device/upload"
        and settings["carrier_webhook_api"] == "/api/carrier/webhook/<provider>"
        and any(item["meter_id"] == "GM-SMOKE-001" for item in devices)
    )
    print(json.dumps({"ok": ok, "carrier_result": result}, ensure_ascii=False, indent=2))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
