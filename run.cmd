@echo off
rem Menu di demogen (doppio click): lanciatore Node + TypeScript in scripts\run.mts
rem Uso: run.cmd [--action <nome>] [--yes] [--setup]   (oppure: npm run menu)
where node >nul 2>nul || (echo Node.js not found: install it from https://nodejs.org ^(22.18 or newer^) & pause & exit /b 1)
node "%~dp0scripts\run.mts" %*
set code=%errorlevel%
rem con il doppio click la finestra non si chiude su un errore
if not "%code%"=="0" if "%~1"=="" pause
exit /b %code%
