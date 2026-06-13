# ═══════════════════════════════════════════════════════════════════════════
# EXP-031: 肌質感アブレーション(GFPGAN Phase3a 主犯検証)
#   RECON-030 最有力容疑 = GFPGAN Phase3a の 512 warp 往復(高周波の肌ディテール喪失)
#
#   3条件を同一条件で生成し、3枚 + [OBS] 実値ログを PO に返す。判定は書かない(PO の目視)。
#     A — 現行 AIBO(GFPGAN Phase3a ON)                … プラスチックな現状ベースライン
#     B — AIBO + GFPGAN OFF(PHASE3A_ENABLED=False)    … ★主犯検証(A と同経路・gate だけ切替)
#     C — 素 FLUX.1-dev(no PuLID / no Hyper / no INT4 / no Phase3) … 肌高周波の天井(generic 顔)
#
#   ★コード実機確認(08_face_refiner.py を読んで判明・コメントではなく実処理):
#     - _apply_gfpgan は GFPGANer.enhance(has_aligned=False, paste_back=True) を呼ぶ。
#       これは 顔検出→512 整列クロップ→復元→逆 warp 貼り戻し の往復で、weight(=GFPGAN_STRENGTH=0.0)
#       に関係なく **512 リサンプルが走る**(08:336-343)。
#     - gfpgan_blend=1.0(既定)では `return restored_pil`(=往復後の画像)を返す(08:351-352)。
#     → A は strength 0 でも「512 往復後の画像」、B は raw diffusion 画像。A/B 差分 = 512 warp 往復そのもの。
#
# 非改変の担保(prod 不変):
#   - GFPGAN gate は runtime in-memory override + try/finally で必ず復元(01_config.py は書き換えない)。
#   - Setting A 7値・config 既定・production コードには一切触れない(本実験の knob は全て Setting A 外)。
#   - per-run の GenerationConfig / IdentityConfig 構築のみ(diag_stage_cell / exp_cn_* と同じ作法)。
#
# 40GB 運用: A・B は同 stack 使い回し → 解放してから C(del + empty_cache + gc.collect())。
#
# 実行(Colab・orchestrator 起動済み=UI で1枚生成済みのセッションで):
#   exec(open("/content/drive/MyDrive/aibo_v7/exp_031_skin_ablation.py", encoding="utf-8").read())
# ═══════════════════════════════════════════════════════════════════════════
import os
import gc
import sys
import logging
import importlib
from importlib import import_module

from PIL import Image

# ── 共通条件(§3 · 全条件で固定)──────────────────────────────────────────
PROMPT = (
    "close-up portrait photo of a young woman, soft natural daylight, "
    "looking directly at camera, 85mm lens, photorealistic, sharp focus on face"
)
SEED = 12345
W, H = 1024, 1536          # 現行 portrait
STEPS_AB = 8               # A/B: 現行 quick path(Hyper-FLUX 8step)
GUIDANCE_AB = 4.0          # UI 既定 CFG=4
STEPS_C = 28               # C: 素 FLUX フルステップ
GUIDANCE_C = 3.5           # C: FLUX 蒸留 guidance

FACE_DIR = "/content/drive/MyDrive/顔"
# 公式 Nika 6枚を名前で固定(先頭6枚ソート等の黙ったフォールバックはしない=identity 無意味化防止)
REF_FILES = [
    "Screenshot_20260414-124011.png",
    "Screenshot_20260414-124040.png",
    "Screenshot_20260414-124119.png",
    "Screenshot_20260414-124130.png",
    "Screenshot_20260414-124144.png",
    "Screenshot_20260510-150734.png",
]
OUT_DIR = "/content/drive/MyDrive/aibo_v7/experiments"
PATH_A = os.path.join(OUT_DIR, "skin_abl_A_aibo.png")
PATH_B = os.path.join(OUT_DIR, "skin_abl_B_gfpgan_off.png")
PATH_C = os.path.join(OUT_DIR, "skin_abl_C_vanilla_flux.png")
PATH_GRID = os.path.join(OUT_DIR, "skin_abl_GRID_ABC.png")

OBS_LINES = []  # 実値ログ集約(末尾でまとめて再掲 → PO へ)


def _obs(line):
    OBS_LINES.append(line)
    print(line)


# ── 1. orchestrator + config 解決(exp_cn_* / diag_stage と同じ作法)────────
pm04 = import_module("04_pipeline_manager")
orch, _err = pm04._depth_find_orch(None)
assert orch is not None, f"[exp031][STOP] {_err}"
pm = orch.pm

_og = getattr(orch.generate, "__globals__", {}) or {}
_cfg = import_module("01_config")
GenerationConfig = _og.get("GenerationConfig") or _cfg.GenerationConfig
IdentityConfig = _og.get("IdentityConfig") or _cfg.IdentityConfig
StudioMode = _og.get("StudioMode") or _cfg.StudioMode

# GFPGAN gate を読む module 群(05/08 とも import_module("01_config") = sys.modules 同一オブジェクト)。
# 二重ロード保険として 08 の module-level _cfg_mod にも同じ override をかける。
_CFG_TARGETS = []
_cfg_canon = importlib.import_module("01_config")
_CFG_TARGETS.append(_cfg_canon)
assert _cfg_canon is sys.modules.get("01_config"), "[exp031][STOP] 01_config が sys.modules と不一致"
try:
    _fr = importlib.import_module("08_face_refiner")
    if getattr(_fr, "_cfg_mod", None) is not None and _fr._cfg_mod not in _CFG_TARGETS:
        _CFG_TARGETS.append(_fr._cfg_mod)
except Exception as e:
    print(f"[exp031] (warn) 08_face_refiner の _cfg_mod 取得失敗(継続): {e}")

# ── 2. 公式6枚の解決(名前固定・黙ったフォールバックなし)──────────────────
assert len(REF_FILES) == 6, f"[exp031][STOP] REF_FILES が6枚でない: {len(REF_FILES)}"
_ref_paths = [os.path.join(FACE_DIR, f) for f in REF_FILES]
_missing = [p for p in _ref_paths if not os.path.exists(p)]
assert not _missing, f"[exp031][STOP] 公式 ref 不足(フォールバックしない): {_missing}"
refs = [Image.open(p).convert("RGB") for p in _ref_paths]
print("[exp031] 使用 ref(公式6枚・要 PO 確認):")
for p in _ref_paths:
    print(f"   - {os.path.basename(p)}")
os.makedirs(OUT_DIR, exist_ok=True)

# ── 構成の実値(後追い推定でなく実オブジェクトから)────────────────────────
_TF_CLS = type(getattr(pm, "transformer", None)).__name__       # Nunchaku INT4 なら NunchakuFlux... 系
_BASE_CLS = type(getattr(pm, "pipe_base", None)).__name__        # PuLIDFluxPipeline 系
_PULID_W = float(IdentityConfig().pulid_weight)                  # config 既定(per-run override しない)
_HYPER = getattr(getattr(orch, "sys_cfg", None), "enable_hyper_flux", "?")
_GF_STR = getattr(_cfg_canon, "GFPGAN_STRENGTH", "?")
_GF_BLEND = getattr(_cfg_canon, "GFPGAN_BLEND", getattr(_cfg_canon, "gfpgan_blend", "?"))
_P3B = getattr(_cfg_canon, "PHASE3B_ENABLED", "?")
print(
    f"[exp031] 構成実値: transformer={_TF_CLS} pipe_base={_BASE_CLS} "
    f"pulid_w(既定)={_PULID_W} hyper_flux={_HYPER} "
    f"GFPGAN_STRENGTH={_GF_STR} GFPGAN_BLEND={_GF_BLEND} PHASE3B_ENABLED={_P3B}"
)
# §8: Pass2/Phase3b/upscale が誤って有効でないことの事前確認
assert _P3B is False, f"[exp031][STOP] PHASE3B_ENABLED={_P3B}(False 以外=厳守ルール違反/想定外)"


def _gen_aibo(label, out_path, phase3a_enabled):
    """A/B 共通: 現行 quick path を1回実行。GFPGAN gate のみ runtime override + 復元。"""
    _orig = [getattr(t, "PHASE3A_ENABLED", None) for t in _CFG_TARGETS]
    try:
        for t in _CFG_TARGETS:
            t.PHASE3A_ENABLED = bool(phase3a_enabled)

        gen_cfg = GenerationConfig(prompt=PROMPT, width=W, height=H, seed=int(SEED))
        gen_cfg.num_inference_steps = STEPS_AB
        gen_cfg.guidance_scale = GUIDANCE_AB
        gen_cfg.enable_pass2 = False                         # §8: Pass2 OFF を明示固定
        id_cfg = IdentityConfig(reference_image=refs[0], reference_images=list(refs))

        # gate の実効値(override 後・gen 直前)を実値で記録
        _eff_gate = getattr(_cfg_canon, "PHASE3A_ENABLED", None)
        print(f"[exp031] ▶ {label}: 生成中 … (PHASE3A_ENABLED={_eff_gate}, steps={STEPS_AB}, "
              f"guidance={GUIDANCE_AB}, {W}x{H}, seed={SEED})")
        r = orch.generate(gen_cfg=gen_cfg, id_cfg=id_cfg, mode=StudioMode.PORTRAIT, save=False)
    finally:
        for t, v in zip(_CFG_TARGETS, _orig):
            if v is not None:
                t.PHASE3A_ENABLED = v                        # ★ 必ず復元(prod ファイル不変)

    assert r.error is None, f"[exp031][STOP] {label} 生成失敗: {r.error}"
    assert r.final_image is not None, f"[exp031][STOP] {label} final_image=None"
    img = r.final_image.convert("RGB")
    img.save(out_path)

    _gate_str = "ON" if phase3a_enabled else "OFF(runtime)"
    _p3 = getattr(r, "phase3_applied", None)
    _byp = getattr(r, "phase3_bypass_triggered", None)
    _byp_r = getattr(r, "phase3_bypass_reason", "")
    _yaw = getattr(r, "phase3_yaw_deg", None)
    _obs(
        f"[OBS] {label} | steps={STEPS_AB} | gfpgan={_gate_str} | "
        f"quant={_TF_CLS} | pulid={_PULID_W} | {W}x{H} | seed={SEED} | "
        f"phase3_applied={_p3} bypass={_byp}({_byp_r}) yaw={_yaw} | "
        f"GFPGAN_STRENGTH={_GF_STR} blend={_GF_BLEND} | pass2=False | "
        f"neg={gen_cfg.negative_prompt!r}"
    )
    print(f"[exp031] 保存: {out_path}")
    return img


def _free_prod_stack():
    """C 前に A/B prod stack を解放(40GB に2 stack は載らない)。VRAM 実値を印字。"""
    import torch
    before = torch.cuda.memory_allocated() / 1e9 if torch.cuda.is_available() else 0.0
    for attr in ["pipe_base", "pipe_i2i", "pipe_fill", "pipe_prior", "pipe_cnet"]:
        p = getattr(pm, attr, None)
        if p is not None:
            try:
                p.to("cpu")
            except Exception:
                pass
            setattr(pm, attr, None)
    for attr in ["_shared_vae", "_shared_transformer", "transformer"]:
        if getattr(pm, attr, None) is not None:
            setattr(pm, attr, None)
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()
    after = torch.cuda.memory_allocated() / 1e9 if torch.cuda.is_available() else 0.0
    free_gb = 0.0
    if torch.cuda.is_available():
        free_b, total_b = torch.cuda.mem_get_info()
        free_gb = free_b / 1e9
    _obs(f"[OBS] stack-free | VRAM allocated {before:.2f}GB -> {after:.2f}GB | free={free_gb:.2f}GB")
    return free_gb


def _gen_vanilla_flux(out_path):
    """C: 素 FLUX.1-dev(PuLID 無し=generic 顔。見るのは毛穴/グレインのみ・identity 比較ではない)。"""
    import torch
    from diffusers import FluxPipeline
    pipe_c = FluxPipeline.from_pretrained(
        "black-forest-labs/FLUX.1-dev", torch_dtype=torch.bfloat16
    ).to("cuda")
    _obs(
        f"[OBS] C vanilla-FLUX | steps={STEPS_C} | guidance={GUIDANCE_C} | "
        f"no-PuLID no-Hyper no-INT4 no-Phase3 | {W}x{H} | seed={SEED}"
    )
    img_c = pipe_c(
        prompt=PROMPT,
        height=H, width=W,
        num_inference_steps=STEPS_C, guidance_scale=GUIDANCE_C,
        generator=torch.Generator("cuda").manual_seed(SEED),
    ).images[0]
    img_c = img_c.convert("RGB")
    img_c.save(out_path)
    print(f"[exp031] 保存: {out_path}")
    # C stack も解放(後続セルのため)
    try:
        del pipe_c
    except Exception:
        pass
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
    return img_c


# ── 3. 実行(A → B → 解放 → C)────────────────────────────────────────────
img_a = _gen_aibo("A aibo", PATH_A, phase3a_enabled=True)
img_b = _gen_aibo("B gfpgan_off", PATH_B, phase3a_enabled=False)

img_c = None
free_gb = _free_prod_stack()
try:
    import torch  # noqa: F401
    img_c = _gen_vanilla_flux(PATH_C)
except Exception as e:  # OOM 等
    _obs(f"[OBS] C SKIPPED | 理由={type(e).__name__}: {e}")
    print("[exp031] ⚠ C(素 FLUX)が失敗。新しい runtime で C のみ単独実行を推奨:")
    print("   from diffusers import FluxPipeline; import torch")
    print("   pipe=FluxPipeline.from_pretrained('black-forest-labs/FLUX.1-dev',")
    print("        torch_dtype=torch.bfloat16).to('cuda')")
    print(f"   pipe(prompt={PROMPT!r}, height={H}, width={W}, num_inference_steps={STEPS_C},")
    print(f"        guidance_scale={GUIDANCE_C},")
    print(f"        generator=torch.Generator('cuda').manual_seed({SEED})).images[0].save({PATH_C!r})")

# ── 4. 比較グリッド(任意・PO 目視用 ASCII ラベル)────────────────────────
_items = [("A aibo (gfpgan ON)", img_a), ("B gfpgan OFF", img_b),
          ("C vanilla FLUX (generic face)", img_c)]
try:
    pm04._depth_grid(_items, PATH_GRID, ncols=3, show=True,
                     title="EXP-031 skin ablation A/B/C (PO: compare pores / vellus hair / grain)")
    print(f"[exp031] グリッド: {PATH_GRID}")
except Exception as e:
    print(f"[exp031] (warn) グリッド生成失敗(継続): {e}")

# ── 5. まとめ(PO へ)──────────────────────────────────────────────────────
print("=" * 72)
print("[exp031] 完了。PO への判定材料(結論は書かない):")
print("  3枚を 毛穴・産毛・肌グレイン で目視比較してください。")
print(f"   A: {PATH_A}")
print(f"   B: {PATH_B}")
print(f"   C: {PATH_C}  (※顔は別人=generic。見るのは肌の質感だけ)")
print(f"   GRID: {PATH_GRID}")
print("-" * 72)
print("[exp031] [OBS] 実値ログ全文:")
for ln in OBS_LINES:
    print("   " + ln)
print("-" * 72)
print("[exp031] 読み筋(§6・最終判定は PO 目視):")
print("   B が A より明確に毛穴回復 → GFPGAN(512 warp 往復)が主犯 → 次手: warp 回避修正")
print("   B もプラスチック / C は良い → 生成段(8step/INT4/PuLID)→ 次バッチ #2(28step)/#4(pulid 0.3)")
print("   C もプラスチック        → FLUX 素 or prompt 側 → #5(texture prompt 注入)")
print("=" * 72)
