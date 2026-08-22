@echo off
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo ERRO: Python nao encontrado.
    echo.
    echo Baixe em https://python.org e, durante a instalacao,
    echo MARQUE a caixinha "Add Python to PATH".
    echo.
    pause
    exit /b 1
)

if not exist config.ini (
    echo Ainda nao configurado. Rodando o configurador...
    echo.
    call configurar.bat
)

python bot.py %*

echo.
pause
