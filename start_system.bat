@echo off
setlocal
cd /d "%~dp0"

set "PYTHONUTF8=1"
set "PROJECT_ROOT=%~dp0"
if not defined DB_BACKEND set "DB_BACKEND=mysql"
if not defined MYSQL_HOST set "MYSQL_HOST=127.0.0.1"
if not defined MYSQL_PORT set "MYSQL_PORT=3306"
if not defined MYSQL_DATABASE set "MYSQL_DATABASE=gas_monitor"
if not defined MYSQL_USER set "MYSQL_USER=root"
if not defined MYSQL_PASSWORD set "MYSQL_PASSWORD=wcy20031001WCY"
if not defined APP_CREDENTIAL_SECRET set "APP_CREDENTIAL_SECRET=gas-monitor-default-secret"
if not defined APP_SECRET_KEY set "APP_SECRET_KEY=gas-monitor-secret-key"
if not defined FLASK_HOST set "FLASK_HOST=127.0.0.1"
if not defined FLASK_PORT set "FLASK_PORT=5000"
if not defined FRONTEND_HOST set "FRONTEND_HOST=127.0.0.1"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"
if not defined FRONTEND_URL set "FRONTEND_URL=http://127.0.0.1:5173"
if not defined FRONTEND_ORIGINS set "FRONTEND_ORIGINS=http://127.0.0.1:5173,http://localhost:5173"
if not defined ASYNC_DETECTION_ENABLED set "ASYNC_DETECTION_ENABLED=1"
if not defined DRIFT_MONITOR_ENABLED set "DRIFT_MONITOR_ENABLED=1"
if not defined SIMULATION_DEVICE_COUNT set "SIMULATION_DEVICE_COUNT=50"
if not defined MQTT_HOST set "MQTT_HOST=127.0.0.1"
if not defined MQTT_PORT set "MQTT_PORT=1883"
if not defined MQTT_REGISTER_TOPIC set "MQTT_REGISTER_TOPIC=gas-meter/register"
if not defined MQTT_UPLOAD_TOPIC set "MQTT_UPLOAD_TOPIC=gas-meter/+/upload"

if not exist "%PROJECT_ROOT%frontend\index.html" (
    echo Frontend entry not found: %PROJECT_ROOT%frontend\index.html
    pause
    exit /b 1
)

python -c "import flask, sqlalchemy, torch, pandas, sklearn, joblib, paho.mqtt.client" >nul 2>nul
if errorlevel 1 (
    echo Missing Python dependencies. Run: pip install -r requirements.txt
    pause
    exit /b 1
)

echo Starting Smart Gas Monitoring System...
echo API=http://%FLASK_HOST%:%FLASK_PORT%
echo Frontend=http://%FRONTEND_HOST%:%FRONTEND_PORT%
echo Database=%DB_BACKEND% ^(%MYSQL_HOST%:%MYSQL_PORT%/%MYSQL_DATABASE%^)
echo Integrated controls: frontend Settings page can start or stop simulator, continuous training, drift monitor, and MQTT gateway.
echo.

echo Checking occupied ports...
powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %FRONTEND_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 11 }"
if errorlevel 11 (
    echo Frontend port %FRONTEND_PORT% is already in use. Reusing existing frontend service.
) else (
    echo Starting frontend window...
    start "Smart Gas Frontend" cmd /k "cd /d %PROJECT_ROOT%frontend && python -m http.server %FRONTEND_PORT% --bind %FRONTEND_HOST%"
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %FLASK_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 12 }"
if errorlevel 12 (
    echo Backend port %FLASK_PORT% is already in use. Reusing existing backend service.
) else (
    echo Starting backend window...
    start "Smart Gas Backend" cmd /k "cd /d %PROJECT_ROOT% && python -m flask --app src.app run --host %FLASK_HOST% --port %FLASK_PORT%"
)

echo.
echo Waiting for services...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(45); do { try { $r=Invoke-WebRequest -UseBasicParsing 'http://%FRONTEND_HOST%:%FRONTEND_PORT%' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
    echo Frontend did not become ready on http://%FRONTEND_HOST%:%FRONTEND_PORT%
    echo Check the Smart Gas Frontend window for details.
    pause
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "$deadline=(Get-Date).AddSeconds(60); do { try { $r=Invoke-WebRequest -UseBasicParsing 'http://%FLASK_HOST%:%FLASK_PORT%' -TimeoutSec 2; if ($r.StatusCode -eq 200) { exit 0 } } catch {}; Start-Sleep -Seconds 1 } while ((Get-Date) -lt $deadline); exit 1"
if errorlevel 1 (
    echo Backend did not become ready on http://%FLASK_HOST%:%FLASK_PORT%
    echo Keep DB_BACKEND=mysql by default. Please check that MySQL is running and the database credentials are correct.
    echo Check the Smart Gas Backend window for the exact error.
    pause
    exit /b 1
)

echo.
echo System is ready.
echo Frontend: http://%FRONTEND_HOST%:%FRONTEND_PORT%
echo Backend : http://%FLASK_HOST%:%FLASK_PORT%
echo Default admin: solisW / 777803wzw@
set "APP_URL=http://%FRONTEND_HOST%:%FRONTEND_PORT%"
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
    start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --new-window "%APP_URL%"
) else if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" (
    start "" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" --new-window "%APP_URL%"
) else if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
    start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --new-window "%APP_URL%"
) else if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
    start "" "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" --new-window "%APP_URL%"
) else (
    echo Edge or Chrome was not found in the default install paths. Opening the system default browser.
    echo If the page shows frontend startup failure, open %APP_URL% manually in Microsoft Edge or Google Chrome.
    start "" "%APP_URL%"
)
echo.
echo You can close this launcher window. Keep the Frontend and Backend windows open while using the system.
pause
