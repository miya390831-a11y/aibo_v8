# ═══════════════════════════════════════════════════════════════════════════
# EXP-032b Part① — E03(PuLID 0.3)・現スタックで即実行
#   前提: EXP-032 の set_lora_strength(0) は Nunchaku の load_state_dict(strict=True) が
#         PuLID-graft の pulid_ca.* で落ちる(Missing keys)→ ★set_lora_strength は一切使わない。
#   E03 は set_lora_strength を通らない(id_cfg.pulid_weight 上書きのみ)→ 現スタックで回せる。
#
#   E03 — Hyper ON / 8step / g4.0 / PuLID 0.3(顔スムージング寄与の診断)
#   B   — 既存 skin_abl_B_gfpgan_off.png 流用(Hyper ON / 8step / g4.0 / PuLID 0.7 = 現状)
#
#   ★PuLID weight は id_cfg.pulid_weight → id_weight(05:805)で forward 毎に読まれる per-run 値。
#     config 既定(0.7)は非接触。set_lora_strength 不使用。
#   ⚠ E03 は『診断』であって『修正案』ではない。PuLID を下げると Nika の顔同一性も薄まる
#     (顔が別人寄りになる)。肌が戻るか“だけ”を見る材料。identity トレードオフは別判断。
#
#   実行(Colab・orchestrator 起動済み=現行スタックのセッションで):
#     exec(open("/content/drive/MyDrive/aibo_v7/exp_032b_E03.py", encoding="utf-8").read())
# ═══════════════════════════════════════════════════════════════════════════
import os
from importlib import import_module

from PIL import Image

PROMPT = (
    "close-up portrait photo of a young woman, soft natural daylight, "
    "looking directly at camera, 85mm lens, photorealistic, sharp focus on face"
)
SEED = 12345
W, H = 1024, 1536
STEPS = 8
GUIDANCE = 4.0
PULID_E = 0.3

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
PATH_B = os.path.join(OUT_DIR, "skin_abl_B_gfpgan_off.png")
PATH_E = os.path.join(OUT_DIR, "skin_abl_E_pulid03.png")
PATH_GRID = os.path.join(OUT_DIR, "skin_abl_GRID_E.png")

OBS_LINES = []


def _obs(line):
    OBS_LINES.append(line)
    print(line)


# ── 1. orchestrator + config 解決 ─────────────────────────────────────────
pm04 = import_module("04_pipeline_manager")
orch, _err = pm04._depth_find_orch(None)
assert orch is not None, f"[exp032bE][STOP] {_err}"
pm = orch.pm
sysc = orch.sys_cfg

_og = getattr(orch.generate, "__globals__", {}) or {}
_cfg = import_module("01_config")
GenerationConfig = _og.get("GenerationConfig") or _cfg.GenerationConfig
IdentityConfig = _og.get("IdentityConfig") or _cfg.IdentityConfig
StudioMode = _og.get("StudioMode") or _cfg.StudioMode

os.makedirs(OUT_DIR, exist_ok=True)
_TF_CLS = type(getattr(pm, "_shared_transformer", None) or getattr(pm, "transformer", None)).__name__
print(f"[exp032bE] 構成実値: transformer={_TF_CLS} "
      f"enable_hyper_flux={getattr(sysc,'enable_hyper_flux',None)} "
      f"pulid_w(config既定)={IdentityConfig().pulid_weight}")

# ── 公式6枚 ────────────────────────────────────────────────────────────────
assert len(REF_FILES) == 6, f"[exp032bE][STOP] REF_FILES が6枚でない: {len(REF_FILES)}"
_ref_paths = [os.path.join(FACE_DIR, f) for f in REF_FILES]
_missing = [p for p in _ref_paths if not os.path.exists(p)]
assert not _missing, f"[exp032bE][STOP] 公式 ref 不足(フォールバックしない): {_missing}"
refs = [Image.open(p).convert("RGB") for p in _ref_paths]

# ── 2. B 流用 ──────────────────────────────────────────────────────────────
assert os.path.exists(PATH_B), f"[exp032bE][STOP] B 不在: {PATH_B}(EXP-031b で先に生成)"
img_b = Image.open(PATH_B).convert("RGB")
print(f"[exp032bE] B 流用: {PATH_B}")
_obs(f"[OBS] B baseline(reuse) | steps=8 | hyper=ON | guidance=4.0 | pulid=0.7 | "
     f"quant={_TF_CLS} | {W}x{H} | seed={SEED}")

# ── 3. E03 = PuLID 0.3(per-run 上書きのみ・set_lora_strength 不使用)─────────
gen_cfg = GenerationConfig(prompt=PROMPT, width=W, height=H, seed=int(SEED))
gen_cfg.num_inference_steps = STEPS
gen_cfg.guidance_scale = GUIDANCE
gen_cfg.enable_pass2 = False
id_cfg = IdentityConfig(reference_image=refs[0], reference_images=list(refs))
id_cfg.pulid_weight = float(PULID_E)               # ★ per-run のみ(config 既定 0.7 は非接触)
print(f"[exp032bE] ▶ E03: 生成中 … hyper=ON steps={STEPS} guidance={GUIDANCE} "
      f"pulid={PULID_E} {W}x{H} seed={SEED}")
r = orch.generate(gen_cfg=gen_cfg, id_cfg=id_cfg, mode=StudioMode.PORTRAIT, save=False)
assert r.error is None, f"[exp032bE][STOP] E03 生成失敗: {r.error}"
assert r.final_image is not None, "[exp032bE][STOP] E03 final_image=None"
img_e = r.final_image.convert("RGB")
img_e.save(PATH_E)
_obs(f"[OBS] E03 pulid03 | steps={STEPS} | hyper=ON | guidance={GUIDANCE} | pulid={PULID_E} | "
     f"quant={_TF_CLS} | {W}x{H} | seed={SEED} | "
     f"pulid_used={getattr(r,'pulid_used',None)} pulid_degraded={getattr(r,'pulid_degraded',None)} "
     f"phase3_applied={getattr(r,'phase3_applied',None)} pass2=False")
print(f"[exp032bE] 保存: {PATH_E}")

# ── 4. グリッド(B | E03)──────────────────────────────────────────────────
try:
    pm04._depth_grid([("B base (pulid 0.7)", img_b), ("E03 (pulid 0.3)", img_e)],
                     PATH_GRID, ncols=2, show=True,
                     title="EXP-032b E03 (PO: compare pores / vellus hair / grain)")
    print(f"[exp032bE] グリッド: {PATH_GRID}")
except Exception as e:
    print(f"[exp032bE] (warn) グリッド生成失敗(継続): {e}")

# ── 5. まとめ(PO へ)──────────────────────────────────────────────────────
print("=" * 72)
print("[exp032bE] 完了。PO への判定材料(結論は書かない):")
print("  毛穴・産毛・肌グレイン で B(pulid0.7) と E03(pulid0.3) を目視比較してください。")
print(f"   B  : {PATH_B}")
print(f"   E03: {PATH_E}")
print(f"   GRID: {PATH_GRID}")
print("-" * 72)
print("[exp032bE] 注意: E03 は『診断』で『修正案』ではない。PuLID 下げ=Nika の顔同一性も薄まる")
print("            (顔が別人寄り)。肌が戻るか“だけ”を見る材料。identity トレードオフは別判断。")
print("[exp032bE] [OBS] 実値ログ全文:")
for ln in OBS_LINES:
    print("   " + ln)
print("[exp032bE] 読み筋(§4): E03 で毛穴回復 → PuLID スムージング寄与 → weight↔同一性トレードオフ判断")
print("=" * 72)
