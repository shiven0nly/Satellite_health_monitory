@echo off
:: run_all.bat — Launch all four satellite-health-monitor processes
:: Usage: run_all.bat
:: Stop: close this window or press Ctrl+C

setlocal

echo.
echo ==========================================
echo  Satellite Health Monitor — Launcher
echo ==========================================
echo.

:: ── 1. Receiver API (must start before dashboard polls it) ──────────────────
echo [1/4] Starting Receiver API  on :8502 ...
pushd %~dp0receiver
start "Receiver-API :8502" cmd /k "uv run uvicorn api:app --port 8502 --reload"
popd
timeout /t 3 /nobreak >nul

:: ── 2. Receiver Dashboard ───────────────────────────────────────────────────
echo [2/4] Starting Receiver Dashboard on :8503 ...
pushd %~dp0receiver
start "Receiver-Dashboard :8503" cmd /k "uv run streamlit run dashboard.py --server.port 8503"
popd
timeout /t 2 /nobreak >nul

:: ── 3. Backend anomaly engine ───────────────────────────────────────────────
echo [3/4] Starting Backend Anomaly Engine on :8000 ...
pushd %~dp0backend
start "Backend :8000" cmd /k "uv run uvicorn app.main:app --port 8000 --reload"
popd
timeout /t 3 /nobreak >nul

:: ── 4. Sender Streamlit app ─────────────────────────────────────────────────
echo [4/4] Starting Sender Telemetry App on :8501 ...
pushd %~dp0sender
start "Sender :8501" cmd /k "uv run streamlit run app.py --server.port 8501"
popd

echo.
echo ==========================================
echo  All services launched in separate windows
echo.
echo   Sender Dashboard  →  http://localhost:8501
echo   Backend API docs  →  http://localhost:8000/docs
echo   Receiver API docs →  http://localhost:8502/docs
echo   Alert Dashboard   →  http://localhost:8503
echo ==========================================
echo.
echo Close individual windows to stop services.
pause
