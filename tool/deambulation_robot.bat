@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM ============================================================
REM   Depose deambulation.py sur le robot et lance son service.
REM   Le capteur ToF n'existe que sur ROS, a bord : sans ce
REM   service, l'onglet Deambulation reste vide (c'est normal).
REM   Projet independant explorations360, sans lien avec Hengbot.
REM ============================================================

set VER=?
if exist VERSION.txt set /p VER=<VERSION.txt
title Studio 360 v%VER% - service de deambulation

REM --- Adresse du robot : argument, sinon on la demande ---
set IP=%1
if "%IP%"=="" (
  set /p IP=  Adresse IP du robot (ex. 192.168.1.42) :
)
if "%IP%"=="" (
  echo   [X] Aucune adresse saisie.
  pause
  exit /b 1
)

set USER=root

echo.
echo   ==========================================
echo      Service de deambulation - robot %IP%
echo   ==========================================
echo.

where scp >nul 2>&1
if errorlevel 1 (
  echo   [X] scp introuvable. Installe OpenSSH :
  echo       Parametres ^> Applications ^> Fonctionnalites facultatives
  echo       ^> Ajouter ^> "Client OpenSSH".
  pause
  exit /b 1
)

if not exist deambulation.py (
  echo   [X] deambulation.py absent de ce dossier.
  pause
  exit /b 1
)

echo   1/2  Copie de deambulation.py vers le robot...
scp deambulation.py %USER%@%IP%:/root/
if errorlevel 1 (
  echo.
  echo   [X] Copie impossible. Verifie que le robot est allume,
  echo       sur le meme reseau, et que SSH est ouvert.
  pause
  exit /b 1
)
echo        Copie faite.
echo.

echo   2/2  Lancement du service a bord (Ctrl+C pour arreter).
echo        La grille ToF va s'animer dans l'onglet Deambulation.
echo        Au lancement le robot NE BOUGE PAS : il observe.
echo.

REM  L'environnement DDS est indispensable, sinon le noeud ne voit aucun topic.
ssh %USER%@%IP% "source /opt/ros/humble/setup.bash && source /root/sirius_ros2/install/setup.bash && export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp && ([ -f /root/cyclonedds.xml ] && export CYCLONEDDS_URI=file:///root/cyclonedds.xml); python3 /root/deambulation.py --service"

echo.
echo   Service arrete.
pause
