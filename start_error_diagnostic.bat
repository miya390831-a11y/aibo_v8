@echo off
chcp 65001 > nul
title AIBO · Error Diagnostic Mode

cd /d C:\Users\yuuki\aibo_v7

echo.
echo  ============================================
echo   AIBO Cyber Studio · Error Diagnostic
echo  ============================================
echo.

set ERROR_DIR=G:\マイドライブ\aibo_v7\logs\errors
set LATEST_ERROR=

if not exist "%ERROR_DIR%" (
    echo  ERROR_DIR not found: %ERROR_DIR%
    echo  Drive sync is running? Has AIBO recorded any errors?
    echo.
    pause
    exit /b 1
)

for /f "delims=" %%i in ('dir /b /o-d "%ERROR_DIR%\error_*.json" 2^>nul') do (
    set LATEST_ERROR=%%i
    goto found
)
:found

if "%LATEST_ERROR%"=="" (
    echo  No error files found. AIBO is running normally.
    echo.
    pause
    exit /b 0
)

echo  Latest error: %LATEST_ERROR%
echo.
echo  Launching Claude Code for analysis...
echo  ============================================
echo.

claude -p "G:\マイドライブ\aibo_v7\logs\errors\%LATEST_ERROR% を解析してください。手順: 1. エラーファイルを読む 2. 根本原因を特定 3. 該当 AIBO ソース (01-09_*.py) を読む 4. 修正案を3つ提示 (保守的/標準/積極的) 5. 確信度8以上なら自動修正+4拠点同期+Git push 6. logs/report_diagnostic に記録。厳守: Setting A の7値は変更しない, PHASE3B_ENABLED=True にしない, silent fail 禁止。"

echo.
echo  ============================================
echo   Session complete. Check logs\report_diagnostic_*.md
echo  ============================================
echo.
pause
