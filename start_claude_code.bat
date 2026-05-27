@echo off
chcp 65001 > nul
title AIBO · Claude Code CLI [BYPASS MODE]

cd /d C:\Users\yuuki\aibo_v7

echo.
echo  ============================================
echo   AIBO Cyber Studio · Claude Code [BYPASS]
echo  ============================================
echo.
echo   [!] 完全自動モード (承認スキップ)
echo   [*] 危険コマンドは settings.json で deny 済
echo.
echo   作業ディレクトリ: %CD%
echo   モデル:           Opus 4.7
echo   設定ファイル:     %USERPROFILE%\.claude\settings.json
echo.
echo  ============================================
echo   注意:
echo     ファイル編集 / Git / コマンド全て自動承認
echo     暴走を感じたら Ctrl+C で中断
echo     致命的なら emergency_stop.bat (デスクトップ)
echo  ============================================
echo.

REM bypass モード起動 (deny rules は settings.json で定義)
claude --dangerously-skip-permissions

if %errorlevel% neq 0 (
    echo.
    echo  ============================================
    echo   ERROR: Claude Code 起動失敗
    echo  ============================================
    echo.
    echo   対処方法:
    echo     1. 認証確認: claude auth status
    echo     2. 再ログイン: claude auth login
    echo     3. PATH 確認: where claude
    echo.
    pause
)
