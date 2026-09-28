@echo off
REM Maximo Delivery AI Suite - start the web control surface.
cd /d "%~dp0"
echo Checking readiness...
python run.py doctor
if errorlevel 1 (
  echo.
  echo Readiness check failed. Fix the items above, then run this again.
  pause
  exit /b 1
)
echo.
echo Starting the control surface...
start "" http://127.0.0.1:8800
python run.py ui
