@echo off
chcp 65001 > nul
title AIBO · Claude Code CLI

cd /d C:\Users\yuuki\aibo_v7

echo.
echo  ============================================
echo   AIBO Cyber Studio · Claude Code CLI 起動
echo  ============================================
echo.
echo   作業ディレクトリ: %CD%
echo   モデル:           Opus 4.7
echo   引継書:           HANDOVER_2026-05-24_v3.md
echo.
echo  ============================================
echo.
echo   起動中... (CLAUDE.md を自動読み込みします)
echo.

REM Claude Code CLI を起動
claude

REM エラー処理: claude コマンドが見つからない場合
if %errorlevel% neq 0 (
    echo.
    echo  ============================================
    echo   ERROR: Claude Code が起動できませんでした
    echo  ============================================
    echo.
    echo   原因の可能性:
    echo     1. Claude Code が未インストール
    echo        → PowerShell で以下を実行:
    echo          irm https://claude.ai/install.ps1 ^| iex
    echo.
    echo     2. PATH が通っていない
    echo        → C:\Users\yuuki\.local\bin が PATH にあるか確認
    echo.
    echo     3. 認証が切れている
    echo        → claude auth login を実行
    echo.
    echo  ============================================
    pause
)
