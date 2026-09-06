@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   Math Competition Question Bank - Launcher
echo ============================================
echo.

where python >nul 2>nul
if errorlevel 1 (
    echo [ERROR] Python was not found on this computer.
    echo         Please install Python 3.11 or newer from:
    echo         https://www.python.org/downloads/
    echo         IMPORTANT: tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo [SETUP] Creating virtual environment ...
    python -m venv .venv
    if errorlevel 1 goto :fail
)

set "PY=%CD%\.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo [ERROR] Virtual environment is broken. Delete the .venv folder and retry.
    pause
    exit /b 1
)

if not exist ".venv\.deps_ok" (
    echo [SETUP] Installing dependencies, please wait ...
    "%PY%" -m pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 goto :fail
    echo ok> ".venv\.deps_ok"
)

echo [SETUP] Preparing database ...
"%PY%" manage.py migrate --noinput
if errorlevel 1 goto :fail

echo.
echo   Site is starting up ...
echo   Open in browser:  http://127.0.0.1:8000/papers/
echo   Admin panel:      http://127.0.0.1:8000/admin/
echo   Stop the site:    close this window, or press Ctrl+C
echo.
start "" "http://127.0.0.1:8000/papers/"
"%PY%" manage.py runserver 127.0.0.1:8000
goto :eof

:fail
echo.
echo [ERROR] Setup failed. Please screenshot the messages above and send them back.
pause
exit /b 1
