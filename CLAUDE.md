# AIBO Cyber Studio · Claude Code 運用ルール

このファイルは Claude Code (CLI) が `aibo_v7` で作業する際の
プロジェクト共通ルールを定義する。すべてのセッションで自動読込される。

## 完了報告ルール (★ 厳守)

すべてのタスク完了時に、次の 3 つを必ず実行する:

### 1. ファイル化

完了報告を以下のパスに保存する:

```
C:\Users\yuuki\aibo_v7\logs\report_<タスク番号>_<YYYYMMDD>_<HHMMSS>.md
```

タスク番号の例: `001`, `001_5`, `001_6`, `001_7`, `002_phase_a`, `006_a1_poc_day1`

タイムスタンプ生成:
- bash: `date +%Y%m%d_%H%M%S`
- PowerShell: `Get-Date -Format "yyyyMMdd_HHmmss"`

### 2. 画面表示

同じ内容を会話画面にも表示し、PO がスクロール無しで状況確認できるようにする。

### 3. 保存通知

ファイル化完了後、以下のメッセージを表示する:

```
完了報告を保存しました:
   C:\Users\yuuki\aibo_v7\logs\report_<XXX>_<YYYYMMDD>_<HHMMSS>.md

PO へ: Claude チャット (Web 版) にこのファイルをアップロードしてください
```

### テンプレート

- 標準テンプレート: `logs/README.md` 参照
- 簡易版テンプレート: **10 分未満かつコード変更なし** のタスクのみ使用可
- **コード変更を伴うタスクは必ず標準テンプレート**

### 必須セクション (標準テンプレート)

- タスク名 / 実行日時 / 所要時間 / 実行モード
- 変更/作成ファイル (パス + md5 + サイズ)
- 動作確認結果
- 4 拠点 MD5 検証
- Git コミット (ブランチ + hash + メッセージ)
- 観察された現象 (期待通り / 想定外 / 次タスクへの改善点)
- 退行リスク評価
- 未実施 (次ステップ)
- PO へのひとこと

## 4 拠点同期ルール

コード/スクリプト変更時は以下 4 拠点を同期する:

| # | パス | 用途 |
|---|------|------|
| 1 | `C:\Users\yuuki\aibo_v7\` | 主 (作業ディレクトリ) |
| 2 | `C:\Users\yuuki\Downloads\AIBOV7\` | バックアップ 1 |
| 3 | `C:\Users\yuuki\Downloads\AIBOV7\3a\` | バックアップ 2 |
| 4 | `G:\マイドライブ\aibo_v7\` | Drive (Colab 参照) |

同期スクリプト: `sync_4_locations_v2_bridge.ps1` (拠点 1→2,3 のみ)
G: は手動 cp 必須。完了後 MD5 で 4 拠点一致を検証する。

## Git ブランチ運用

- `master`: 主ブランチ。すべての変更を反映。
- `colab-stable`: Colab 安定版。master をマージして同期。
- コード変更時は両ブランチに push する。

## bypass モード運用 (#001.6 設定済)

- `~/.claude/settings.json` で `defaultMode: bypassPermissions`
- 危険コマンドは `permissions.deny` でブロック済
  (rm -rf 系 / sudo / format / del-rmdir-rd /s / git push --force / git reset --hard など)
- wrapper 経由 (`bash -c '...'` 等) は deny を擦り抜ける可能性あり
- 暴走時はデスクトップの `AIBO Emergency Stop` アイコンで全停止

## 関連ファイル

- `start_claude_code.bat/.ps1`: CC 起動 (bypass モード)
- `start_aibo.bat`: フロントエンド (npm run dev)
- `start_aibo_colab.bat`: Colab Notebook 起動
- `emergency_stop.bat`: 緊急停止 + 自動バックアップ
- `setup_desktop_shortcuts_full.bat/.ps1`: デスクトップアイコン整備
- `sync_4_locations_v2_bridge.ps1`: 拠点 1→2,3 同期
