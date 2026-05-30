@echo off
REM ============================================================
REM  実装検証統括くろうど(タブ2)起動
REM  役割憲章を system prompt に追記して「統括」として起動する。
REM  共通ルールはルート CLAUDE.md が自動で読まれる。
REM ============================================================
setlocal
set "AIBO_REPO=C:\Users\yuuki\aibo_v7"
set "CHARTER=.claude\agents\lead-verify-kuroudo.md"
set "KICKOFF=君は実装検証統括くろうど。司令部(対話)からの指示書を待つ役。指示書(docs\directives\ の .md を @ で参照、または貼り付け)を受けたら、実装くろうど/エラー修正くろうどを使って遂行し、完了条件を検証して logs\report_*.md に報告する。戦略は決めない。まず repo の現状を把握して待機。"

cd /d "%AIBO_REPO%"

REM --- 推奨: --append-system-prompt-file が使えるバージョンならこれ(最もシンプル)---
REM claude --append-system-prompt-file "%CHARTER%" --permission-mode acceptEdits "%KICKOFF%"

REM --- 互換: 上が無いバージョン向け。PowerShell で憲章を読み込んで追記 ---
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = Get-Content -Raw -Encoding UTF8 '%CHARTER%'; claude --append-system-prompt $c --permission-mode acceptEdits '%KICKOFF%'"

echo.
echo [統括] セッション終了。
pause
endlocal
