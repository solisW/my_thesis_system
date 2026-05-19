from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
FRONTEND_URL = os.getenv("FRONTEND_URL", "http://127.0.0.1:5173").rstrip("/")
BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:5000").rstrip("/")
ADMIN_USERNAME = os.getenv("SUPER_ADMIN_USERNAME", "solisW")
ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "777803wzw@")


REQUIRED_FILES = [
    "start_system.bat",
    "requirements.txt",
    "src/app.py",
    "src/application/auth.py",
    "src/application/http.py",
    "src/application/realtime.py",
    "src/application/runtime.py",
    "src/domain/devices.py",
    "src/domain/identity.py",
    "src/domain/monitoring.py",
    "src/domain/work_orders.py",
    "frontend/index.html",
    "frontend/src/config.js",
    "frontend/src/api.js",
    "frontend/src/formatters.js",
    "frontend/src/map-utils.js",
    "frontend/src/main.js",
    "frontend/src/styles.css",
    "frontend/vendor/vue.global.prod.js",
    "frontend/vendor/echarts.min.js",
    "frontend/vendor/leaflet.js",
    "frontend/vendor/leaflet.css",
]


FRONTEND_ASSETS = [
    "/",
    "/src/config.js",
    "/src/api.js",
    "/src/formatters.js",
    "/src/map-utils.js",
    "/src/main.js",
    "/src/styles.css",
    "/vendor/vue.global.prod.js",
    "/vendor/echarts.min.js",
    "/vendor/leaflet.js",
    "/vendor/leaflet.css",
]


def result(name: str, ok: bool, detail: str = "") -> dict[str, object]:
    return {"name": name, "ok": ok, "detail": detail}


def run_command(name: str, command: list[str]) -> dict[str, object]:
    try:
        completed = subprocess.run(
            command,
            cwd=ROOT,
            text=True,
            capture_output=True,
            timeout=60,
            check=False,
        )
    except FileNotFoundError as exc:
        return result(name, False, f"command not found: {exc.filename}")
    except subprocess.TimeoutExpired:
        return result(name, False, "command timed out")
    output = (completed.stdout + completed.stderr).strip()
    return result(name, completed.returncode == 0, output[-1200:])


def http_get(url: str, timeout: int = 8) -> tuple[bool, int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:
            body = response.read(4000).decode("utf-8", errors="replace")
            return 200 <= response.status < 400, response.status, body
    except urllib.error.HTTPError as exc:
        return False, exc.code, exc.read(1000).decode("utf-8", errors="replace")
    except Exception as exc:
        return False, None, str(exc)


def check_required_files() -> dict[str, object]:
    missing = [path for path in REQUIRED_FILES if not (ROOT / path).exists()]
    return result("required_files", not missing, ", ".join(missing) if missing else "all required files exist")


def check_frontend_assets() -> list[dict[str, object]]:
    checks = []
    for asset in FRONTEND_ASSETS:
        ok, status, detail = http_get(f"{FRONTEND_URL}{asset}")
        checks.append(result(f"frontend_asset {asset}", ok, f"status={status}, detail={detail[:120]}"))
    return checks


def check_backend_root() -> dict[str, object]:
    ok, status, detail = http_get(BACKEND_URL)
    return result("backend_root", ok and '"ok":true' in detail.replace(" ", ""), f"status={status}, detail={detail[:300]}")


def check_login_and_dashboard() -> dict[str, object]:
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
    payload = json.dumps({"username": ADMIN_USERNAME, "password": ADMIN_PASSWORD}).encode("utf-8")
    request = urllib.request.Request(
        f"{BACKEND_URL}/api/auth/login",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with opener.open(request, timeout=12) as response:
            login_body = response.read().decode("utf-8", errors="replace")
        with opener.open(f"{BACKEND_URL}/api/dashboard", timeout=20) as response:
            dashboard_body = response.read().decode("utf-8", errors="replace")
        ok = '"authenticated":true' in login_body.replace(" ", "") and response.status == 200
        return result("login_and_dashboard", ok, f"login={login_body[:220]}, dashboard_bytes={len(dashboard_body)}")
    except Exception as exc:
        return result("login_and_dashboard", False, str(exc))


def main() -> int:
    checks: list[dict[str, object]] = [
        check_required_files(),
        run_command("python_compile", [sys.executable, "-m", "compileall", "src"]),
        run_command("frontend_main_js_syntax", ["node", "--check", "frontend/src/main.js"]),
        run_command("frontend_config_js_syntax", ["node", "--check", "frontend/src/config.js"]),
        run_command("frontend_api_js_syntax", ["node", "--check", "frontend/src/api.js"]),
        run_command("frontend_formatters_js_syntax", ["node", "--check", "frontend/src/formatters.js"]),
        run_command("frontend_map_utils_js_syntax", ["node", "--check", "frontend/src/map-utils.js"]),
    ]
    checks.extend(check_frontend_assets())
    checks.append(check_backend_root())
    checks.append(check_login_and_dashboard())

    ok = all(bool(item["ok"]) for item in checks)
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
