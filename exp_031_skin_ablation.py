# ═══════════════════════════════════════════════════════════════════════════
# EXP-031b: 肌質感アブレーション(GFPGAN を“実際に走らせて”再実験)
#   RECON-030 最有力容疑 = GFPGAN Phase3a の 512 warp 往復(高周波の肌ディテール喪失)
#
#   第1回の失敗: A も B も yaw 35.6° > 閾値 35.0° で **角度バイパス**(08:186)し、
#                GFPGAN が両方未適用=同条件 → 判定材料にならなかった。
#
#   本セル(差分): GFPGAN を確実に適用した A' を作る。
#     A' — 既存 skin_abl_B(raw diffusion, seed 12345, GFPGAN未適用)に GFPGAN を直適用。
#          → 全く同じ画像で「GFPGAN(512 warp 往復)だけの差」を純粋分離(再 diffusion 不要)。
#     B  — 既存 skin_abl_B_gfpgan_off.png を流用(GFPGAN無し = raw diffusion)。
#     C  — 別 runtime で単独実行(exp_031c_vanilla_flux.py)。本セルでは触らない(OOM 回避)。
#
#   ★純粋分離の要(コード実機確認・コメントでなく実処理):
#     - 角度ゲートは instance 属性 `fre.angle_bypass_yaw_deg`(08:186)。module override では効かない
#       → fre の instance を 90.0 に上書き(try/finally 復元)。
#     - GFPGAN 本体は `getattr(_cfg_mod,"PHASE3A_ENABLED")`(08:196)で gate → sys.modules を True 上書き。
#     - process() は GFPGAN-restored の **顔領域** を face_mask で原画へ合成(08:230 _alpha_blend)。
#       weight=GFPGAN_STRENGTH=0.0 / blend=1.0 のまま = RECON-030 主犯(weight非依存の 512 warp)を見る。
#
# 非改変の担保(prod 不変):
#   - GFPGAN gate / 角度ゲートは runtime in-memory override + try/finally で必ず復元。
#   - Setting A 7値・config 既定・production コードには一切触れない。
#
# 実行(Colab・orchestrator 起動済みセッションで):
#   exec(open("/content/drive/MyDrive/aibo_v7/exp_031_skin_ablation.py", encoding="utf-8").read())
# ═══════════════════════════════════════════════════════════════════════════
import os
import sys
import logging
import importlib
from importlib import import_module

from PIL import Image

# ── 共通条件(全条件で固定)──────────────────────────────────────────────
PROMPT = (
    "close-up portrait photo of a young woman, soft natural daylight, "
    "looking directly at camera, 85mm lens, photorealistic, sharp focus on face"
)
SEED = 12345
W, H = 1024, 1536
STEPS_AB = 8
GUIDANCE_AB = 4.0

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
PATH_B = os.path.join(OUT_DIR, "skin_abl_B_gfpgan_off.png")          # 既存流用(raw diffusion)
PATH_A = os.path.join(OUT_DIR, "skin_abl_A_gfpgan_applied.png")      # ★A'(GFPGAN 適用)
PATH_C = os.path.join(OUT_DIR, "skin_abl_C_vanilla_flux.png")        # 別 runtime で生成(あれば grid に載せる)
PATH_GRID = os.path.join(OUT_DIR, "skin_abl_GRID_ABC.png")

OBS_LINES = []


def _obs(line):
    OBS_LINES.append(line)
    print(line)


# ── 1. orchestrator + config 解決 ─────────────────────────────────────────
pm04 = import_module("04_pipeline_manager")
orch, _err = pm04._depth_find_orch(None)
assert orch is not None, f"[exp031b][STOP] {_err}"
pm = orch.pm

_og = getattr(orch.generate, "__globals__", {}) or {}
_cfg = import_module("01_config")
GenerationConfig = _og.get("GenerationConfig") or _cfg.GenerationConfig
IdentityConfig = _og.get("IdentityConfig") or _cfg.IdentityConfig
StudioMode = _og.get("StudioMode") or _cfg.StudioMode

# PHASE3A_ENABLED を読む module 群(05/08 とも import_module("01_config") = sys.modules 同一)。
_CFG_TARGETS = []
_cfg_canon = importlib.import_module("01_config")
_CFG_TARGETS.append(_cfg_canon)
assert _cfg_canon is sys.modules.get("01_config"), "[exp031b][STOP] 01_config が sys.modules と不一致"
try:
    _fr_mod = importlib.import_module("08_face_refiner")
    if getattr(_fr_mod, "_cfg_mod", None) is not None and _fr_mod._cfg_mod not in _CFG_TARGETS:
        _CFG_TARGETS.append(_fr_mod._cfg_mod)
except Exception as e:
    print(f"[exp031b] (warn) 08_face_refiner の _cfg_mod 取得失敗(継続): {e}")

os.makedirs(OUT_DIR, exist_ok=True)

# ── 構成の実値(後追い推定でなく実オブジェクトから)────────────────────────
_TF_CLS = type(getattr(pm, "transformer", None)).__name__
_BASE_CLS = type(getattr(pm, "pipe_base", None)).__name__
_GF_STR = getattr(_cfg_canon, "GFPGAN_STRENGTH", "?")
_P3B = getattr(_cfg_canon, "PHASE3B_ENABLED", "?")
print(f"[exp031b] 構成実値: transformer={_TF_CLS} pipe_base={_BASE_CLS} "
      f"GFPGAN_STRENGTH={_GF_STR} PHASE3B_ENABLED={_P3B}")
assert _P3B is False, f"[exp031b][STOP] PHASE3B_ENABLED={_P3B}(False 以外=厳守ルール違反/想定外)"


def _resolve_refs():
    """B 再生成が必要な時だけ呼ぶ(公式6枚・黙ったフォールバックなし)。"""
    assert len(REF_FILES) == 6, f"[exp031b][STOP] REF_FILES が6枚でない: {len(REF_FILES)}"
    _ref_paths = [os.path.join(FACE_DIR, f) for f in REF_FILES]
    _missing = [p for p in _ref_paths if not os.path.exists(p)]
    assert not _missing, f"[exp031b][STOP] 公式 ref 不足(フォールバックしない): {_missing}"
    return [Image.open(p).convert("RGB") for p in _ref_paths]


def _gen_b_raw():
    """B(GFPGAN無し raw diffusion)を quick path で生成(PHASE3A=False)。既存が無い時のみ。"""
    refs = _resolve_refs()
    _orig = [getattr(t, "PHASE3A_ENABLED", None) for t in _CFG_TARGETS]
    try:
        for t in _CFG_TARGETS:
            t.PHASE3A_ENABLED = False
        gen_cfg = GenerationConfig(prompt=PROMPT, width=W, height=H, seed=int(SEED))
        gen_cfg.num_inference_steps = STEPS_AB
        gen_cfg.guidance_scale = GUIDANCE_AB
        gen_cfg.enable_pass2 = False
        id_cfg = IdentityConfig(reference_image=refs[0], reference_images=list(refs))
        print(f"[exp031b] ▶ B(raw)生成中 … (PHASE3A=False, steps={STEPS_AB}, {W}x{H}, seed={SEED})")
        r = orch.generate(gen_cfg=gen_cfg, id_cfg=id_cfg, mode=StudioMode.PORTRAIT, save=False)
    finally:
        for t, v in zip(_CFG_TARGETS, _orig):
            if v is not None:
                t.PHASE3A_ENABLED = v
    assert r.error is None, f"[exp031b][STOP] B 生成失敗: {r.error}"
    assert r.final_image is not None, "[exp031b][STOP] B final_image=None"
    img = r.final_image.convert("RGB")
    img.save(PATH_B)
    _obs(f"[OBS] B gfpgan_off(regen) | steps={STEPS_AB} | gfpgan=OFF | quant={_TF_CLS} | "
         f"{W}x{H} | seed={SEED} | pass2=False")
    return img


def _apply_gfpgan_to_raw(raw_img):
    """A': raw 画像に GFPGAN を直適用(角度ゲート無効化 + PHASE3A=True・両方 try/finally 復元)。"""
    fre = getattr(orch, "face_restore_engine", None)
    assert fre is not None, "[exp031b][STOP] face_restore_engine 未初期化(GFPGAN 不可)"
    _orig_yaw = fre.angle_bypass_yaw_deg                       # instance 属性(08:186)
    _orig_p3a = [getattr(t, "PHASE3A_ENABLED", None) for t in _CFG_TARGETS]
    try:
        fre.angle_bypass_yaw_deg = 90.0                       # yaw 35.6 を通す(角度バイパス回避)
        for t in _CFG_TARGETS:
            t.PHASE3A_ENABLED = True                          # GFPGAN を確実に走らせる
        print(f"[exp031b] ▶ A': raw B に GFPGAN 直適用 … "
              f"(angle_bypass=90.0, PHASE3A_ENABLED=True, "
              f"gfpgan_strength={fre.gfpgan_strength}, blend={fre.gfpgan_blend})")
        res = fre.process(image=raw_img, debug_keep_intermediates=False)
    finally:
        fre.angle_bypass_yaw_deg = _orig_yaw                  # ★ 必ず復元
        for t, v in zip(_CFG_TARGETS, _orig_p3a):
            if v is not None:
                t.PHASE3A_ENABLED = v
    return res, fre


# ── 2. B(raw)を用意(既存流用・無ければ生成)──────────────────────────────
if os.path.exists(PATH_B):
    img_b = Image.open(PATH_B).convert("RGB")
    print(f"[exp031b] B 流用: {PATH_B}")
    _obs(f"[OBS] B gfpgan_off(reuse) | source={os.path.basename(PATH_B)} | gfpgan=OFF | {W}x{H} | seed={SEED}")
else:
    print(f"[exp031b] B 不在 → quick path で再生成: {PATH_B}")
    img_b = _gen_b_raw()

# ── 3. A' = GFPGAN を実適用 ───────────────────────────────────────────────
res, fre = _apply_gfpgan_to_raw(img_b)
_byp = getattr(res, "bypass_triggered", None)
_byp_r = getattr(res, "bypass_reason", "")
_p3a = getattr(res, "phase3a_applied", None)
_yaw = getattr(res, "yaw_deg", None)
_e3a = getattr(res, "elapsed_phase3a_sec", None)

# ★必須チェック(§2): GFPGAN が実際に適用されたか。未適用なら STOP(判定に進まない)。
_obs(f"[OBS] A' gfpgan_applied | source=skin_abl_B(raw,seed{SEED}) | "
     f"gfpgan={'APPLIED(512 align/warp/paste-back)' if (_p3a and not _byp) else 'NOT-APPLIED'} | "
     f"phase3a_applied={_p3a} bypass={_byp}({_byp_r}) yaw={_yaw} elapsed3a={_e3a}s | "
     f"strength={fre.gfpgan_strength} blend={fre.gfpgan_blend} | quant={_TF_CLS} | {W}x{H} | seed={SEED}")
assert (_p3a is True) and (not _byp), (
    f"[exp031b][STOP] A' で GFPGAN が適用されなかった(phase3a_applied={_p3a} bypass={_byp} "
    f"reason={_byp_r} yaw={_yaw})。別経路の bypass(顔検出失敗等)を疑い司令部へ報告。判定に進まない。"
)
img_a = res.final_image.convert("RGB")
img_a.save(PATH_A)
print(f"[exp031b] 保存: {PATH_A}")

# ── 4. 比較グリッド(A' / B (/ C があれば))────────────────────────────────
_items = [("A' gfpgan APPLIED", img_a), ("B gfpgan OFF (raw)", img_b)]
if os.path.exists(PATH_C):
    _items.append(("C vanilla FLUX (generic face)", Image.open(PATH_C).convert("RGB")))
else:
    _items.append(("C vanilla FLUX (run exp_031c separately)", None))
try:
    pm04._depth_grid(_items, PATH_GRID, ncols=3, show=True,
                     title="EXP-031b skin ablation A'/B/C (PO: compare pores / vellus hair / grain)")
    print(f"[exp031b] グリッド: {PATH_GRID}")
except Exception as e:
    print(f"[exp031b] (warn) グリッド生成失敗(継続): {e}")

# ── 5. まとめ(PO へ)──────────────────────────────────────────────────────
print("=" * 72)
print("[exp031b] 完了。PO への判定材料(結論は書かない):")
print("  毛穴・産毛・肌グレイン で A'(GFPGAN適用) と B(OFF) を目視比較してください。")
print(f"   A': {PATH_A}   (GFPGAN 適用)")
print(f"   B : {PATH_B}   (GFPGAN 無し・同一 raw)")
print(f"   C : {PATH_C}   (※別 runtime で exp_031c_vanilla_flux.py を実行・顔は別人)")
print(f"   GRID: {PATH_GRID}")
print("-" * 72)
print("[exp031b] [OBS] 実値ログ全文:")
for ln in OBS_LINES:
    print("   " + ln)
print("-" * 72)
print("[exp031b] 読み筋(§6・最終判定は PO 目視):")
print("   A'(GFPGAN適用) が B(OFF) より のっぺり → GFPGAN の 512 warp が主犯確定 → warp 回避修正へ")
print("   A' ≈ B(質感同じ)                      → GFPGAN は犯人でない → 生成段 #2(28step)/#4(pulid 0.3)")
print("   C ものっぺり                          → FLUX 素 or prompt → #5(texture prompt)")
print("=" * 72)
