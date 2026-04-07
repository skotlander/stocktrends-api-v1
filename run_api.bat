@echo off
cd /d %~dp0

REM -----------------------------------------
REM Stock Trends API - Local Development Only
REM -----------------------------------------
REM This script is for LOCAL Windows development.
REM It assumes Python is available in your PATH.
REM It is NOT used in production.

echo Starting Stock Trends API (local dev)...

REM Start API in a new terminal window
start "" cmd /k "python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000"

REM Wait briefly, then open docs
timeout /t 2 > nul
start "" "http://127.0.0.1:8000/v1/docs"

echo API started. Check the new terminal window.
pause