@echo off
setlocal
cd /d "%~dp0"

set "PYTHONUTF8=1"
if not defined DB_BACKEND set "DB_BACKEND=sqlite"
if not defined DRIFT_MONITOR_ENABLED set "DRIFT_MONITOR_ENABLED=0"
if not defined APP_CREDENTIAL_SECRET set "APP_CREDENTIAL_SECRET=gas-monitor-default-secret"

echo Running project health check: Python compile...
python -m compileall src scripts
if errorlevel 1 exit /b 1

where node >nul 2>nul
if errorlevel 1 (
    echo Node.js not found. Skipping frontend/src/main.js syntax check.
) else (
    echo Running project health check: independent frontend JavaScript syntax...
    node --check frontend\src\main.js
    if errorlevel 1 exit /b 1
)

echo Running project health check: backend smoke test...
python scripts\validate_project_health.py
if errorlevel 1 exit /b 1

echo.
echo Project health check passed.
