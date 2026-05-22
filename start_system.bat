@echo off
setlocal
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start_single_window.ps1"
set "EXIT_CODE=%errorlevel%"
if not "%EXIT_CODE%"=="0" pause
exit /b %EXIT_CODE%
