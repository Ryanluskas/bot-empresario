@echo off
title Bot Santander - Instalacao
cd /d "%~dp0"

echo Procurando Python...
set "PY_EXE=python"
set "PY_ARGS="
python -c "import sys" >nul 2>&1
if not errorlevel 1 goto python_encontrado

set "PY_EXE=py"
set "PY_ARGS=-3.12"
py -3.12 -c "import sys" >nul 2>&1
if not errorlevel 1 goto python_encontrado

set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
set "PY_ARGS="
if exist "%PY_EXE%" goto python_encontrado

echo.
echo Python nao encontrado. Instale o Python 3.12 em python.org
echo e marque "Add python.exe to PATH" na primeira tela.
echo.
pause
exit /b 1

:python_encontrado
if not exist "venv_win\Scripts\python.exe" (
    echo Criando ambiente virtual venv_win...
    "%PY_EXE%" %PY_ARGS% -m venv venv_win
    if errorlevel 1 goto erro
)

echo Instalando dependencias...
venv_win\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 goto erro

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
