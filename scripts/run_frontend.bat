@echo off
title TrafficShield - Frontend (Vite UI)
set "PROJECT_ROOT=%~dp0..\"
cd /d "%PROJECT_ROOT%frontend"

echo ========================================================
echo  TrafficShield Frontend Service (Vite UI)
echo  Port: 5173 ^| URL: http://localhost:5173/
echo ========================================================
echo.

call npm.cmd run dev
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Frontend process terminated with exit code %errorlevel%.
    echo Terminal kept open for inspection.
    pause
)
