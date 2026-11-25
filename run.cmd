@echo off
rem Menu di demogen: doppio click, oppure "run.cmd -Action processi" (vedi run.ps1)
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0run.ps1" %*
