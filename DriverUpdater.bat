@echo off
chcp 65001 >nul
rem Relaunch as administrator (required to install drivers).
net session >nul 2>&1
if %errorlevel% neq 0 (
  powershell -NoProfile -Command "Start-Process -FilePath '%~f0' -ArgumentList '%*' -Verb RunAs"
  exit /b
)
cd /d "%~dp0"
if "%~1"=="" (
  python -m driverupdater install
) else (
  python -m driverupdater %*
)
pause
