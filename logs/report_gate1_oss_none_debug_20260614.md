# 報告: GATE① ブロッカー解明 — 本番で OSS が発火しない(`OSS='None'`)

- 日付: 2026-06-14
- 担当: 統括(read-first 診断・instrument・同期準備)
- 状態: **コード読み診断・logging-only instrument 実装・構文検証・ローカルコミット完了**。
  **真因の最終確証(stale-module か否か)は Colab 実機=PO 確認待ち**(ここで「解決」とは言わない)。

## 0. 結論(先に一言)
- **H1(真に未発火)で確定。** ただし **prod の committed コードは正しい**。
- **真因 = 実行中(Colab runtime)の `05_orchestrator.py` が stale**:`04` のフックは新版(ceab744)が
  ロード済(`oss_hook_installed=True`)だが、`05` の `_run_pass1` が **OSS 注入ブロックを未搭載の旧版**。
  → フラグ(`_oss_force_sigmas`)が一度もセットされず、wrap は `fs=None` で素通し → ただの 14-step。
  → 仮説 **(a) scheduler-swap ではない**(理由は §2)。**(b) の変種**=「OSS を入れた `_run_pass1` を
  実経路が通らない」だが、原因は CN ルートではなく **05 モジュールの desync**。

## 1. H1/H2 を決め切った論理(コード読みのみで確定)
committed の `_run_pass1`(05:847-)を portrait 経路で辿ると、以下が全て成立:
1. **経路 = `_run_pass1`**:PORTRAIT は `default_enable_multi_cn=False`(01_config:509)→ `use_cn=False`
   (05:571)→ CN 経路に行かない。
2. **`_oss` は非 None**:`oss_sigmas(14)` は例外を出さず 14 要素を返す(局所再現で 14/28/13/29 全 OK)。
   `np` も 04:56 で import 済。
3. **sigmas 長一致**:GATE④ 緑 = `pipe_base.scheduler.sigmas` 長 15(step=14)→ `len(_used)==len(_oss)`。
4. **logger が拾える**:`logger="AIBO_v7"`(01/04/05 共通)、effective level=INFO(01_config:50 basicConfig)
   → `logger.info(...)` は通る。検証セルの handler も "AIBO_v7" に attach=同一 singleton。

→ よって committed コードが動いていれば、**`[OSS] APPLIED …`(✓ でも ⚠️FALLBACK でも)が必ず1行出て
捕捉される**。`OSS='None'`(APPLIED 文字列が皆無)は **そのブロックが実行されていない**ことの証明。
= **H1**。検証セルの捕捉ミス(H2)ではない。

## 2. なぜ仮説(a)scheduler-swap ではないか(切り分け)
- swap / stale-wrap なら、wrap は乗らずとも `_run_pass1` の `if _oss is not None:`(05:861)は実行され、
  既定 sigmas と OSS の差で **`[OSS] APPLIED n=14 … ⚠️FALLBACK`(warning)** が必ず出る=捕捉される。
  → `OSS='None'`(文字列ですらない)とは両立しない。
- さらに GATE④ 緑 = `pipe_base.scheduler.sigmas` が 14/28 に更新 = **wrap 済 scheduler の set_timesteps は
  実際に呼ばれている**(swap で別 scheduler が使われた訳でもない)。
- 「APPLIED 文字列が一切出ない」を満たすのは **OSS ブロック自体が実行コードに無い**場合のみ。
  04 フックは新版(`oss_hook_installed=True`)・05 が旧版 → **04/05 desync**。

## 3. 実装した instrument(logging only・生成非改変・revertible)
| 変更 | 内容 | 場所 |
|---|---|---|
| inject-point 証跡 | `_run_pass1` の OSS ブロック先頭に到達ログを1行追加(`🧩 [OSS] inject-point reached: route=_run_pass1 steps=.. hook_on_live_sched=..`) | 05_orchestrator.py:847- |
| ログ蛇口 | `AIBO_v7` ロガー→ `/content/aibo_gen.log` の FileHandler(指示書 §2)。新規ファイル | attach_aibo_log_spigot.py |

- inject-point 行は **stale 判定の決定打**:次 run で
  - **行が出る → 05 は live**(さらに APPLIED ✓/⚠️ で H2/a を最終切り分け)
  - **行が出ない → 05 stale 確定**(=今回の本命)。
- `hook_on_live_sched` は「これから叩く scheduler に wrap が乗っているか」= 仮説(a)の即時判定材料。
- ログ蛇口は **UI→FastAPI→generate の本物経路**の最終真偽判定用。logger level は変えず(prod 非改変)、
  handler を1個足すだけ。二重 attach 防止マーカー付き。

## 4. 厳守事項の遵守
- **読み first**:diff・トレースのみで H1/H2 を確定。修正は logging-only に限定。
- **検証済み構成 不変**:Setting A 7値 / PHASE3A/3B / no-Hyper / OSS スケジュール / pass2 off /
  phase3 off / PuLID 0.7 に**一切触れていない**。`set_lora_strength` 不使用。
- **silent fail 無し**:追加は `logger.info` のみ。`try/except: pass` なし。
- `python -m py_compile 05_orchestrator.py / attach_aibo_log_spigot.py` → **OK**。
- git **ローカルコミットのみ**。push は PO 判断。

## 5. ★PO への再検証手順(ここで初めて GATE① ✓ を確定できる)
1. **全 .py を G:\マイドライブ\aibo_v7\ に再同期**(特に `05_orchestrator.py`。`attach_aibo_log_spigot.py` も)。
   → 4拠点のサイズ/mtime 一致を確認(05 が今回の desync 本命)。
2. **Colab 再起動**(`import os; os.kill(os.getpid(), 9)`)→ Cell 0 から再 build。
3. ログ蛇口を1回 attach:
   `exec(open("/content/drive/MyDrive/aibo_v7/attach_aibo_log_spigot.py", encoding="utf-8").read())`
4. **検証セル**(`exp_portrait_verify_oneshot.py`)再走 → 各生成で `🧩 [OSS] inject-point reached`
   と `[OSS] APPLIED n=14 maxΔ≈0.0 ✓`、`OSS='None'` の消滅を確認。
5. **+ UI 実経路**:UI(localhost:3000・slider 14)で1枚 → `!tail -n 120 /content/aibo_gen.log` で
   `🧩 [OSS] inject-point reached` + `[OSS] APPLIED n=14 ✓` を確認(両方緑で初めて ship 可)。

### 予測
- 再同期+再起動だけで `OSS='None'` は消える公算が高い(committed コードは正しい)。
- 万一、再同期後も inject-point 行が出るのに `OSS='None'`(=⚠️FALLBACK すら出ない)なら、
  本報告の論理に反する=別経路実行の可能性 → ログ蛇口の全文を司令部へ。

---
**要点:** `OSS='None'` は **H1(未発火)**。committed コードは正しく、**真因は Colab runtime の 05 が stale
(04 新・05 旧の desync)**。仮説(a)swap は ⚠️FALLBACK ログが出るはずで棄却。対処は **05 再同期 → Colab
再起動 → 再 build**。追加した inject-point 証跡 + ログ蛇口で、次 run に stale/live と H1/H2 を機械的に確定できる。
