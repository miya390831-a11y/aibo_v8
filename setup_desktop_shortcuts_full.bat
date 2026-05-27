@echo off
chcp 65001 > nul
title AIBO · デスクトップアイコン整備

echo.
echo  ============================================
echo   AIBO デスクトップアイコン整備
echo  ============================================
echo.
echo   作成するショートカット:
echo     1. AIBO Cyber Studio (現行 · 既存があれば上書き)
echo     2. AIBO Claude Code
echo     3. AIBO Colab
echo.
echo  ============================================
echo.

REM PowerShell でショートカットを作成
powershell -ExecutionPolicy Bypass -File "%~dp0setup_desktop_shortcuts_full.ps1"

echo.
echo  ============================================
echo   [OK] デスクトップアイコン作成完了
echo  ============================================
echo.
pause
