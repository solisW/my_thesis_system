@echo off
setlocal
cd /d "%~dp0frontend"

set "PYTHONUTF8=1"
if not defined FRONTEND_HOST set "FRONTEND_HOST=127.0.0.1"
if not defined FRONTEND_PORT set "FRONTEND_PORT=5173"

if not exist "index.html" (
    echo Frontend entry not found: %cd%\index.html
    exit /b 1
)

powershell -NoProfile -ExecutionPolicy Bypass -Command "if (Get-NetTCPConnection -LocalPort %FRONTEND_PORT% -State Listen -ErrorAction SilentlyContinue) { exit 7 }"
if errorlevel 7 (
    echo Frontend port %FRONTEND_PORT% is already in use.
    echo URL=http://%FRONTEND_HOST%:%FRONTEND_PORT%
    echo If the page is stale, close the old server window and run this script again.
    pause >nul
    exit /b 0
)

echo Starting Smart Gas Monitoring Frontend...
echo URL=http://%FRONTEND_HOST%:%FRONTEND_PORT%
python -m http.server "%FRONTEND_PORT%" --bind "%FRONTEND_HOST%"

echo.
echo Frontend stopped. Press any key to close this window.
pause >nul
