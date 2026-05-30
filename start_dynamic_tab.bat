@echo off
REM ============================================================
REM  ダイナミックくろうど(特殊部隊)タブ起動
REM  役割憲章を system prompt に注入して別タブで起動する。
REM  共通ルールはルート CLAUDE.md が自動ロードされる。
REM  ※ Dynamic Workflows は Claude Code v2.1.154+ / 有料プラン。Max は既定ON。
REM ============================================================
setlocal
set "AIBO_REPO=C:\Users\yuuki\aibo_v7"
set "CHARTER=.claude\charters\dynamic-kuroudo.md"
set "KICKOFF=君はダイナミックくろうど(特殊部隊)。司令部からの偵察/調査ミッションを待つ。ミッションを受けたら、規模が見合えばワークフローで並列展開し、各発見を独立検証してから docs\research\ または docs\design\ に保存して司令部に報告する。設計の決定はしない(案まで)。繊細な核心部とACE++導入には手を出さない。まず repo 現状を把握して待機。"

cd /d "%AIBO_REPO%"

echo [特殊部隊] 起動。重量級ミッション時は次を実行:
echo     /effort ultracode     (xhigh + ワークフロー自動編成。セッション限り)
echo     auto モード併用を推奨   (数百サブを止めないため。guard フックが最後の砦)
echo     /usage                 (消費確認) / /workflows (走行管理・停止)
echo     通常作業に戻る時は /effort high に落とす
echo.

REM --- 推奨: --append-system-prompt-file が使えるバージョン ---
REM claude --append-system-prompt-file "%CHARTER%" --permission-mode acceptEdits "%KICKOFF%"

REM --- 互換: PowerShell で憲章を読み込んで追記 ---
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$c = Get-Content -Raw -Encoding UTF8 '%CHARTER%'; claude --append-system-prompt $c --permission-mode acceptEdits '%KICKOFF%'"

echo.
echo [特殊部隊] セッション終了。
pause
endlocal
