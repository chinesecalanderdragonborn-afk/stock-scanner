@echo off
REM Double-click this file to launch Pi Search on Windows.
cd /d "%~dp0"
echo Starting Pi Search...
python start.py
if errorlevel 1 (
  echo.
  echo Something went wrong. Trying 'py' instead of 'python'...
  py start.py
)
echo.
echo The server has stopped. You can close this window.
pause
