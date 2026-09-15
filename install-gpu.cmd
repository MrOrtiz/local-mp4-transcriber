@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\install_resources.py gpu
if errorlevel 1 echo GPU runtime setup failed. CPU mode remains available.
pause
