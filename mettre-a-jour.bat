@echo off
rem Mise a jour de PrixMalin, puis relance.
rem   - dossier venu de git (.git present) : git pull --ff-only ;
rem   - sinon : derniere version publiee sur GitHub (PrixMalin-x.y.z.zip),
rem     extraite par-dessus ; venv et les donnees ne sont jamais touches.
rem Ce fichier se copie d'abord dans %TEMP% : la mise a jour peut le remplacer.
rem CRLF et sans accents (voir .gitattributes).
setlocal EnableExtensions DisableDelayedExpansion
if /i "%~1"=="/copie" goto :run
set "PRIXMALIN_APP=%~dp0"
copy /y "%~f0" "%TEMP%\prixmalin-mise-a-jour.bat" >nul 2>&1
if errorlevel 1 goto :run
"%TEMP%\prixmalin-mise-a-jour.bat" /copie

:run
cd /d "%PRIXMALIN_APP%"
chcp 65001 >nul 2>&1
title PrixMalin - Mise a jour
if not defined PRIXMALIN_PORT set "PRIXMALIN_PORT=8000"

echo ========================================
echo   PrixMalin - Mise a jour
echo ========================================
echo.

rem PrixMalin doit etre ferme : ses fichiers vont etre remplaces
powershell -NoProfile -Command "$c = New-Object Net.Sockets.TcpClient; try { $c.Connect('127.0.0.1', [int]$env:PRIXMALIN_PORT); exit 1 } catch { exit 0 } finally { $c.Close() }"
if errorlevel 1 goto :running

if exist ".git" goto :git
goto :zip

:git
where git >nul 2>&1
if errorlevel 1 goto :no_git
echo Mise a jour avec git...
git pull --ff-only
if errorlevel 1 goto :git_failed
goto :restart

:zip
echo Telechargement de la derniere version de PrixMalin...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference = 'Stop'; [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; $app = $env:PRIXMALIN_APP.TrimEnd('\'); $headers = @{ 'User-Agent' = 'PrixMalin' }; try { $release = Invoke-RestMethod -UseBasicParsing -Headers $headers -Uri 'https://api.github.com/repos/Dayti-0/Checker-de-prix/releases/latest' } catch { $status = 0; if ($_.Exception.Response) { $status = [int]$_.Exception.Response.StatusCode }; if ($status -eq 404) { Write-Host '  Aucune version publiee pour l''instant : rien a mettre a jour.'; exit 2 }; throw }; $asset = $release.assets | Where-Object { $_.name -like 'PrixMalin-*.zip' } | Select-Object -First 1; if (-not $asset) { Write-Host ('  La version ' + $release.tag_name + ' n''a pas de fichier PrixMalin-*.zip : rien a mettre a jour.'); exit 2 }; $tmp = Join-Path $env:TEMP ('prixmalin-maj-' + [Guid]::NewGuid().ToString('N')); New-Item -ItemType Directory -Path $tmp | Out-Null; try { $zip = Join-Path $tmp 'prixmalin.zip'; Write-Host ('  Version ' + $release.tag_name + '...'); Invoke-WebRequest -UseBasicParsing -Headers $headers -Uri $asset.browser_download_url -OutFile $zip; $out = Join-Path $tmp 'x'; Expand-Archive -LiteralPath $zip -DestinationPath $out; $src = $out; if (-not (Test-Path -LiteralPath (Join-Path $src 'lancer.bat'))) { $inner = @(Get-ChildItem -LiteralPath $src -Directory); if ($inner.Count -eq 1) { $src = $inner[0].FullName } }; if (-not (Test-Path -LiteralPath (Join-Path $src 'backend\main.py'))) { throw 'archive inattendue' }; foreach ($dir in Get-ChildItem -LiteralPath $src -Directory) { if (@('venv', 'data', '.git') -contains $dir.Name) { continue }; & robocopy $dir.FullName (Join-Path $app $dir.Name) /MIR /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null; if ($LASTEXITCODE -ge 8) { throw ('copie impossible : ' + $dir.Name) } }; & robocopy $src $app /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null; if ($LASTEXITCODE -ge 8) { throw 'copie impossible' }; Write-Host ('  PrixMalin ' + $release.tag_name + ' installe.') } finally { Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue }"
if errorlevel 2 goto :nothing_new
if errorlevel 1 goto :zip_failed
goto :restart

:nothing_new
echo.
echo Rien a mettre a jour : PrixMalin redemarre.
echo.
call "%PRIXMALIN_APP%lancer.bat"
exit /b %ERRORLEVEL%

:restart
echo.
echo Mise a jour terminee : PrixMalin redemarre.
echo.
call "%PRIXMALIN_APP%lancer.bat"
exit /b %ERRORLEVEL%

:running
echo [ATTENTION] PrixMalin est ouvert : fermez sa fenetre noire, puis relancez mettre-a-jour.bat.
pause
exit /b 1

:no_git
echo [ERREUR] Ce dossier vient de git, mais git est introuvable.
echo   Installez Git pour Windows (https://git-scm.com/download/win), ou telechargez
echo   la derniere version sur https://github.com/Dayti-0/Checker-de-prix/releases
pause
exit /b 1

:git_failed
echo [ERREUR] git pull a echoue : des fichiers ont peut-etre ete modifies a la main.
echo   Rien n'a ete change. Demandez de l'aide avec le message ci-dessus.
pause
exit /b 1

:zip_failed
echo [ERREUR] La mise a jour n'a pas pu etre telechargee ou installee.
echo   Verifiez la connexion a Internet, puis relancez mettre-a-jour.bat.
echo   Vos donnees ne sont pas touchees.
pause
exit /b 1
