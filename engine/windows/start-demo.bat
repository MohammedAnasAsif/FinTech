@echo off
REM Fake market at high speed: try the app without an Angel One account.
cd /d "%~dp0"
tradebot-engine.exe demo --speed 60
pause
