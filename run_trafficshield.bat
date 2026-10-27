@echo off
setlocal EnableExtensions EnableDelayedExpansion

:: ============================================================================
:: TrafficShield — One-Click Development Launcher
:: Starts Flask Backend (Port 5000) and React+Vite Frontend (Port 5173)
:: ============================================================================

title TrafficShield Launcher

set "PROJECT_ROOT=%~dp0"
cd /d "%PROJECT_ROOT%"

echo ============================================================================
echo   TrafficShield — Unidirectional IP Traffic Anomaly Detection
echo   One-Click Launcher (Development Environment)
echo ============================================================================
echo.

:: ----------------------------------------------------------------------------
:: 1. Verify Prerequisites & Environment
:: ----------------------------------------------------------------------------
echo [1/4] Verifying prerequisites and environment...

where python.exe >nul 2>&1
if %errorlevel% neq 0 goto :err_no_python

where node.exe >nul 2>&1
if %errorlevel% neq 0 goto :err_no_node

where npm.cmd >nul 2>&1
if %errorlevel% neq 0 (
    where npm >nul 2>&1
    if !errorlevel! neq 0 goto :err_no_npm
)

if not exist "%PROJECT_ROOT%run.py" goto :err_no_run
if not exist "%PROJECT_ROOT%frontend\package.json" goto :err_no_pkg
if not exist "%PROJECT_ROOT%frontend\node_modules" goto :err_no_modules
if not exist "%PROJECT_ROOT%scripts\launcher_helper.py" goto :err_no_helper
if not exist "%PROJECT_ROOT%scripts\run_backend.bat" goto :err_no_backend_bat
if not exist "%PROJECT_ROOT%scripts\run_frontend.bat" goto :err_no_frontend_bat

echo   - Python: OK
echo   - Node.js and npm: OK
echo   - Project structure and node_modules: OK
echo.

:: ----------------------------------------------------------------------------
:: 2. Check Port Availability and Existing Services
:: ----------------------------------------------------------------------------
echo [2/4] Checking ports and service status...

set "BACKEND_STATUS=FREE"
set "FRONTEND_STATUS=FREE"

for /f "tokens=1,2 delims==" %%A in ('python "%PROJECT_ROOT%scripts\launcher_helper.py" check-ports') do (
    if "%%A"=="BACKEND_STATUS" set "BACKEND_STATUS=%%B"
    if "%%A"=="FRONTEND_STATUS" set "FRONTEND_STATUS=%%B"
)

if "%BACKEND_STATUS%"=="CONFLICT" goto :err_port_5000
if "%FRONTEND_STATUS%"=="CONFLICT" goto :err_port_5173

echo   - Port 5000 (Backend API): %BACKEND_STATUS%
echo   - Port 5173 (Frontend UI): %FRONTEND_STATUS%
echo.

:: ----------------------------------------------------------------------------
:: 3. Launch Services in Dedicated Windows
:: ----------------------------------------------------------------------------
echo [3/4] Starting application services...

if "%BACKEND_STATUS%"=="ALREADY_RUNNING" (
    echo   [INFO] Backend is already running and healthy at http://127.0.0.1:5000
) else (
    echo   [LAUNCH] Starting Flask Backend API in separate terminal window...
    start "TrafficShield - Backend (Flask API)" "%PROJECT_ROOT%scripts\run_backend.bat"
)

if "%FRONTEND_STATUS%"=="ALREADY_RUNNING" (
    echo   [INFO] Frontend is already running and accessible at http://localhost:5173
) else (
    echo   [LAUNCH] Starting React+Vite Frontend in separate terminal window...
    start "TrafficShield - Frontend (Vite UI)" "%PROJECT_ROOT%scripts\run_frontend.bat"
)
echo.

:: ----------------------------------------------------------------------------
:: 4. Await Readiness & Open Browser
:: ----------------------------------------------------------------------------
echo [4/4] Awaiting service readiness (timeout: 60s)...

python "%PROJECT_ROOT%scripts\launcher_helper.py" wait-ready --timeout 60
set "WAIT_CODE=%errorlevel%"

echo.
if %WAIT_CODE% equ 0 goto :launch_success
if %WAIT_CODE% equ 1 goto :err_timeout_backend
if %WAIT_CODE% equ 2 goto :err_timeout_frontend
goto :err_timeout_both

:launch_success
echo ============================================================================
echo   [SUCCESS] TrafficShield services are ONLINE and READY!
echo ============================================================================
echo   Backend API:   http://127.0.0.1:5000/api/v1
echo   API Health:    http://127.0.0.1:5000/api/v1/health
echo   Frontend UI:   http://localhost:5173/
echo.
echo   Default development login credentials:
echo     Username: admin       Password: AdminPass123^^!
echo     Username: analyst     Password: AnalystPass123^^!
echo ============================================================================
echo.
echo Opening TrafficShield in your default browser...
start "" "http://localhost:5173/"
echo.
echo Services are running in their respective terminal windows.
echo To stop TrafficShield: Close the Backend and Frontend windows, or press Ctrl+C in each.
echo.
echo Launcher will close in 5 seconds.
ping -n 6 127.0.0.1 >nul
exit /b 0

:: ----------------------------------------------------------------------------
:: Error Handlers
:: ----------------------------------------------------------------------------
:err_no_python
echo [ERROR] Python interpreter not found in PATH.
echo Please install Python 3.12+ (AMD64) and ensure it is added to your PATH.
goto :error_exit

:err_no_node
echo [ERROR] Node.js not found in PATH.
echo Please install Node.js (v18+) from https://nodejs.org/
goto :error_exit

:err_no_npm
echo [ERROR] npm was not found in PATH.
echo Please ensure Node.js and npm are properly installed.
goto :error_exit

:err_no_run
echo [ERROR] Backend entry point run.py is missing from:
echo   %PROJECT_ROOT%
goto :error_exit

:err_no_pkg
echo [ERROR] Frontend package.json is missing from:
echo   %PROJECT_ROOT%frontend\
goto :error_exit

:err_no_modules
echo [ERROR] Frontend dependencies not found in frontend\node_modules.
echo Action required: Please install frontend dependencies first:
echo   cd frontend
echo   npm install
goto :error_exit

:err_no_helper
echo [ERROR] Launcher helper utility is missing from:
echo   %PROJECT_ROOT%scripts\launcher_helper.py
goto :error_exit

:err_no_backend_bat
echo [ERROR] Backend launcher script is missing from:
echo   %PROJECT_ROOT%scripts\run_backend.bat
goto :error_exit

:err_no_frontend_bat
echo [ERROR] Frontend launcher script is missing from:
echo   %PROJECT_ROOT%scripts\run_frontend.bat
goto :error_exit

:err_port_5000
echo [ERROR] Port 5000 is occupied by an unrelated or non-responsive process.
echo Action required: Free port 5000 before starting TrafficShield.
echo Inspect with: netstat -ano ^| findstr :5000
goto :error_exit

:err_port_5173
echo [ERROR] Port 5173 is occupied by an unrelated or non-responsive process.
echo Action required: Free port 5173 before starting TrafficShield.
echo Inspect with: netstat -ano ^| findstr :5173
goto :error_exit

:err_timeout_backend
echo [ERROR] Backend service failed to become ready at http://127.0.0.1:5000/api/v1/health within 60s.
echo Troubleshooting:
echo   1. Check the 'TrafficShield - Backend (Flask API)' terminal window for errors.
echo   2. Verify Python dependencies: pip install -r requirements.txt
echo   3. Test manual startup: python run.py
goto :error_exit

:err_timeout_frontend
echo [ERROR] Frontend service failed to become ready at http://localhost:5173 within 60s.
echo Troubleshooting:
echo   1. Check the 'TrafficShield - Frontend (Vite UI)' terminal window for errors.
echo   2. Verify frontend dependencies: cd frontend ^& npm install
echo   3. Test manual startup: cd frontend ^& npm run dev
goto :error_exit

:err_timeout_both
echo [ERROR] Both Backend and Frontend services failed to become ready within 60s.
echo Troubleshooting:
echo   1. Inspect both terminal windows for startup errors.
echo   2. Check if ports 5000 or 5173 are blocked by host security software.
goto :error_exit

:error_exit
echo.
echo ============================================================================
echo   Startup could not be completed. Please review the errors above.
echo ============================================================================
echo.
echo Press any key to exit...
pause >nul
exit /b 1
