@echo off
cd /d "%~dp0"
echo ===================================================================
echo   ATLAS NEURAL CORE // BACKEND SERVICE
echo   Starting on http://127.0.0.1:8000...
echo ===================================================================
backend\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --reload --port 8000
pause
