@echo off
rem Lanceur de PrixMalin pour Windows.
rem Ce fichier reste en CRLF et sans accents (voir .gitattributes) : cmd.exe
rem lit les fichiers .bat dans la page de code de la console.
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul 2>&1
title PrixMalin - Comparateur de prix
if not defined PRIXMALIN_PORT set "PRIXMALIN_PORT=8000"
set "VPY=venv\Scripts\python.exe"

echo ========================================
echo   PrixMalin - Comparateur de prix
echo ========================================
echo.

rem --- 1. Environnement virtuel : garde s'il marche (Python 3.11 ou plus), sinon recree
if not exist "%VPY%" goto :create_venv
"%VPY%" -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 goto :venv_ok
echo [1/4] L'environnement virtuel ne marche plus : il est recree.
rmdir /s /q "venv"
if exist "venv" goto :venv_locked

:create_venv
call :find_python
if not defined PY goto :no_python
echo [1/4] Creation de l'environnement virtuel avec %PY%...
%PY% -m venv venv
if errorlevel 1 goto :venv_failed
goto :deps

:venv_ok
echo [1/4] Environnement virtuel pret.

rem --- 2. Dependances : installees seulement si requirements.txt a change (empreinte SHA256)
:deps
"%VPY%" -c "import fastapi, playwright, uvicorn" >nul 2>&1
if errorlevel 1 del /q "venv\.prixmalin-req" >nul 2>&1
"%VPY%" -c "import hashlib, pathlib, sys; h = hashlib.sha256(pathlib.Path('requirements.txt').read_bytes()).hexdigest(); m = pathlib.Path('venv/.prixmalin-req'); sys.exit(0 if m.is_file() and m.read_text().strip() == h else 1)"
if not errorlevel 1 goto :deps_ok
echo [2/4] Installation des dependances (quelques minutes la premiere fois)...
"%VPY%" -m pip install --disable-pip-version-check -r requirements.txt
if errorlevel 1 goto :pip_failed
"%VPY%" -c "import hashlib, pathlib; pathlib.Path('venv/.prixmalin-req').write_text(hashlib.sha256(pathlib.Path('requirements.txt').read_bytes()).hexdigest())"
rem Nouvelle version de Playwright : le navigateur est verifie de nouveau
del /q "venv\.prixmalin-navigateur" >nul 2>&1
goto :browser

:deps_ok
echo [2/4] Dependances a jour.

rem --- 3. Navigateur : Chrome ou Edge suffisent, Chromium n'est telecharge que si aucun ne demarre
:browser
if exist "venv\.prixmalin-navigateur" goto :browser_ok
echo [3/4] Verification du navigateur...
"%VPY%" -m backend.browser_check --install --marker "venv\.prixmalin-navigateur"
if errorlevel 1 echo [ATTENTION] Aucun navigateur ne demarre : installez Google Chrome, puis relancez PrixMalin.
goto :shortcut

:browser_ok
echo [3/4] Navigateur pret.

rem --- 4. Raccourci sur le Bureau, propose une seule fois
:shortcut
if exist "venv\.prixmalin-raccourci" goto :start
echo.
choice /c ON /n /m "Creer un raccourci PrixMalin sur le Bureau ? (O/N) "
if errorlevel 2 goto :no_shortcut
if errorlevel 1 call "%~dp0installer-raccourci.bat" /silencieux
:no_shortcut
echo.>"venv\.prixmalin-raccourci"

:start
echo [4/4] Demarrage de PrixMalin...
echo   La page s'ouvre dans votre navigateur des que PrixMalin est pret.
echo.
rem Le navigateur est ouvert par PrixMalin quand le serveur ecoute
set "PRIXMALIN_OPEN_BROWSER=1"
"%VPY%" -m backend.main
set "CODE=%ERRORLEVEL%"
if "%CODE%"=="0" exit /b 0
echo.
echo   PrixMalin s'est arrete sur une erreur. Le journal prixmalin.log est dans le
echo   dossier logs des donnees de PrixMalin, en general %LOCALAPPDATA%\PrixMalin\logs
pause
exit /b %CODE%

rem ------------------------------------------------------------------------
:find_python
rem Python 3.11 ou plus : py -3.13, -3.12, -3.11, -3, puis python
set "PY="
for %%V in (3.13 3.12 3.11 3) do if not defined PY call :try_python py -%%V
if not defined PY call :try_python python
exit /b 0

:try_python
%* -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if not errorlevel 1 set "PY=%*"
exit /b 0

:no_python
echo [ERREUR] Python 3.11 ou plus est introuvable.
echo   Installez Python depuis https://www.python.org/downloads/
echo   Pendant l'installation, cochez bien la case "Add python.exe to PATH",
echo   puis relancez lancer.bat.
pause
exit /b 1

:venv_locked
echo [ERREUR] Le dossier venv n'a pas pu etre supprime : PrixMalin est peut-etre encore ouvert.
echo   Fermez les autres fenetres de PrixMalin, puis relancez lancer.bat.
pause
exit /b 1

:venv_failed
echo [ERREUR] Impossible de creer l'environnement virtuel.
pause
exit /b 1

:pip_failed
echo [ERREUR] Echec de l'installation des dependances.
echo   Verifiez la connexion a Internet, puis relancez lancer.bat.
pause
exit /b 1
