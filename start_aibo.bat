@echo off
title AIBO Cyber Studio Launcher
echo ===========================================
echo   AIBO Cyber Studio 起動中...
echo ===========================================
echo.
cd /d "%~dp0frontend"
echo Starting Next.js dev server...
start "AIBO Frontend" cmd /k "npm run dev"
echo Waiting 5 seconds for server...
timeout /t 5 /nobreak >nul
echo Opening browser...
start http://localhost:3000
echo.
echo Done! UI が開かない場合は手動で http://localhost:3000 にアクセス
timeout /t 3 /nobreak >nul
exit
