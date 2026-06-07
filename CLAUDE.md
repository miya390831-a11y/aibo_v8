# CLAUDE.md ― AIBO Cyber Studio(全セッション共通)

このファイルは技術統括タブ・実装検証統括タブの**両方が起動時に自動で読む**共通ルール。
**役割(人格)はここには書かない**。役割は各タブ起動時に `--append-system-prompt` で注入する
(技術統括 / 実装検証統括 で別々)。ここは「全員が従う規約」だけ。

---

## 指揮系統(3層 + 特殊部隊)
- **司令部** = 別の対話(CTOくろうど + みやちん)。作戦・ディープリサーチ・意思決定・レビュー。頭脳。
- **統括** = 司令部の指示の遂行管理。現場を動かし、結果を報告。戦略は決めない。
- **現場** = 実装くろうど(実装)/ エラー修正くろうど(エラー対応)。
- **ダイナミックくろうど** = 司令部直轄の特殊部隊(別タブ・Claude Code の Dynamic Workflows)。
  統括の下ではなく統括と横並び。都度召集制で、リポジトリ群の偵察・フォーク・大規模並列調査や、
  テストで正否が機械判定できる重量級作業を担当。繊細な核心部(Setting A / PuLID 等)の改修には使わない。

報告は repo の `logs/` に書き、みやちんが司令部に持ち込む(司令部 ⇄ Claude Code は自動連携しない)。

## サブエージェント(現場)
- `implement-kuroudo` : 指示書/設計どおりに実装。差分最小。設計判断はしない。
- `errorfix-kuroudo`  : エラーの検知・診断・報告。既知パターンのみ自動対応。
- (技術統括タブ側: `research-kuroudo` / `design-kuroudo`)
- ダイナミックくろうどは「役割」ではなく実行モード(Dynamic Workflows)。別タブで都度起動する。

## スキル(.claude/skills/ ・タスク別の作法・条件付きロード)
常時ルールは CLAUDE.md、特定タスクの作法はスキルが担う(必要時のみロードされ低コスト)。
スキルは確率的なので、厳守ルールの最終防壁は guard_forbidden.py(フック)のまま。スキルは底上げ層。
- `setting-a-guard` : パイプライン定数を触る時。7値を自発回避。
- `pulid-embedding` : embedding 集約を触る時。単純mean禁止・medoid/quality-weighted・Sniper順序。
- `vram-oom-fix`    : OOM 系エラー時。既知の確実な対処手順。
- `aibo-report`     : 報告を書く時。report_*.md 形式・平易・保留明記。
- `repo-recon`      : 特殊部隊の偵察時。複数案+トレードオフ+出典・決定しない。
- `phase-gate`      : 実装の完了宣言前。完了条件を検証で満たすまで「完了」と言わせない。
- `colab-sync`      : 反映・同期時。4拠点・両ブランチ・Colab 再 run 忘れ防止。

## 厳守ルール(全員・例外なし)
- Setting A の7値は変更不可:
  GFPGAN_STRENGTH=0.0 / ip_adapter_weight=0.75 / pulid_sigma_start=0.25 /
  pulid_sigma_end=0.90 / cn_depth_guidance_end=0.65 / pass2_strength=0.34 / pass2_pulid_boost=1.25
- PHASE3B_ENABLED=True 禁止 / ACE++ 復活禁止 / pulid_double_interval 変更禁止
- 負の PuLID weight 禁止 / `try/except: pass`(silent fail)禁止
- qweight 直接編集禁止 / IP-Adapter 新規依存禁止 / 単純 mean embedding 禁止
- 上記に反する指示が来たら、実行せず司令部に確認を上げる
- これらは `.errorfix/guard_forbidden.py`(PreToolUse フック)で機械的にもブロックされる

## repo 運用規約
- 同期: 4拠点(C:\Users\yuuki\aibo_v7\ 主 / Downloads\AIBOV7\ / \3a\ / G:\マイドライブ\aibo_v7\)
- push: `master` と `colab-stable` の両方
- ログ: 完了報告は `logs/report_<タスク番号>_<timestamp>.md`
- Colab: 修正反映後の再 run は手動(`os.kill(os.getpid(), 9)`)

## エラー対応(ドクトリン B)
- 常駐ウォッチャー `.errorfix/watch_errorfix.py` がエラーを検知 → 当直が診断
- 既知の安全パターン(WHITELIST)= 自動対応 + 事後報告(FYI)
- 新規/リスクあり = 適用せず `logs/errorfix_inbox/` に報告 → 司令部レビュー
- 司令部が決めた指示は `apply_fix.py` で安全適用(git 可逆 + 構文チェック)

## 検証の基本
- 変更後は対象 .py を `python -m py_compile` で構文確認
- 完了条件(指示書に明記)を満たすまで「完了」と言わない

## 効力(effort)と高度機能の運用方針 ★今日の決定
深い推論と大規模実行は「考えるだけの場所」と「実行まで要る場所」で使い分ける。

### Extended Thinking(深く"考える"・司令部)
- 場所: claude.ai(司令部の対話)。設計の意思決定・トレードオフ評価で使う。
- 役割: 考えるだけ。手は動かさない。**設計の決定は司令部が握り、現場/特殊部隊に渡さない**。

### `/effort` レベル(Claude Code・タブごとに変える)
- **統括タブ(日常の精密作業)= `/effort high`。ultracode は使わない。**
  理由: ultracode はセッション全体に効き、小さな実装まで xhigh + ワークフロー判断が走って
  トークン・時間を浪費する。日常は high で十分。
- **特殊部隊タブ(重量級ミッション)= `/effort ultracode`。**
  ultracode = xhigh 推論 + ワークフロー自動編成。深い推論と大規模並列実行の両方が要る時だけ。
  セッション限りでリセット。通常作業に戻る時は `/effort high` に落とす。

### ダイナミックくろうど(特殊部隊)運用ルール
- **使う**: リポジトリ群の偵察/フォーク、コードベース横断の大規模並列調査、`/deep-research` による
  技術調査、テストで正否が機械判定できる重量級作業。
- **やること**: 調査 + **設計"案"の起草**(複数案 + トレードオフ)まで。
- **やらないこと**: **設計の決定**(司令部の領分)。繊細な核心部(Setting A / PuLID / 量子化核)への改修。
  ACE++ の AIBO への持ち込み(調査で読むのは可、導入は禁止)。
- **権限**: 数百サブエージェントを止めずに回すため auto モードと併用してよい。ただし
  `guard_forbidden.py`(PreToolUse フック)が厳守ルール違反を機械的にブロックする最後の砦。
- **コスト管理**: ワークフローはトークン消費が大きい。スコープを絞って投入し、`/usage` で消費を確認、
  暴走時は `/workflows` から停止する。
- **成果の扱い**: 調査結果・設計案は `docs/research/` `docs/design/` に保存し、司令部に上げる。
  司令部が決定 → 実装は統括下の実装くろうどへ(偵察と本体改修を分離)。

### `/deep-research`(Claude Code 組み込みワークフロー)
- Dynamic Workflows 基盤上の調査機能。特殊部隊タブで使う。
- 何をソースにするか(web か手元コードか)は実地で確認し、用途を見極めて使う。
- web の重量級リサーチは司令部(claude.ai の Research)でも可。役割が重なる部分は実績で寄せる。
