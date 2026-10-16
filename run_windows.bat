@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python was not found. Install Python 3.10 or newer from https://www.python.org/downloads/windows/
  echo Enable "Add Python to PATH" during installation.
  pause
  exit /b 1
)
py -3 EnerBridge.py
if errorlevel 1 (
  echo.
  echo EnerBridge closed with an error. Review the message above.
  pause
)
