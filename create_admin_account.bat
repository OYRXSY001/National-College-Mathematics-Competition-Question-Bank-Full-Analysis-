@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] Please run start_bank_site.bat once first to complete setup.
    pause
    exit /b 1
)

echo This will create an administrator account.
echo You will pick a username and password next.
echo.
.venv\Scripts\python.exe manage.py createsuperuser

echo.
echo Done. You can now log in at http://127.0.0.1:8000/admin/
pause
