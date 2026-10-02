@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\bootstrap.py
) else (
  py -3 tools\bootstrap.py
)
if errorlevel 1 pause
