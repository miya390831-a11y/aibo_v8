# 実装検証チーム ― 起動・実行フロー

タブ2(実装検証統括)の回し方。技術統括チームと同じ repo・同じ CLAUDE.md を共有し、
役割だけ起動時の `--append-system-prompt` で分ける。

---

## 配置
```
<repo>/
  CLAUDE.md                         # 全タブ共通ルール(自動ロード)
  .claude/agents/
    lead-verify-kuroudo.md          # 統括の役割憲章(起動時に注入)
    implement-kuroudo.md            # 現場: 実装
    errorfix-kuroudo.md             # 現場: エラー対応
  docs/directives/
    TEMPLATE_directive.md           # 司令部→統括 の指示書テンプレ
  start_lead_tab.bat                # タブ2をこのアイコンから起動
```

## 起動(タブ2)
1. `start_lead_tab.bat` を実行 → セッションが「統括」として立ち上がる
   (役割憲章を system prompt に追記 + 共通 CLAUDE.md 自動ロード)。
2. 統括はまず repo 現状を把握して**指示書待ち**になる。

## 実行フロー(指示が来てから)
```
[司令部=この対話]  指示書を作る(TEMPLATE_directive.md 形式)
      │   docs/directives/<id>.md に保存 or タブ2に貼り付け
      ▼
[統括]  指示書を受領(@docs/directives/<id>.md で参照)
      │  - 完了条件・対象ファイル・やらないこと を確認
      │  - 厳守ルール/スコープに反するなら実行せず司令部に確認
      ▼
[統括 → 実装くろうど]  具体タスクに分解して実装させる
      │  (エラーが出たら → エラー修正くろうど に診断・修正)
      ▼
[統括]  完了条件を検証(py_compile / 再現確認 / 厳守ルール)
      │  apply_fix.py で安全適用 or 直接適用 → push 判断
      ▼
[統括]  logs/report_<task>_<ts>.md に結果報告(専門用語を避けて)
      │  要・司令部判断は「保留」として明記
      ▼
[司令部]  報告を受けて次の作戦へ
```

## 役割境界(重要)
- **統括は戦略を決めない**。指示書の範囲を遂行管理するだけ。迷ったら司令部に上げる。
- **実装くろうどは設計判断をしない**。完了条件に向けて最小差分で実装するだけ。
- 設計・優先順位・「そもそも何をやるか」は**司令部(この対話)**で決める。

## 技術統括チーム(タブ1)との関係
- 同じ仕組み。タブ1は `research-kuroudo` / `design-kuroudo` を使い、役割は
  起動時に技術統括の憲章を注入する(start_lead_tab.bat を複製して CHARTER と KICKOFF を差し替え)。
- チーム間の受け渡しは docs/(設計・指示)と logs/(報告)経由。

## メモ
- `--permission-mode acceptEdits` は統括が逐一確認なしで編集できる設定。厳守ルールは
  guard_forbidden フックが機械的に守る。手動ゲートを増やしたいなら外す。
- `--append-system-prompt-file` が使えるバージョンなら .bat はその1行に簡略化できる。
  使えなければ PowerShell 経由(同梱の .bat 既定)。`claude --help`/docs で確認。
