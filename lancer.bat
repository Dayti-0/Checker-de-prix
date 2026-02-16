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

REM Activer l'environnement virtuel
call venv\Scripts\activate.bat

REM Installer les dependances
echo [2/4] Installation des dependances...
pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo [ERREUR] Echec de l'installation des dependances.
    pause
    exit /b 1
)

REM Installer le navigateur Playwright
echo [3/4] Installation du navigateur Playwright (Chromium)...
playwright install chromium --quiet 2>nul
if errorlevel 1 (
    python -m playwright install chromium
)

REM Lancer l'application
echo [4/4] Demarrage du serveur...
echo.
echo   L'application est accessible sur : http://localhost:8000
echo   Appuyez sur Ctrl+C pour arreter le serveur.
echo.

python -m backend.main
pause
