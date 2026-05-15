@echo off
setlocal
cd /d "%~dp0frontend"

if not defined FRONTEND_HOST set "FRONTEND_HOST=127.0.0.1"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"

echo Starting Smart Gas Monitoring Frontend...
echo URL=http://%FRONTEND_HOST%:%FRONTEND_PORT%
python -m http.server "%FRONTEND_PORT%" --bind "%FRONTEND_HOST%"

echo.
echo Frontend stopped. Press any key to close this window.
pause >nul
