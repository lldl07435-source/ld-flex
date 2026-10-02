@echo off
chcp 65001 >nul
cd /d "%~dp0"
"%~dp0.venv\Scripts\python.exe" -X utf8 manage.py test portal
if errorlevel 1 goto end
"%~dp0.venv\Scripts\python.exe" -X utf8 账户实际验收.py
:end
pause
