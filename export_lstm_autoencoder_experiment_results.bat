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

python -c "import torch, pandas, sklearn, joblib, numpy" >nul 2>nul
if errorlevel 1 (
    echo Missing experiment evaluation dependencies. Run: pip install -r requirements.txt
    exit /b 1
)

echo Exporting LSTM AutoEncoder experiment results...
python scripts\evaluate_lstm_autoencoder_experiment_results.py %*
if errorlevel 1 exit /b 1

echo.
echo Experiment results exported.
