@echo off
title Bot Santander - Instalacao
cd /d "%~dp0"

echo Procurando Python...
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo Python nao encontrado. Instale o Python 3.12 em python.org
    echo e marque "Add python.exe to PATH" na primeira tela.
    echo.
    pause
    exit /b 1
)

if exist "venv_win\pyvenv.cfg" (
    echo Removendo venv antigo ^(aponta para outro PC^)...
    rmdir /s /q venv_win
)

echo Criando ambiente...
python -m venv venv_win
if errorlevel 1 goto erro

echo Instalando dependencias...
venv_win\Scripts\python.exe -m pip install --upgrade pip
venv_win\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto erro

echo Instalando driver do navegador...
venv_win\Scripts\python.exe -m playwright install chromium

echo.
echo Pronto. Use "Iniciar Bot.vbs" para rodar.
echo.
pause
exit /b 0

:erro
echo.
echo Falhou. Rode de novo ou mande o texto acima.
echo.
pause
exit /b 1
