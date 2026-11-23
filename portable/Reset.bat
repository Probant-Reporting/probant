@echo off
rem Back to the starting point (deletes your trials): the tool restores its initial backup, or prepares the demo again.
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0system\libs"
"%~dp0system\python\python.exe" "%~dp0system\launch.py" --reset
pause
