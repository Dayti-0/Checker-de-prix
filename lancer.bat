@echo off
chcp 65001 >nul 2>&1
title PrixMalin - Comparateur de prix

echo ========================================
echo   PrixMalin - Comparateur de prix
echo ========================================
echo.

REM Verifier que Python est installe
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERREUR] Python n'est pas installe ou n'est pas dans le PATH.
    echo Telechargez Python sur https://www.python.org/downloads/
    pause
    exit /b 1
)

REM Creer l'environnement virtuel s'il n'existe pas
if not exist "venv" (
    echo [1/4] Creation de l'environnement virtuel...
    python -m venv venv
    if errorlevel 1 (
        echo [ERREUR] Impossible de creer l'environnement virtuel.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Environnement virtuel existant detecte.
)

call venv\Scripts\activate.bat

echo [2/4] Installation des dependances...
python -m pip install --upgrade -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERREUR] Echec de l'installation des dependances.
    pause
    exit /b 1
)

REM Chromium sert de secours si Chrome ou Edge ne sont pas utilisables
echo [3/4] Verification du navigateur Chromium...
python -m playwright install chromium
if errorlevel 1 (
    echo [ATTENTION] Chromium n'a pas pu etre installe. PrixMalin utilisera Chrome ou Edge.
)

echo [4/4] Demarrage de PrixMalin...
echo.
echo   L'application s'ouvre dans votre navigateur : http://localhost:8000
echo   Depuis un telephone sur le meme Wi-Fi : http://ADRESSE-IP-DU-PC:8000
echo   Fermez cette fenetre (ou Ctrl+C) pour arreter PrixMalin.
echo.

start "" cmd /c "timeout /t 4 >nul & start http://localhost:8000"
python -m backend.main
pause
