# ═══════════════════════════════════════════════════════════════════════════
# EXP-032: 生成段アブレーション(ステップスイープ + PuLID)
#   前提: EXP-031b で GFPGAN はシロ確定(512 warp は肌に無影響)。容疑は生成段へ:
#         S1 = 8-step 蒸留(Hyper-FLUX) / S2 = INT4(Nunchaku) / S3 = PuLID。
#   目的: 肌のプラスチック化が生成段のどれか切り分け + 出荷できる sweet spot(step数)探索。
#
#   B  — 既存 skin_abl_B_gfpgan_off.png 流用(Hyper ON / 8step / g4.0 / PuLID0.7 = 現状)
#   D16 — Hyper OFF / 16step / g3.5 / PuLID0.7(中間・sweet spot 候補)
#   D28 — Hyper OFF / 28step / g3.5 / PuLID0.7(高ステップ・蒸留圧縮を外した素の denoise)
#   E03 — Hyper ON  / 8step  / g4.0 / PuLID0.3(顔スムージング寄与の診断)
#
#   ★runtime override(prod 不変・コード実機確認):
#     - Hyper-FLUX 無効化(D): Nunchaku は transformer.set_lora_strength() がグローバル
#       multiplier で Hyper のみ load(04:1189-1192)→ `_shared_transformer.set_lora_strength(0.0)`
#       で Hyper を無効化(scale 0)。try/finally で hyper_flux_weight に復元。
#     - steps(D): gen_cfg.num_inference_steps を明示 → resolved_steps はその値を使う(01:326)。
#       併せて sys_cfg.enable_hyper_flux=False で整合(復元)。pass1 は sigma 注入なし=steps/guidance のみ(05:779-793)。
#     - PuLID weight(E): id_cfg.pulid_weight → id_weight(05:805)。0.3 を per-run 上書き。
#
#   全条件 AIBO INT4 stack で 40GB に収まる(素 FLUX を出さない=OOM しない)。
#   GFPGAN は無関係と判明済み(この顔は yaw 35.6° で bypass されるが結果に無影響)→ 既定のまま放置。
#   Setting A 7値・config 既定・production コードには一切触れない。判定文は書かない(PO 目視)。
#
#   実行(Colab・orchestrator 起動済みセッションで):
#     exec(open("/content/drive/MyDrive/aibo_v7/exp_032_genstage_ablation.py", encoding="utf-8").read())
# ═══════════════════════════════════════════════════════════════════════════
import os
import sys
import importlib
from importlib import import_module

from PIL import Image

# ── 共通条件(EXP-031 と同一: prompt / seed / size / refs)──────────────────
PROMPT = (
    "close-up portrait photo of a young woman, soft natural daylight, "
    "looking directly at camera, 85mm lens, photorealistic, sharp focus on face"
)
SEED = 12345
W, H = 1024, 1536

FACE_DIR = "/content/drive/MyDrive/顔"
REF_FILES = [
    "Screenshot_20260414-124011.png",
    "Screenshot_20260414-124040.png",
    "Screenshot_20260414-124119.png",
    "Screenshot_20260414-124130.png",
    "Screenshot_20260414-124144.png",
    "Screenshot_20260510-150734.png",
]
OUT_DIR = "/content/drive/MyDrive/aibo_v7/experiments"
PATH_B = os.path.join(OUT_DIR, "skin_abl_B_gfpgan_off.png")     # 既存流用(現状ベースライン)
PATH_D16 = os.path.join(OUT_DIR, "skin_abl_D16_16step.png")
PATH_D28 = os.path.join(OUT_DIR, "skin_abl_D28_28step.png")
PATH_E = os.path.join(OUT_DIR, "skin_abl_E_pulid03.png")
PATH_GRID = os.path.join(OUT_DIR, "skin_abl_GRID_DE.png")

OBS_LINES = []


def _obs(line):
    OBS_LINES.append(line)
    print(line)


# ── 1. orchestrator + config 解決 ─────────────────────────────────────────
pm04 = import_module("04_pipeline_manager")
orch, _err = pm04._depth_find_orch(None)
assert orch is not None, f"[exp032][STOP] {_err}"
pm = orch.pm
sysc = orch.sys_cfg

_og = getattr(orch.generate, "__globals__", {}) or {}
_cfg = import_module("01_config")
GenerationConfig = _og.get("GenerationConfig") or _cfg.GenerationConfig
IdentityConfig = _og.get("IdentityConfig") or _cfg.IdentityConfig
StudioMode = _og.get("StudioMode") or _cfg.StudioMode

os.makedirs(OUT_DIR, exist_ok=True)

# Hyper-FLUX 無効化に使う transformer(Nunchaku は _shared_transformer に Hyper を load)
_TF = getattr(pm, "_shared_transformer", None) or getattr(pm, "transformer", None)
assert _TF is not None and hasattr(_TF, "set_lora_strength"), (
    "[exp032][STOP] transformer.set_lora_strength が使えない(Hyper 無効化不可)。INT4 stack か確認。"
)
_TF_CLS = type(_TF).__name__
_BASE_CLS = type(getattr(pm, "pipe_base", None)).__name__
_HYPER_W = float(getattr(sysc, "hyper_flux_weight", 0.125) or 0.125)   # 復元値(init 適用値)
print(f"[exp032] 構成実値: transformer={_TF_CLS} pipe_base={_BASE_CLS} "
      f"enable_hyper_flux={getattr(sysc,'enable_hyper_flux',None)} hyper_flux_weight={_HYPER_W}")

# ── 公式6枚(D/E は生成するので必須・黙ったフォールバックなし)────────────
assert len(REF_FILES) == 6, f"[exp032][STOP] REF_FILES が6枚でない: {len(REF_FILES)}"
_ref_paths = [os.path.join(FACE_DIR, f) for f in REF_FILES]
_missing = [p for p in _ref_paths if not os.path.exists(p)]
assert not _missing, f"[exp032][STOP] 公式 ref 不足(フォールバックしない): {_missing}"
refs = [Image.open(p).convert("RGB") for p in _ref_paths]
print("[exp032] 使用 ref(公式6枚・要 PO 確認):")
for p in _ref_paths:
    print(f"   - {os.path.basename(p)}")


def _gen(label, out_path, *, steps, guidance, pulid_weight, hyper_on):
    """1条件を生成。Hyper OFF 時は set_lora_strength(0) + enable_hyper_flux=False(両方 try/finally 復元)。"""
    _orig_enable = sysc.enable_hyper_flux
    try:
        if not hyper_on:
            _TF.set_lora_strength(0.0)                 # ★ Hyper-FLUX 無効化(scale 0)
            sysc.enable_hyper_flux = False             # resolved_steps / logging を整合

        gen_cfg = GenerationConfig(prompt=PROMPT, width=W, height=H, seed=int(SEED))
        gen_cfg.num_inference_steps = int(steps)       # 明示 → resolved_steps はこの値(01:326)
        gen_cfg.guidance_scale = float(guidance)
        gen_cfg.enable_pass2 = False                   # Pass2 OFF 明示
        id_cfg = IdentityConfig(reference_image=refs[0], reference_images=list(refs))
        id_cfg.pulid_weight = float(pulid_weight)      # per-run 上書き(config 既定 非接触)

        print(f"[exp032] ▶ {label}: 生成中 … hyper={'ON' if hyper_on else 'OFF(scale0)'} "
              f"steps={steps} guidance={guidance} pulid={pulid_weight} {W}x{H} seed={SEED}")
        r = orch.generate(gen_cfg=gen_cfg, id_cfg=id_cfg, mode=StudioMode.PORTRAIT, save=False)
    finally:
        if not hyper_on:
            _TF.set_lora_strength(_HYPER_W)            # ★ Hyper strength 復元
            sysc.enable_hyper_flux = _orig_enable

    assert r.error is None, f"[exp032][STOP] {label} 生成失敗: {r.error}"
    assert r.final_image is not None, f"[exp032][STOP] {label} final_image=None"
    img = r.final_image.convert("RGB")
    img.save(out_path)
    _obs(
        f"[OBS] {label} | steps={steps} | hyper={'ON' if hyper_on else 'OFF'} | "
        f"guidance={guidance} | pulid={pulid_weight} | quant={_TF_CLS} | {W}x{H} | seed={SEED} | "
        f"pulid_used={getattr(r,'pulid_used',None)} pulid_degraded={getattr(r,'pulid_degraded',None)} "
        f"phase3_applied={getattr(r,'phase3_applied',None)} pass2=False"
    )
    print(f"[exp032] 保存: {out_path}")
    return img


# ── 2. B(現状ベースライン)を流用 ──────────────────────────────────────────
if os.path.exists(PATH_B):
    img_b = Image.open(PATH_B).convert("RGB")
    print(f"[exp032] B 流用: {PATH_B}")
    _obs(f"[OBS] B baseline(reuse) | steps=8 | hyper=ON | guidance=4.0 | pulid=0.7 | "
         f"quant={_TF_CLS} | {W}x{H} | seed={SEED}")
else:
    _obs(f"[OBS] B 不在 | {PATH_B} が無い → EXP-031b を先に実行して B を作ってください")
    raise AssertionError(f"[exp032][STOP] B({PATH_B})が無い。EXP-031b で生成後に再実行。")

# ── 3. D16 / D28 / E03 を生成 ─────────────────────────────────────────────
img_d16 = _gen("D16", PATH_D16, steps=16, guidance=3.5, pulid_weight=0.7, hyper_on=False)
img_d28 = _gen("D28", PATH_D28, steps=28, guidance=3.5, pulid_weight=0.7, hyper_on=False)
img_e = _gen("E03", PATH_E, steps=8, guidance=4.0, pulid_weight=0.3, hyper_on=True)

# ── 4. 比較グリッド(B | D16 | D28 | E03)──────────────────────────────────
_items = [
    ("B base (8step hyper)", img_b),
    ("D16 (16step no-hyper)", img_d16),
    ("D28 (28step no-hyper)", img_d28),
    ("E03 (pulid 0.3)", img_e),
]
try:
    pm04._depth_grid(_items, PATH_GRID, ncols=4, show=True,
                     title="EXP-032 gen-stage A/B (PO: compare pores / vellus hair / grain)")
    print(f"[exp032] グリッド: {PATH_GRID}")
except Exception as e:
    print(f"[exp032] (warn) グリッド生成失敗(継続): {e}")

# ── 5. まとめ(PO へ)──────────────────────────────────────────────────────
print("=" * 72)
print("[exp032] 完了。PO への判定材料(結論は書かない):")
print("  毛穴・産毛・肌グレイン で B / D16 / D28 / E03 を目視比較してください。")
print(f"   B  : {PATH_B}")
print(f"   D16: {PATH_D16}")
print(f"   D28: {PATH_D28}")
print(f"   E03: {PATH_E}")
print(f"   GRID: {PATH_GRID}")
print("-" * 72)
print("[exp032] 注意(§3):")
print("   E03(PuLID 0.3)は『診断』で『修正案』ではない。PuLID を下げると Nika の顔同一性も弱まる")
print("   (顔が別人寄りになる)。肌が戻るか“だけ”を見る材料。identity トレードオフは別判断。")
print("   D16/D28 は Hyper-FLUX OFF で生成が遅い(8→16/28step)。戻れば sweet spot を後で決める。")
print("-" * 72)
print("[exp032] [OBS] 実値ログ全文:")
for ln in OBS_LINES:
    print("   " + ln)
print("-" * 72)
print("[exp032] 読み筋(§4・最終判定は PO 目視):")
print("   D28(or D16)で毛穴が戻る / B はのっぺり → 8-step 蒸留が主因 → step 増(sweet spot=D16 で戻れば安い)")
print("   E03 で毛穴が戻る                     → PuLID スムージング寄与 → weight↔同一性トレードオフ(or σ-gate 復活)")
print("   どれも B と同じ(全部のっぺり)        → 残るは INT4(S2)→ bf16 比較は 80GB で別途(#3)")
print("   D も E も戻る                         → 複合 → 効いた順に組合せ")
print("=" * 72)
