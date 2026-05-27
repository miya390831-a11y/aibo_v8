@echo off
chcp 65001 > nul
title AIBO · 緊急停止

echo.
echo  ============================================
echo   [!] AIBO Claude Code 緊急停止
echo  ============================================
echo.
echo   この操作は以下を実行します:
echo     1. すべての claude プロセスを終了
echo     2. すべての node プロセスを終了 (UI 含む)
echo     3. .py / .md / .json / .bat の緊急バックアップ
echo     4. 現在の Git status を表示
echo.
echo   実行しますか? (Y/N)
set /p confirm=

if /i not "%confirm%"=="Y" (
    echo キャンセルしました
    pause
    exit /b
)

echo.
echo  [1/4] claude / node プロセス終了中...
taskkill /F /IM claude.exe 2>nul
taskkill /F /IM node.exe 2>nul

echo  [2/4] 緊急バックアップ作成中...
cd /d C:\Users\yuuki\aibo_v7
set BACKUP_DIR=C:\Users\yuuki\aibo_v7_emergency_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%
set BACKUP_DIR=%BACKUP_DIR: =0%
mkdir "%BACKUP_DIR%" 2>nul
xcopy "C:\Users\yuuki\aibo_v7\*.py" "%BACKUP_DIR%\" /Y > nul 2>&1
xcopy "C:\Users\yuuki\aibo_v7\*.md" "%BACKUP_DIR%\" /Y > nul 2>&1
xcopy "C:\Users\yuuki\aibo_v7\*.json" "%BACKUP_DIR%\" /Y > nul 2>&1
xcopy "C:\Users\yuuki\aibo_v7\*.bat" "%BACKUP_DIR%\" /Y > nul 2>&1
xcopy "C:\Users\yuuki\aibo_v7\*.ps1" "%BACKUP_DIR%\" /Y > nul 2>&1
echo   バックアップ先: %BACKUP_DIR%

echo  [3/4] Git status 確認...
git status

echo.
echo  [4/4] 直近のコミット履歴...
git log --oneline -5

echo.
echo  ============================================
echo   緊急停止完了
echo  ============================================
echo.
echo   次のステップ:
echo     - git diff で変更内容を確認
echo     - 問題あれば: git checkout . で未コミットを破棄
echo     - 致命的なら: %BACKUP_DIR% から復旧
echo.
pause
