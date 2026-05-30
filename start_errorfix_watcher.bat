@echo off
REM ============================================================
REM  AIBO 実装検証チーム / エラー修正くろうど 常駐ウォッチャー
REM  デスクトップアイコン 🔬 から起動する想定
REM ============================================================
setlocal

REM --- 環境に合わせて変更 ---
set "AIBO_REPO=C:\Users\yuuki\aibo_v7"
set "CLAUDE_BIN=claude"

cd /d "%AIBO_REPO%"
echo [errorfix] watcher 起動: %AIBO_REPO%
echo [errorfix] 停止は Ctrl+C
python "%AIBO_REPO%\.errorfix\watch_errorfix.py"

echo.
echo [errorfix] watcher が終了しました。
pause
endlocal
