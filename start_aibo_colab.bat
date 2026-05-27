@echo off
chcp 65001 > nul
title AIBO · Colab Notebook

echo.
echo  ============================================
echo   AIBO Cyber Studio · Colab 起動中
echo  ============================================
echo.

REM Colab Notebook URL (GitHub ホスト · master 追随)
set COLAB_URL=https://colab.research.google.com/github/miya390831-a11y/aibo_v8/blob/master/aibo_v7_colab.ipynb#scrollTo=filKR6AT6JR3

REM URL がデフォルト値のままなら警告
echo %COLAB_URL% | findstr /C:"PASTE_YOUR_NOTEBOOK_ID_HERE" > nul
if not errorlevel 1 (
    echo  ============================================
    echo   [WARN] COLAB_URL が未設定です
    echo  ============================================
    echo.
    echo   start_aibo_colab.bat の COLAB_URL を
    echo   実際の AIBO Notebook URL に変更してください
    echo.
    echo   例:
    echo   set COLAB_URL=https://colab.research.google.com/drive/abc123...
    echo.
    echo  ============================================
    pause
    exit /b 1
)

REM Chrome で Colab を開く
echo  Colab を Chrome で起動中...
start chrome "%COLAB_URL%"

REM 起動完了
echo.
echo  ============================================
echo   [OK] AIBO Colab を起動しました
echo  ============================================
echo.
echo   次のステップ:
echo     1. Colab で ランタイム → 接続 → A100
echo     2. Cell 0 を実行 (起動時間 80-130 秒)
echo     3. ngrok URL が表示されたら完了
echo.
echo   このウィンドウは閉じて OK です
echo.
timeout /t 5 /nobreak > nul
