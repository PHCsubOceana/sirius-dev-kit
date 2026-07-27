@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM --- Version : lue dans VERSION.txt, source unique du paquet ---
set VER=?
if exist VERSION.txt set /p VER=<VERSION.txt
title Studio 360 v%VER% - mode telephone (reseau)

echo.
echo   ==========================================
echo      STUDIO 360 v%VER% - MODE TELEPHONE
echo   ==========================================
echo.
echo   [!] Ce mode rend l'interface accessible depuis le Wi-Fi :
echo       ton telephone, mais AUSSI tout autre appareil du reseau.
echo       Le pilotage du robot n'est PAS protege par mot de passe.
echo       A n'utiliser que sur un reseau de confiance (ton Wi-Fi perso).
echo.
echo   Sur un reseau public ou partage : ferme cette fenetre et utilise
echo   plutot demarrer.bat (mode PC uniquement).
echo.
pause

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

echo   Demarrage en mode reseau...
echo   Repere la ligne "a ouvrir sur le telephone" ci-dessous : c'est
echo   l'adresse a taper dans le navigateur du telephone (meme Wi-Fi).
echo   L'adresse du robot, elle, se saisit DANS l'interface.
echo.
echo   Ferme cette fenetre pour tout arreter.
echo.

%PY% sirius_helper.py --host 0.0.0.0

echo.
echo   Studio 360 est arrete.
pause
