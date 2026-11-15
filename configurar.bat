@echo off
setlocal
where python >nul 2>&1
if errorlevel 1 goto sem_python
python "%~dp0scripts\configure.py"
exit /b %errorlevel%

:sem_python
echo Python 3 nao encontrado. Instale-o marcando "Add Python to PATH".
pause
exit /b 1
