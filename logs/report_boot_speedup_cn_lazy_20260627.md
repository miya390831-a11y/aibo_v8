# 報告: 起動高速化 — ControlNet 遅延ロード + build 内訳計測 + warm 運用ガイド

- **日付:** 2026-06-27
- **依頼:** 司令部 → 統括(偵察・設計)→ 実装くろうど(core .py)/ 統括(notebook)
- **緑基準:** `gate1-green-20260627`(5d29113)固定。本作業は**別コミット**の高速化(portrait 出力不変)。
- **push:** `origin/sync/colab` ← 新 tip **`8ea4946`**(`5d29113..8ea4946`)。master parked。
- **不変:** Setting A 7値 / PuLID 0.7 / IP-Adapter 0.75 / Nunchaku INT4 / OSS 05=4055f4a5 / VAE / DL アーキ。
- **分離維持:** 設計=統括(recon_032)、core .py 改修=実装くろうど、notebook=統括。

---

## A. build 内訳計測(logging-only タイマ・挙動/出力 不変・revertible)
build 178.8s の内訳を確定するため `[BUILD-TIME] <name>: N.s` を**ログ追加のみ**で挿入(順序・戻り値・例外不変)。
PO の **cold run 1 回**でこれらの行が出る → 内訳が確定する。

| file | ラベル(grep `[BUILD-TIME]`) | 対象 |
|---|---|---|
| 04 | `nunchaku_transformer.from_pretrained` | Nunchaku INT4 transformer ロード |
| 04 | `PuLIDFluxPipeline.from_pretrained` | PuLID 構築(T5/EVA-CLIP/VAE/pulid_model) |
| 04 | `controlnet_model.from_pretrained` / `pipe_cnet.from_pretrained` / `ensure_controlnet (total)` | CN 一式 |
| 04 | `_build_i2i` / `_build_redux_prior` / `_enable_vae_optimizations` | I2I / Redux / VAE |
| 03 | `ControlNetEngine FluxControlNetModel load` | 03 CN model(=今回撤去対象) |
| 03 | `ipadapter_image_encoder load` / `load_ip_adapter` | IP-Adapter |

**内訳表(PO cold run の `[BUILD-TIME]` 行を貼って確定):**
```
Nunchaku transformer : ____ s
PuLIDFluxPipeline    : ____ s
_build_i2i           : ____ s
_build_redux_prior   : ____ s   ← (recon_032 B: redux は portrait 未参照。次点候補)
VAE optimizations    : ____ s
03 IP-Adapter        : ____ s
03 CN model(撤去分) : ____ s   ← 今回 Phase D から削除した分(削減確定)
ensure_controlnet    : ____ s   ← 今回 起動から外した分(初回 CN 生成へ後ろ倒し)
```

## B. ControlNet 遅延ロード(portrait byte 不変)
**撤去した起動時 eager:**
1. **07 Phase D** の `ie.controlnet.lazy_init()` を撤去。調査(grep 横断)で **03 ControlNetEngine の
   FluxControlNetModel は推論で未使用**と確認(CN 推論は `pm.pipe_cnet`/`pm.controlnet_model` 経由。
   `ie.controlnet` は `preprocess()` の detector だけ使い、detector は controlnet_aux が都度ロード)。
   → 使われない model を起動時にロードしていたので**撤去が安全**。IP-Adapter init は維持。
2. **notebook Cell-run** の起動時 `ensure_controlnet()` / `_wrap_transformer_forward_for_cn()` /
   pipe_cnet への CN-IP 配線を撤去。

**遅延移管先:** 撤去した CN 専用 setup(pipe_cnet への image_encoder/feature_extractor 配線 +
`set_scale(pipe_cnet, IdentityConfig().ip_adapter_weight)`)を **05 `_run_pass1_with_cn` の初回 lazy
ブロック**へ移管(idempotent・`pm._cnet_ipadapter_wired`)。既存の lazy `ensure_controlnet()`(05:935)が
初回 Multi-CN 生成で CN を構築 → **CN 挙動は保持・起動から後ろ倒し**しただけ。

**diff(05 追加分・要点):**
```python
# wrap 確認ブロック直後(初回 CN 生成で1回だけ)
pm = self.pm
if pm.pipe_cnet is not None and not getattr(pm, "_cnet_ipadapter_wired", False):
    ipa = self.ie.ip_adapter
    if getattr(pm.pipe_cnet, "image_encoder", None) is None and ipa is not None:
        pm.pipe_cnet.image_encoder = ipa._image_encoder
        pm.pipe_cnet.feature_extractor = ipa._feature_extractor
    if ipa is not None:
        ipa.set_scale(pm.pipe_cnet, IdentityConfig().ip_adapter_weight)   # Setting A 0.75
    pm._cnet_ipadapter_wired = True
```

**portrait byte 不変の根拠(再確認):**
- 本番 portrait = `_run_pass1`(plain `pm.pipe_base`)で **CN を一切通らない**。
- `04.auto_pulid_forward` は portrait(`id_embeddings` が kwargs にある)を `original_pulid_forward` へ
  **素通し** → forward wrap の有無で portrait 出力は同一バイト。
- `pipe_cnet` は scheduler を `pipe_base` から借用(04:742)→ **OSS hook(set_timesteps 上書き)は不変**。
- portrait の `pipe_base` IP-Adapter scale(Setting A 0.75)は notebook で **eager 維持**。
- 触ったのは CN(pipe_cnet)側のみ。pipe_base / 共有 transformer の構築結果は不変。
- **PC 検証で byte を直接確認はできない(Colab 不可)** → PO が同 seed/N14/Nika で前後 byte 一致を確認(下記)。

## C. warm 運用ガイド(DL ~111s/cold をスキップ)
notebook **[Cell-run] banner** に追記:
- VM を保持(クリーン再起動しない)→ モデルは /content(NVMe)に残り **PHASE1 DL skip**。
- さらに FastAPI 生存中なら冪等ガードで全 phase skip(蛇口だけ再 attach)= 数秒で復帰。
- cold(新 VM / クリーン再起動)の時だけ全 DL + build。

## 期待効果(見積もり・実数は PO 計測で確定)
- **warm 運用:** DL 111s + antelopev2 ~15s ≈ **~126s カット**(運用変更のみ)。
- **CN 遅延:** 起動から「03 CN model + ensure_controlnet(CN model+pipe_cnet)」分をカット(§A で実数確定)。
- 目安: **cold 6分 → 4分前後、warm 2〜3分**。

## 検証(PC 範囲)
- 4 core(03/04/05/07)`py_compile` 緑 / notebook 6 セル compile 緑。
- `tools/gen_manifest.py` 再生成 + `tools/check_manifest.py` 緑(desync なし)。
- 新規の silent-fail パターン(except 直後 pass)無し。diff は 03/04/05/07 + notebook + manifest のみ。

## 残(PO 実機・必須)
1. **byte 一致検証:** 高速化前(`gate1-green-20260627`)と後(`8ea4946`)で portrait 1 枚を
   **同 seed・N14・Nika refs** で生成 → **byte 一致**を確認。不一致なら revert(本コミット単独で revertible)。
2. **内訳確定:** cold run の `[BUILD-TIME]` 行を貼る → §A 表を実数化。
3. **CN 動作確認:** Multi-CN モードを 1 回 → 初回 lazy 構築ログ(`🔧 [Pass 1 CN] pipe_cnet に CN 専用
   IP-Adapter 配線完了`)+ CN 生成が従来どおり出ることを確認。
4. 高速化後の cold/warm 起動秒数を実測。

## 司令部判断が要る点
- **Redux prior 遅延**(recon_032 B・次点)は今回**見送り**(他 UI モードの使用未確認・独断 off にしない)。
  §A の `_build_redux_prior` 秒数が大きければ、別途モード調査の上で司令部判断。

新 tip: **`8ea4946`**(`origin/sync/colab`)。緑 tag: `gate1-green-20260627`。
