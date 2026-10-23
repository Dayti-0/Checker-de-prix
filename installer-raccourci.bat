@echo off
rem Raccourcis PrixMalin sur le Bureau et dans le menu Demarrer (fenetre reduite).
rem   installer-raccourci.bat               : cree les raccourcis puis attend une touche
rem   installer-raccourci.bat /silencieux   : sans attendre (appele par lancer.bat)
rem L'icone frontend\icons\prixmalin.ico est utilisee si elle existe.
rem Le chemin du dossier passe par une variable d'environnement : espaces et
rem accents y restent intacts (ce fichier ne contient que de l'ASCII).
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "PRIXMALIN_APP=%~dp0"
set "PRIXMALIN_QUIET="
if /i "%~1"=="/silencieux" set "PRIXMALIN_QUIET=1"

powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; $app = $env:PRIXMALIN_APP.TrimEnd('\'); $shell = New-Object -ComObject WScript.Shell; $icon = Join-Path $app 'frontend\icons\prixmalin.ico'; foreach ($dir in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) { $link = $shell.CreateShortcut((Join-Path $dir 'PrixMalin.lnk')); $link.TargetPath = (Join-Path $app 'lancer.bat'); $link.WorkingDirectory = $app; $link.WindowStyle = 7; $link.Description = 'PrixMalin - comparateur de prix'; if (Test-Path -LiteralPath $icon) { $link.IconLocation = $icon + ',0' }; $link.Save() }"
if errorlevel 1 goto :failed

echo   Raccourcis PrixMalin crees sur le Bureau et dans le menu Demarrer.
if not defined PRIXMALIN_QUIET pause
exit /b 0

:failed
echo   [ERREUR] Les raccourcis n'ont pas pu etre crees.
echo   Vous pouvez toujours lancer PrixMalin avec lancer.bat.
if not defined PRIXMALIN_QUIET pause
exit /b 1
