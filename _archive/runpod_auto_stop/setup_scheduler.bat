@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion

set "SCRIPT_DIR=%~dp0"
rem 末尾の \ を削除
if "%SCRIPT_DIR:~-1%"=="\" set "SCRIPT_DIR=%SCRIPT_DIR:~0,-1%"

where pythonw >nul 2>&1
if errorlevel 1 (
  echo [ERROR] pythonw が PATH に見つかりません。Python 3 をインストールするか PATH に追加してください。
  exit /b 1
)

for /f "delims=" %%I in ('where pythonw') do (
  set "PYTHONW=%%I"
  goto :HAVE_PY
)
:HAVE_PY

set "TASK_NAME=AIBO_RunPod_AutoStop"

echo [INFO] PYTHONW=%PYTHONW%
echo [INFO] SCRIPT_DIR=%SCRIPT_DIR%
echo [INFO] タスク名: %TASK_NAME% （5分ごと）
echo.
echo [重要] ユーザー環境変数 RUNPOD_API_KEY を設定してください（setx または システムの環境変数）。
echo.
schtasks /Create /F /TN "%TASK_NAME%" /TR "\"%PYTHONW%\" \"%SCRIPT_DIR%\check_last_access.py\"" /SC MINUTE /MO 5 /RL LIMITED

if errorlevel 1 (
  echo [ERROR] schtasks の登録に失敗しました。管理者権限が必要な場合は PowerShell を管理者で開いて再実行してください。
  exit /b 1
)

echo.
echo [OK] 登録完了。
echo      削除: schtasks /Delete /TN "%TASK_NAME%" /F
endlocal
exit /b 0
