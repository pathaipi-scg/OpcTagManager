@echo off
setlocal
cd /d "%~dp0"
set "OPCTAGMANAGER_ENV_FILE=%~dp0config\.env.sb12"
if not exist "%OPCTAGMANAGER_ENV_FILE%" (
    echo Missing environment profile: %OPCTAGMANAGER_ENV_FILE%
    exit /b 1
)
if exist "%~dp0.venv\Scripts\python.exe" (
    "%~dp0.venv\Scripts\python.exe" "%~dp0OpcTagManager.py"
) else (
    python "%~dp0OpcTagManager.py"
)
exit /b %errorlevel%
