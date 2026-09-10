@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
 echo Please follow README.zh-CN.md to create .venv first.
 pause
 exit /b 1
)
.venv\Scripts\python.exe -m uvicorn artlens.main:app --host 127.0.0.1 --port 8000
pause
