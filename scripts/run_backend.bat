@echo off
title TrafficShield - Backend (Flask API)
set "PROJECT_ROOT=%~dp0..\"
cd /d "%PROJECT_ROOT%"

echo ========================================================
echo  TrafficShield Backend Service (Flask API)
echo  Port: 5000 ^| Health: http://127.0.0.1:5000/api/v1/health
echo ========================================================
echo.

python run.py
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Backend process terminated with exit code %errorlevel%.
    echo Terminal kept open for inspection.
    pause
)
