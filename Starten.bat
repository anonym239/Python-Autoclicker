@echo off
title AutoClicker
cd /d "%~dp0"
python --version >NUL 2>NUL
if not errorlevel 1 (
  python autoclicker.py %*
) else (
  py -3 autoclicker.py %*
)
if errorlevel 1 (
  echo.
  echo Etwas ist schiefgelaufen. Ist Python 3.9+ installiert?
  echo Download: https://www.python.org/downloads/  ^(Haken bei "Add python.exe to PATH"^)
  pause
)
