@echo off
rem Probant, all-in-one version: double-click. Close the window to stop the tool.
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0system\libs"
"%~dp0system\python\python.exe" "%~dp0system\launch.py"
pause
