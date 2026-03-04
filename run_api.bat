@echo off
cd /d %~dp0

REM Start API
start "" C:\anaconda3\envs\st_api\python.exe -m uvicorn main:app --reload --host 127.0.0.1 --port 8000

REM Wait 2 seconds, then open browser
timeout /t 2 > nul
start "" "http://127.0.0.1:8000/v1/docs"

pause