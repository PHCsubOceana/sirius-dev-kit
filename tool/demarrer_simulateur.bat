@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM --- Version : lue dans VERSION.txt, source unique du paquet ---
set VER=?
if exist VERSION.txt set /p VER=<VERSION.txt
title Studio 360 v%VER% - simulateur

echo.
echo   ==========================================
echo      STUDIO 360 v%VER% - mode SIMULATEUR
echo      (aucun robot necessaire, aucun risque)
echo   ==========================================
echo.

where python >nul 2>&1
if errorlevel 1 ( set PY=py ) else ( set PY=python )

%PY% -c "import fastapi, uvicorn, websockets, httpx" >nul 2>&1
if errorlevel 1 (
  echo   Installation des dependances...
  %PY% -m pip install --quiet --disable-pip-version-check fastapi uvicorn websockets httpx
)

echo   Demarrage du robot simule...
start "Robot simule" /min %PY% mock_robot.py
timeout /t 3 /nobreak >nul

echo   Demarrage de l'interface...
echo   Dans l'interface, connecte-toi a l'adresse  127.0.0.1
echo   Ferme cette fenetre pour tout arreter.
echo.
%PY% sirius_helper.py

echo.
echo   Arret. Fermeture du robot simule...
taskkill /f /fi "WINDOWTITLE eq Robot simule*" >nul 2>&1
pause
