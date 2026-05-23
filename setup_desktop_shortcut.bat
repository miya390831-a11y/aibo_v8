@echo off
title AIBO Desktop Shortcut Setup
echo ===========================================
echo   AIBO デスクトップショートカット作成
echo ===========================================
echo.
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0setup_desktop_shortcut.ps1"
echo.
echo 完了しました。デスクトップを確認してください。
pause
