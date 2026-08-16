@echo off

cd /d D:\AI\alarm_system

call .venv\Scripts\activate.bat

python -m uvicorn alarm_list:app --host 0.0.0.0 --port 1865

