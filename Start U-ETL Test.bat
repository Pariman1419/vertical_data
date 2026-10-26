@echo off
setlocal
cd /d "%~dp0"
title U-ETL Factory Data Bridge - Local Test

if not exist ".spike-venv\Scripts\python.exe" (
  echo Oracle read-only test runtime is not installed.
  echo See README.md for setup instructions or contact the project maintainer.
  echo.
  pause
  exit /b 1
)

echo Starting U-ETL local HTTPS test server.
echo Enter your local application passphrase when prompted. Do NOT enter the Oracle password here.
echo This window must remain open while you use the app. Press Ctrl+C here to stop.
echo.
"%~dp0.spike-venv\Scripts\python.exe" -m backend.spike.server

echo.
echo U-ETL test server stopped.
pause
endlocal
