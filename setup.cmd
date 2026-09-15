@echo off
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if errorlevel 1 (
  echo Setup failed. Read the error above.
  pause
  exit /b 1
)
echo Setup complete. Open launch.cmd.
pause
