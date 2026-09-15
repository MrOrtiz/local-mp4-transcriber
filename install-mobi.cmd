@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\install_resources.py mobi
if errorlevel 1 echo MOBI setup failed. See README for standard Calibre installation.
pause
