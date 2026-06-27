# 報告: GATE① 仕上げ一括(numpy固定 / ログ蛇口配線 / 2セル化 / guidance・GATE③段取り)

- **日付:** 2026-06-27
- **依頼:** 司令部 → 統括(実装)「GATE① 仕上げ4点を一括」
- **対象:** `aibo_v7_colab.ipynb`(5→2核心セル) / `attach_aibo_log_spigot.py`(v2)
- **push:** `origin/sync/colab` ← 新 tip **`eefa451`**(`944a9b8..eefa451`)。master parked。
- **不変:** core .py(01〜17)無変更・`module_manifest` 整合(05=4055f4a5)・Setting A 7値・PuLID 0.7・CLEAN 方式。

---

## ① numpy 固定の版 + 再起動回数
- **固定版:** `AIBO_NUMPY = "2.4.6"`(Cell-deps 冒頭の単一定数・司令部判断で 1 行変更可)。
  - 旧実装は `PIP_CONSTRAINT=numpy>=2.1.0` の**レンジ** + 末尾 `--upgrade numpy>=2.1.0` で、
    resolver が毎回 2.4.6 へ寄せ直す=**毎回 ABI 再起動**が挟まっていた(症状の真因)。
  - → `PIP_CONSTRAINT=numpy==2.4.6` の **exact pin** にして、build 含む後続の全 pip が numpy を
    動かせなくした。`_numpy_ok()` も exact 一致判定に変更(非決定性を排除)。
  - 2.4.6 は「観測上スタックが収束する版」を採用。万一 pip conflict が出たら定数 1 行を差し替える。
- **再起動回数: 最大 1 回(条件次第で 0 回)。**
  - 再起動は「**現カーネルに既ロードの numpy ABI が固定版と食い違う時だけ**」(`sys.modules["numpy"].__version__ != AIBO_NUMPY`)。
  - Colab 既定が 2.4.6、または numpy 未ロードなら **0 回**で確定 → そのまま [Cell-run] へ。
  - 既定が 2.5.0 等で 2.4.6 へ変えた場合のみ 1 回 `os.kill`。再起動後 [Cell-deps] 再実行で緑(deps 済)→ [Cell-run]。
  - マーカー `/content/.aibo_deps_tried` で再起動ループを構造的に封じる(従来踏襲)。

## ② どのロガーに繋ぎ替えたか + 設計確認
- **発生源の特定:** `[OSS] APPLIED n=.. ✓` / `🧩 inject-point reached` は **`05_orchestrator.py:855,878`** で
  **`logger.info/warning`**(`logger` = `01_config` の `getLogger("AIBO_v7")`)が出している(print ではない)。
  FastAPI は `07_main.py:504` の **daemon thread・同一プロセス**起動なので、原理上は "AIBO_v7" への
  handler で UI 経路も拾えるはず。0 bytes は配線の取りこぼし。
- **配線(v2・根本原因に賭けない3経路):**
  1. **ROOT logger に FileHandler** を付ける(logger 名非依存で伝播してくる全 logging を捕捉。
     "AIBO_v7" は propagate=True なので root に必ず届く。root だけに付け二重書き込みも回避)。
  2. **`AIBO_v7.propagate=True` 強制 + level を INFO 以下に保証**([OSS] APPLIED は info 行。
     level が WARNING に上がっていても落とさない。prod 非改変=「下げるだけ」)。
  3. **`sys.stdout` を tee**(万一 print 由来でも file に乗せる)。I/O 失敗は握りつぶさず記録。
- **設計上の保証:** attach 時に **self-test**(logging + print の両経路を撃つ)→ `os.path.getsize` で
  file>0 を即確認・表示。→ **PO は UI 生成の前に「配線が生きている」ことを確認できる。**
  その後 UI 1 枚生成 → `!tail -n 120 /content/aibo_gen.log` で `[OSS] APPLIED n=14 ✓` を目視。
  ※ self-test は乗るのに UI 生成行が出ない場合は「その生成がこのカーネルの orchestrator を
    通っていない(ngrok 先が別/旧サーバ)」と切り分けできる(蛇口バグではない)。
- **[Cell-run] 末尾で自動 attach**(`/content/aibo_clean/attach_aibo_log_spigot.py` を exec)。手動操作不要。

## ③ 新セル構成(5 → 2 核心セル)
| # | セル | 役割 |
|---|---|---|
| 0 | **[Cell-deps]** | ① numpy exact pin + onnxruntime 確定。再起動≤1(ideally 0)。 |
| 1 | **[Cell-run]** | 旧 B+C+D を verbatim 連結:model warm → CLEAN 配置 → import/build → FastAPI/ngrok。**先頭に冪等ガード**(既起動なら全 skip=OOM 回避)、各 phase の開始ログ、**末尾でログ蛇口 auto-attach**。 |
| 2 | [任意] | 環境確認(localhost:8000 / ngrok 疎通)。 |
| 3 | [任意] | ④a guidance A/B 比較。 |
| 4 | [任意] | ④b GATE③ 原寸×複数 seed。 |
- **運用は実質 2 クリック:** [Cell-deps](必要なら再起動→もう一度 [Cell-deps])→ [Cell-run]。
- B/C/D は**検証済みコミット版を verbatim 連結**(差分最小・revertible)。新規 glue のみ silent-fail 無し。

## ④ guidance 比較 + GATE③ の PO 実行手順
いずれも**生成タスク=PO 実行**。統括は「比較しやすい出力(原寸+GRID)」の段取りのみ用意。prod 非改変。
- **④a(guidance A/B):** N=14・seed 固定・Nika refs で **guidance 4.0 と 3.5 を 1 枚ずつ**生成 →
  原寸保存 + 横並び GRID。PO が肌/identity を見て 1 つ選択。
  - 本番既定への反映 → **frontend `portrait-mode.tsx` の `useState(<guidance>)`** を変更
    (backend 既定 `01_config.GenerationConfig.guidance_scale=3.5`。UI から渡る値が優先)。
- **④b(GATE③):** 確定 guidance(セル先頭定数)で **N=14 × 複数 seed** を原寸保存 + GRID。
  PO が**原寸で D20級肌 + Nika identity 保持**を複数画で目視(機械判定しない)。
- 実装は `srv._build_configs` + `orch.generate(mode=PORTRAIT, save=False)` + `pm04._depth_grid`
  (`exp_portrait_verify_oneshot.py` と同経路。refs=`/content/drive/MyDrive/顔` の公式6枚・差し替え可)。

## 検証(PC 範囲)
- 全 5 セル `py_compile` 緑 / 連結 seam 健全 / `tools/check_manifest.py` 緑(core desync なし・05=4055f4a5)。
- core .py(01〜17)無変更・manifest 無変更(spigot/notebook は manifest 対象外)。新規 glue は guard 禁止の
  silent-fail パターン無し。`attach_aibo_log_spigot.py` 単体 `py_compile` 緑。

## 残(PO 実機確認待ち・統括は Colab を起動できないため)
1. [Cell-deps] 再起動が想定どおり **≤1 回**で収束するか(2.4.6 で pip conflict が出ないか)。
2. [Cell-run] 末尾 self-test が `/content/aibo_gen.log` を **size>0** にするか。
3. UI 1 枚生成で `[OSS] APPLIED n=14 ✓` が同 log に出るか(=**GATE① 正式クリア**)。
4. ④a/④b の生成 → PO 目視で guidance 確定 → GATE③。

## 司令部判断が要る点
- なし(指示範囲で実装・push 済み)。`AIBO_NUMPY` の版だけ、実機 pip conflict 時に調整余地あり(その時報告)。

新 tip: **`eefa451`**(`origin/sync/colab`)。
