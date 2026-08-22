@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo === Configuracao do abecmed-watch ===
echo.

:pedir_cpf
set "cpf="
set /p "cpf=CPF do associado (so numeros): "

rem --- tira tudo que nao for digito
set "limpo="
for /l %%i in (0,1,40) do (
    set "c=!cpf:~%%i,1!"
    if not "!c!"=="" (
        echo !c!| findstr /r "^[0-9]$" >nul && set "limpo=!limpo!!c!"
    )
)
set "cpf=!limpo!"

rem --- confere 11 digitos
set "n=0"
for /l %%i in (0,1,40) do (
    if not "!cpf:~%%i,1!"=="" set /a n+=1
)
if not "!n!"=="11" (
    echo   -^> Precisa ter 11 digitos. Voce digitou !n!.
    echo.
    goto pedir_cpf
)

echo.
echo O topico e o canal onde o app recebe as notificacoes.
echo Deixe em branco para eu sortear um seguro pra voce.
set "topico="
set /p "topico=Topico do ntfy: "

if "!topico!"=="" (
    set "topico=abecmed-!random!!random!"
    echo   -^> Sorteado: !topico!
)

rem --- grava o arquivo
(
    echo # Configuracao do abecmed-watch.
    echo # Gerado por configurar.bat - pode editar na mao se preferir.
    echo # NAO envie este arquivo pro GitHub: ele tem seu CPF.
    echo.
    echo [abecmed]
    echo cpf = !cpf!
    echo topico = !topico!
    echo.
    echo # Intervalo entre verificacoes no modo --loop, em minutos.
    echo # O programa sorteia um valor aleatorio entre os dois a cada ciclo.
    echo intervalo_min = 7
    echo intervalo_max = 12
) > config.ini

echo.
echo Salvo em config.ini
echo.
echo PROXIMO PASSO - no app ntfy do celular:
echo   toque no + e assine exatamente este topico:
echo.
echo       !topico!
echo.
echo Depois rode run.bat para testar.
echo.
pause
