@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM --- Version : lue dans VERSION.txt, source unique du paquet ---
set VER=?
if exist VERSION.txt set /p VER=<VERSION.txt
title Studio 360 v%VER%

echo.
echo   ==========================================
echo      STUDIO 360 v%VER% - pour Hengbot Sirius
echo      projet independant, sans lien avec Hengbot
echo   ==========================================
echo.

REM --- Python present ? ---
where python >nul 2>&1
if errorlevel 1 (
  where py >nul 2>&1
  if errorlevel 1 (
    echo   [X] Python introuvable.
    echo       Installe-le depuis https://www.python.org/downloads/
    echo       IMPORTANT : coche "Add Python to PATH" pendant l'installation.
    echo.
    pause
    exit /b 1
  )
  set PY=py
) else (
  set PY=python
)

REM --- Dependances (installation silencieuse, une seule fois) ---
%PY% -c "import fastapi, uvicorn, websockets, httpx" >nul 2>&1
if errorlevel 1 (
  echo   Premiere utilisation : installation des dependances...
  %PY% -m pip install --quiet --disable-pip-version-check fastapi uvicorn websockets httpx
  if errorlevel 1 (
    echo   [X] L'installation a echoue. Verifie ta connexion internet.
    pause
    exit /b 1
  )
  echo   Dependances installees.
  echo.
)

echo   Demarrage... l'interface va s'ouvrir dans ton navigateur.
echo   L'adresse du robot se saisit DANS l'interface.
echo.
echo   Ferme cette fenetre pour tout arreter.
echo.

%PY% sirius_helper.py

echo.
echo   Studio 360 est arrete.
pause
