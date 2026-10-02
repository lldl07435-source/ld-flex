@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo 请先关闭正在运行的本项目工作台，避免控制库正在使用。
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" tools\verify.py --arm
) else (
  py -3 tools\verify.py --arm
)
pause
