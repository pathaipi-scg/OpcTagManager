@echo off

cd /d "%~dp0"

call .venv\Scripts\activate.bat

python -m uvicorn OpcTagManager:app --host 0.0.0.0 --port 1865

