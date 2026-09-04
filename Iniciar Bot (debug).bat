@echo off
title Bot Santander
cd /d "%~dp0"
echo Iniciando Bot Santander...
if exist "venv_win\Scripts\python.exe" (
    venv_win\Scripts\python.exe gui.py
) else (
    python gui.py
)
pause
