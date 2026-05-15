@echo off
setlocal
cd /d "%~dp0"

set "PYTHONUTF8=1"
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
if not defined FRONTEND_URL set "FRONTEND_URL=http://127.0.0.1:5173"
if not defined FRONTEND_ORIGINS set "FRONTEND_ORIGINS=http://127.0.0.1:5173,http://localhost:5173"
if not defined ASYNC_DETECTION_ENABLED set "ASYNC_DETECTION_ENABLED=1"
if not defined DRIFT_MONITOR_ENABLED set "DRIFT_MONITOR_ENABLED=1"
if not defined SIMULATION_DEVICE_COUNT set "SIMULATION_DEVICE_COUNT=50"
if not defined MQTT_HOST set "MQTT_HOST=127.0.0.1"
if not defined MQTT_PORT set "MQTT_PORT=1883"
if not defined MQTT_REGISTER_TOPIC set "MQTT_REGISTER_TOPIC=gas-meter/register"
if not defined MQTT_UPLOAD_TOPIC set "MQTT_UPLOAD_TOPIC=gas-meter/+/upload"

python -c "import flask, sqlalchemy, torch, pandas, sklearn, joblib, paho.mqtt.client" >nul 2>nul
if errorlevel 1 (
    echo Missing Python dependencies. Run: pip install -r requirements.txt
    exit /b 1
)

echo Starting Smart Gas Monitoring Backend API...
echo API=http://%FLASK_HOST%:%FLASK_PORT%
echo Frontend=http://127.0.0.1:5173  ^(run start_frontend.bat in another terminal^)
echo Integrated controls: frontend Settings page can start or stop simulator, continuous training, drift monitor, and MQTT gateway.
python -m flask --app src.app run --host "%FLASK_HOST%" --port "%FLASK_PORT%"

echo.
echo Smart Gas Monitoring System stopped. Press any key to close this window.
pause >nul
