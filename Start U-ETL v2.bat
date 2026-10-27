@echo off
setlocal
cd /d "%~dp0"
title U-ETL v2 (Phase 1) - local

rem Reads UETL_* settings from .env (git-ignored). The legacy pilot launcher is unchanged.
echo Starting U-ETL v2 API + UI on http://127.0.0.1:8443
echo Press Ctrl+C to stop.
python -m uvicorn backend.v2.app:app --host 127.0.0.1 --port 8443

echo.
echo U-ETL v2 stopped.
pause
endlocal
