@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
  echo Run setup.cmd first.
  pause
  exit /b 1
)
start "Course Transcriber" ".venv\Scripts\pythonw.exe" -m course_transcriber
