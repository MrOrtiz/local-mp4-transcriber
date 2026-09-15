@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" scripts\install_resources.py ocr
if errorlevel 1 echo OCR setup failed.
pause
