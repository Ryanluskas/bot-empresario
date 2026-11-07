@echo off
title Bot Santander - Instalacao
cd /d "%~dp0"

echo Procurando Python...
set "PY_CMD="

where python >nul 2>&1
if not errorlevel 1 set "PY_CMD=python"

if not defined PY_CMD (
    where py >nul 2>&1
    if not errorlevel 1 set "PY_CMD=py -3.12"
)

if not defined PY_CMD (
    if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
        set "PY_CMD=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
    )
)

if not defined PY_CMD (
    echo.
    echo Python nao encontrado. Instale o Python 3.12 em python.org
    echo e marque "Add python.exe to PATH" na primeira tela.
    echo.
    pause
    exit /b 1
)

echo Python encontrado: %PY_CMD%

if not exist "venv_win\Scripts\python.exe" (
    echo Criando ambiente virtual venv_win...
    %PY_CMD% -m venv venv_win
    if errorlevel 1 goto erro
)

echo Instalando dependencias...
venv_win\Scripts\python.exe -m pip install --upgrade pip
venv_win\Scripts\python.exe -m pip install -r requirements.txt playwright-stealth
if errorlevel 1 goto erro

echo Instalando driver do navegador...
venv_win\Scripts\python.exe -m playwright install chromium

echo.
echo ============================================================
echo  Instalacao concluida com sucesso!
echo  Agora voce pode clicar duas vezes em "Iniciar Bot.vbs".
echo ============================================================
echo.
pause
exit /b 0

:erro
echo.
echo Falhou. Verifique os erros acima e tente novamente.
echo.
pause
exit /b 1
