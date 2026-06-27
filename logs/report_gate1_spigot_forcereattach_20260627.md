# 報告: 起動セルに蛇口 force re-attach 内蔵 + LOG セル追加 + Cell-deps CPU onnxruntime 化

- **日付:** 2026-06-27
- **依頼:** 司令部 → 統括(実装)「force re-attach 内蔵 + LOG 専用セル + Cell A を CPU onnx に」
- **対象:** `aibo_v7_colab.ipynb` / `attach_aibo_log_spigot.py`
- **push:** `origin/sync/colab` ← 新 tip **`b6e6ee2`**(`29fb224..b6e6ee2`)。master parked。
- **不変:** B/C/D は byte 一致 verbatim・E/④a/④b 保持・core .py(01〜17)無変更・manifest 緑(05=4055f4a5)・Setting A 7値・PuLID 0.7・CLEAN 方式。

---

## A. 蛇口 force re-attach(diff の要点 + self-test 出力例)
**根本原因:** ①旧 spigot は「既に attach 済みなら skip」で新版に張り替わらなかった。②さらに
[Cell-run] の早期冪等ガードが FastAPI 既起動時に **`raise SystemExit`** して、**末尾の蛇口 attach に
到達しないまま終了**していた(=既起動カーネルでは新版が一度も走らない)。両方を直した。

**A-1. `attach_aibo_log_spigot.py` v2→v3(force re-attach):**
- 「skip」を廃止。`_purge_spigot()` で **同一 path(`baseFilename==/content/aibo_gen.log`)or 旧蛇口マーカ
  (`_aibo_spigot`)の FileHandler を root・AIBO_v7 から remove** → **root に新版 FileHandler を 1 個だけ**付け直す。
  二重書込みは「同一 path は 1 個だけ」で回避。
- 3 経路は維持: (1) root FileHandler / (2) `AIBO_v7.propagate=True` + level INFO 保証(05:855/878 の発生元)/
  (3) stdout tee(**既 tee は再 tee しない**=二重書込み回避)。
- self-test を attach 直後に実行 → `os.path.getsize`>0 を確認。silent fail させない。

**A-2. `[Cell-run]`(helper 化 + 既起動でも attach):**
- `_aibo_attach_spigot()` helper を定義(CLEAN 配下 spigot を exec)。
- **早期冪等ガードの「既起動 skip」分岐で、`SystemExit` の前に `_aibo_attach_spigot()` を呼ぶ** →
  既起動(同一カーネル)でも新版蛇口へ確実に張り替わる。
- 末尾 PHASE6 でも同 helper で force re-attach(新規起動パス)。

**self-test 出力例(設計上の期待):**
```
[spigot] force re-attach: 旧 handler 1 個除去 → root に新版 FileHandler 1個 → /content/aibo_gen.log
[spigot] stdout tee 有効(print 由来の [OSS]/inject-point も捕捉)
[spigot] root.level=INFO / AIBO_v7.level=INFO propagate=True
✅ spigot self-test OK size=123B → /content/aibo_gen.log(UI で 1 枚生成 → [LOG] セルで `[OSS] APPLIED n=14` を確認)
```
※ 0 の場合は `⚠️ spigot 配線失敗: self-test が file に乗らない(size=0)…` を出す。

## B. LOG セル(最終形・配置 = [Cell-run] → [LOG] → E → ④)
```python
# 📋 [LOG] OSS 適用ログ確認(生成後に実行)── GATE① 判定を 1 行表示
import os
P = "/content/aibo_gen.log"
if not os.path.exists(P):
    print("❌ gen.log が無い。[Cell-run] 末尾の蛇口 attach(PHASE 6 / self-test)を先に。")
else:
    lines = open(P, encoding="utf-8", errors="replace").readlines()
    print(f"=== gen.log 総行数: {len(lines)} ===\n")
    hit = [l.rstrip() for l in lines if any(k in l for k in
           ("[OSS]", "inject-point", "APPLIED", "sigma"))]
    if hit:
        print("=== 🧩 OSS 関連ログ ===")
        for l in hit:
            print(l)
        applied = [l for l in hit if "APPLIED n=" in l]
        if applied:
            print("\n✅ GATE① 判定: [OSS] APPLIED 検出 →", applied[-1].split("APPLIED")[1][:40])
        else:
            print("\n⚠️ inject-point は出たが APPLIED 未検出 → fallback 疑い(05:881 参照)")
    else:
        print("⚠️ OSS 痕跡なし。① 蛇口未配線 or ② 今回生成が OSS 経路を通っていない。")
        print("   末尾 120 行を表示:")
        for l in lines[-120:]:
            print(l.rstrip())
```

## 3. Cell-deps の onnxruntime CPU 版確定
- gpu-first 試行を**撤去**。`pip uninstall onnxruntime onnxruntime-gpu`(競合除去)→ **`pip install onnxruntime`(CPU)** 1 本。
- 理由: gpu 版は環境により `libcudart.so.13`(CUDA13)要求で **import 不可→FATAL**。insightface 顔検出は
  CPU で十分(944a9b8 実証 v1.27.0)。numpy==2.4.6 exact pin・再起動≤1 は前回どおり。

## 検証(PC 範囲)
- 全 6 セル `py_compile` 緑 / `attach_aibo_log_spigot.py` 単体 compile 緑。
- B/C/D は eefa451 と **byte 一致**(verbatim)/ E・④a・④b 保持 / core .py 無変更 / `check_manifest` 緑。
- helper は早期ガード分岐と末尾の両所で結線(2 呼び出し)。新規 glue に silent-fail パターン無し。

## 残(PO 実機・GATE① 正式締め)
1. クリーン再起動 → [Cell-deps](CPU onnx・numpy==2.4.6・再起動≤1)。
2. [Cell-run] → 末尾 **`✅ spigot self-test OK size=..B`** + `🔎 PuLID: degraded=False`。
   (既起動カーネルで [Cell-run] を押した場合も、skip 表示の直後に蛇口 self-test 緑が出る。)
3. UI 1 枚生成(slider 14)→ **[LOG] セル** → **`[OSS] APPLIED n=14`** 表示 → **GATE① 正式クリア**。

## 司令部判断が要る点
- なし。`AIBO_NUMPY` の版だけ実機 pip conflict 時に調整余地あり(その時報告)。

新 tip: **`b6e6ee2`**(`origin/sync/colab`)。
