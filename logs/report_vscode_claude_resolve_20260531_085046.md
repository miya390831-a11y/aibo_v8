# 🛠 完了報告 [vscode_claude_resolve] — 2026-05-31 08:50

VS Code タスクの3分割起動で「特殊部隊」と「エラー修正ウォッチャー(当直)」が
`'claude' が見つからない / CommandNotFoundException` で失敗していた件の診断と修正。

## 1. 何をやったか
- claude の実体を特定し、各起動経路で確実に動く呼び出しに直した。
- 対象は指示どおり `.vscode/tasks.json` と `.errorfix/watch_errorfix.py` の2ファイルのみ。

## 2. 原因(切り分け済み・実測)
claude は `C:\Users\yuuki\AppData\Roaming\npm\` に3種が同居：
- `claude.ps1`(PowerShell の bareword はこれに解決される)
- `claude.cmd`(バッチラッパ／**どの経路でも唯一確実に動く**)
- `claude`(拡張子なし sh スクリプト)

`PATHEXT` に `.PS1` は無い(`.CMD` はある)。実測結果：

| 指定 | subprocess(当直が使う) | 備考 |
|---|---|---|
| bareword `claude` | ❌ WinError 2(ファイル無し) | **当直の現状＝これ。落ちていた直接原因** |
| `claude.ps1` | ❌ WinError 193(Win32 でない) | |
| `claude.cmd`(フルパス) | ✅ rc 0 | 採用 |

- **当直(watcher)**: `CLAUDE_BIN="claude"` を `subprocess.run` に渡していた。Windows の
  CreateProcess は PATHEXT を使わず bareword を解決できず WinError 2 で起動失敗。
- **特殊部隊／統括タスク**: inner の powershell コマンド単体は手元で成功する。失敗は
  VS Code の `type:"shell"` が既定シェル経由でもう一段ラップし、`$c`(多行)＋日本語
  シングルクォート文字列のクォートが崩れて inner が分断 → `claude` が孤立トークン化し
  CommandNotFound になっていた(ワークスペースに terminal profile の上書きは無し)。

## 3. 直し方(適用済み)
- `tasks.json`「統括くろうど」「特殊部隊くろうど」:
  - `"type": "shell"` → `"type": "process"`(二重ラップ／クォート再解釈を排除)
  - `-Command` 内の `claude` 呼び出しを PATH 非依存に:
    `$cc = (Get-Command claude.cmd ...).Source; if(-not $cc){ $cc='...\npm\claude.cmd' }; & $cc ...`
    (claude.cmd を実体解決、取れなければ既知フルパスへフォールバック)
  - 「エラー修正ウォッチャー」(python タスク)は変更不要。
- `watch_errorfix.py` line48:
  `CLAUDE_BIN = os.environ.get("CLAUDE_BIN", r"C:\Users\yuuki\AppData\Roaming\npm\claude.cmd")`
  (環境変数での上書きは温存し、他PC移植時に差し替え可能)

## 4. 結果(検証)
- `tasks.json`: JSON 妥当性 OK。
- `watch_errorfix.py`: `python -m py_compile` OK。
- watcher の新 `CLAUDE_BIN` を実走 → **rc 0 / `2.1.158 (Claude Code)`**。当直が claude を
  呼べる状態に回復したことを確認。
- ※ 3タスクの「VS Code からの実起動」までは未確認(headless で再現困難)。次回フォルダ
  オープン時に3ペインが立ち上がるかは実機で要観察。

## 5. 残課題・要・司令部判断
- **(所見・未修正)ウォッチャーが起動直後に過去ログを連続診断する件**:
  初回起動で state.json が無いと、`logs/report_*.md` など既存ファイルを offset 0 から
  全読みし、過去レポート内の Traceback/Error/🔬 を「新規エラー」と誤認 → 署名ごとに
  当直(headless claude)を連続起動する。debounce/lock で同時多発は抑えるが、処理済みの
  バックログを再診断して inbox を汚し、起動を浪費する。**「新規エラー監視」の意図とずれ**
  ているとみる。
  - 推奨(要判断): 初回(state 無し)は既存ファイルサイズを offsets にシードして既読扱いに
    し、起動後の追記／新規ファイルだけ拾う。`SCAN_BACKLOG_ON_START`(既定 False)を置けば
    一回だけ全掃きも可能。
  - トレードオフ: 停止中に既存ファイルへ追記された新規エラーは見逃す(新規ファイルは拾える)。
  - 今回の指示範囲外のため未適用。やるなら別途 diff を出す。
- **4拠点同期 / push**: 指示で push 禁止のため未実施。対象は VS Code 運用ツールであり
  Colab パイプライン本体ではないが、他PC・他拠点で同じ起動構成を使うなら同期要否を司令部判断。

## 6. 厳守ルール適合
- Setting A の7値・PuLID・量子化核は未接触。例外の握り潰し(silent fail)追加なし。
- 編集は指示された2ファイルのみ。push 未実施。
