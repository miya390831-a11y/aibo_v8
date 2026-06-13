# ═══════════════════════════════════════════════════════════════════════════
# EXP-032b Part② — D16 / D28(Hyper-FLUX を“最初から載せない”構築で実行)
#   前提: set_lora_strength(0) は Nunchaku strict load が pulid_ca.* で落ちる → ★使わない。
#         Hyper を後から切るのではなく、enable_hyper_flux=False で **Hyper 未ロードのスタック**を作る。
#
#   D16 — Hyper 未ロード / 16step / g3.5 / PuLID 0.7
#   D28 — Hyper 未ロード / 28step / g3.5 / PuLID 0.7
#   B   — 既存 skin_abl_B_gfpgan_off.png 流用
#
# ─────────────────────────────────────────────────────────────────────────
# ★実行手順(必ずこの順・別 fresh runtime・各ステップ 1行 exec):
#   1) ランタイム再起動:
#        import os; os.kill(os.getpid(), 9)
#   2) 再起動後、**Cell 0 / setup を走らせる前に** prebuild を実行(Hyper を載せない構築にする):
#        exec(open("/content/drive/MyDrive/aibo_v7/exp_032b_prebuild.py", encoding="utf-8").read())
#      (= SystemConfig 既定を enable_hyper_flux=False / hyper_flux_weight=0.0 に書換 + 自己検証)
#   3) Cell 0 / setup を実行(= Hyper 未ロードのスタックが構築される)。
#   4) 本セルを実行:
#        exec(open("/content/drive/MyDrive/aibo_v7/exp_032b_DnoHyper.py", encoding="utf-8").read())
#
#   ★本セルは Hyper が実際に未ロードであることを冒頭で検証し、載っていたら STOP(別経路ロード疑い)。
#   VRAM: no-Hyper INT4 PuLID は ~24GB で 40GB に収まる。set_lora_strength は一切使わない。
#   Setting A 7値・config 既定・production コードには触れない(prebuild は in-memory のみ)。判定は PO 目視。
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
GUIDANCE = 3.5
PULID = 0.7

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
PATH_D16 = os.path.join(OUT_DIR, "skin_abl_D16_16step.png")
PATH_D28 = os.path.join(OUT_DIR, "skin_abl_D28_28step.png")
PATH_GRID = os.path.join(OUT_DIR, "skin_abl_GRID_D.png")

OBS_LINES = []


def _obs(line):
    OBS_LINES.append(line)
    print(line)


# ── 1. orchestrator + config 解決 ─────────────────────────────────────────
pm04 = import_module("04_pipeline_manager")
orch, _err = pm04._depth_find_orch(None)
assert orch is not None, f"[exp032bD][STOP] {_err}"
pm = orch.pm
sysc = orch.sys_cfg

_og = getattr(orch.generate, "__globals__", {}) or {}
_cfg = import_module("01_config")
GenerationConfig = _og.get("GenerationConfig") or _cfg.GenerationConfig
IdentityConfig = _og.get("IdentityConfig") or _cfg.IdentityConfig
StudioMode = _og.get("StudioMode") or _cfg.StudioMode

os.makedirs(OUT_DIR, exist_ok=True)
_TF_CLS = type(getattr(pm, "_shared_transformer", None) or getattr(pm, "transformer", None)).__name__

# ── 2. ★必須検証: Hyper が未ロードか(載っていたら STOP)──────────────────
_loaded = getattr(pm, "_hyper_flux_loaded", None)        # _inject_hyper_flux_* でのみ True(04:1193)
_enable = getattr(sysc, "enable_hyper_flux", None)
_obs(f"[OBS] prebuild-check | _hyper_flux_loaded={_loaded} | enable_hyper_flux={_enable} | "
     f"hyper_flux_weight={getattr(sysc,'hyper_flux_weight',None)} | transformer={_TF_CLS}")
assert _loaded is not True, (
    f"[exp032bD][STOP] Hyper-FLUX が既にロードされている(_hyper_flux_loaded={_loaded})。"
    "別経路でロードされた疑い → 司令部へ報告。判定に進まない。"
    "(手順2の prebuild override を Cell 0 の前に実行したか確認)"
)
assert _enable is not True, (
    f"[exp032bD][STOP] enable_hyper_flux={_enable}(True)。no-Hyper 構築になっていない → 報告。"
)

# ── 公式6枚 ────────────────────────────────────────────────────────────────
assert len(REF_FILES) == 6, f"[exp032bD][STOP] REF_FILES が6枚でない: {len(REF_FILES)}"
_ref_paths = [os.path.join(FACE_DIR, f) for f in REF_FILES]
_missing = [p for p in _ref_paths if not os.path.exists(p)]
assert not _missing, f"[exp032bD][STOP] 公式 ref 不足(フォールバックしない): {_missing}"
refs = [Image.open(p).convert("RGB") for p in _ref_paths]

# ── B 流用 ─────────────────────────────────────────────────────────────────
assert os.path.exists(PATH_B), f"[exp032bD][STOP] B 不在: {PATH_B}(EXP-031b で先に生成)"
img_b = Image.open(PATH_B).convert("RGB")
_obs(f"[OBS] B baseline(reuse) | steps=8 | hyper=ON | guidance=4.0 | pulid=0.7 | "
     f"quant={_TF_CLS} | {W}x{H} | seed={SEED}")


def _health_warn(label, img):
    """崩れ/単色の粗い検知(PO の最終目視の補助)。低 stddev は崩れ/真っ黒の疑い。"""
    try:
        from PIL import ImageStat
        st = ImageStat.Stat(img.convert("RGB"))
        sd = sum(st.stddev) / len(st.stddev)
        if sd < 8.0:
            print(f"[exp032bD][WARN] {label}: 画像 stddev={sd:.1f} が低い → 崩れ/単色の疑い。PO 確認必須。")
        return round(sd, 1)
    except Exception:
        return None


def _gen_d(label, out_path, steps):
    """D 条件を生成(set_lora_strength 不使用・Hyper 未ロード前提・steps は明示で resolved=その値)。"""
    gen_cfg = GenerationConfig(prompt=PROMPT, width=W, height=H, seed=int(SEED))
    gen_cfg.num_inference_steps = int(steps)       # 明示 → resolved_steps はこの値(01:326)
    gen_cfg.guidance_scale = float(GUIDANCE)
    gen_cfg.enable_pass2 = False
    id_cfg = IdentityConfig(reference_image=refs[0], reference_images=list(refs))
    id_cfg.pulid_weight = float(PULID)
    print(f"[exp032bD] ▶ {label}: 生成中 … hyper=OFF(not loaded) steps={steps} "
          f"guidance={GUIDANCE} pulid={PULID} {W}x{H} seed={SEED}")
    r = orch.generate(gen_cfg=gen_cfg, id_cfg=id_cfg, mode=StudioMode.PORTRAIT, save=False)
    assert r.error is None, f"[exp032bD][STOP] {label} 生成失敗: {r.error}"
    assert r.final_image is not None, f"[exp032bD][STOP] {label} final_image=None"
    img = r.final_image.convert("RGB")
    img.save(out_path)
    sd = _health_warn(label, img)
    _obs(f"[OBS] {label} | steps={steps} | hyper=OFF(not loaded) | guidance={GUIDANCE} | "
         f"pulid={PULID} | quant={_TF_CLS} | {W}x{H} | seed={SEED} | stddev={sd} | "
         f"pulid_used={getattr(r,'pulid_used',None)} phase3_applied={getattr(r,'phase3_applied',None)} pass2=False")
    print(f"[exp032bD] 保存: {out_path}")
    return img


# ── 3. D16 / D28 生成 ─────────────────────────────────────────────────────
img_d16 = _gen_d("D16", PATH_D16, 16)
img_d28 = _gen_d("D28", PATH_D28, 28)

# ── 4. グリッド(B | D16 | D28)────────────────────────────────────────────
try:
    pm04._depth_grid(
        [("B base (8step hyper)", img_b), ("D16 (16step no-hyper)", img_d16),
         ("D28 (28step no-hyper)", img_d28)],
        PATH_GRID, ncols=3, show=True,
        title="EXP-032b D no-hyper (PO: compare pores / vellus hair / grain)")
    print(f"[exp032bD] グリッド: {PATH_GRID}")
except Exception as e:
    print(f"[exp032bD] (warn) グリッド生成失敗(継続): {e}")

# ── 5. まとめ(PO へ)──────────────────────────────────────────────────────
print("=" * 72)
print("[exp032bD] 完了。PO への判定材料(結論は書かない):")
print("  ★まず出力健全性: D16/D28 が綺麗な高ステップ絵か(崩れ/過蒸留でないか)を確認。")
print("    崩れていたら判定に進まず [OBS](stddev 等)付きで報告してください。")
print("  健全なら 毛穴・産毛・肌グレイン で B / D16 / D28 を目視比較。")
print(f"   B  : {PATH_B}")
print(f"   D16: {PATH_D16}")
print(f"   D28: {PATH_D28}")
print(f"   GRID: {PATH_GRID}")
print("-" * 72)
print("[exp032bD] 注意: D16/D28 は Hyper 無し=生成が遅い。『肌が戻るか』の検証。戻れば sweet spot は後で決める。")
print("[exp032bD] [OBS] 実値ログ全文:")
for ln in OBS_LINES:
    print("   " + ln)
print("[exp032bD] 読み筋(§4): D28(or D16)で毛穴回復 / B のっぺり → 8-step 蒸留が主因 → step 増(sweet spot=D16)")
print("=" * 72)
