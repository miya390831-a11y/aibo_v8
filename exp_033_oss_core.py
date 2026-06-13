# ═══════════════════════════════════════════════════════════════════════════
# EXP-033 案A検証 — OSS-16/14 で「<30s × 20step 品質」 (core)
#
#   司令部確定の規約(案①):
#     dynamic-shift 一時OFF + OSS“最終sigma”注入 + [OBS] で実sigma印字。
#   実装メカニズム(prod 不変・runtime override・try/finally 復元):
#     pipe.scheduler.set_timesteps を instance-wrap し、通常呼出しの“後”に
#     scheduler.sigmas を OSS 最終 sigma（+末尾0）で“強制上書き”する。
#     → これにより calculate_shift(mu) の二重シフトが結果に乗らない（= shift OFF と等価）。
#       しかも diffusers のバージョン差（time_shift の実装差）に依らず確実。
#     さらに毎回 scheduler.sigmas を捕捉 → [OBS] で「注入値 vs 実際に使われた値」を突合
#       （サイレント fallback / 二重シフトを機械検出）。指示書 §3 検証ゲートの本体。
#
#   条件(同 seed / no-Hyper / PuLID 0.7 / INT4 / 1024x1536 / 公式6枚):
#     D20   = 既定sigma 20step（★肌の品質下限・A/B 基準）   phase3 OFF
#     OSS16 = OSS最終sigma 16step（本命）                  phase3 OFF（<30s 本命）/ ON（GFPGAN コスト計測）
#     OSS14 = OSS最終sigma 14step（ストレッチ）            phase3 OFF
#     D28   = 既存 skin_abl_D28_28step.png を流用（identity gold・あれば GRID 併置）
#
#   ★ OSS sigma の実値出所（推測値ではない）:
#     公式 ComfyUI 統合ノード OptimalStepsScheduler の NOISE_LEVELS["FLUX"]（10step ネイティブ 11値）を
#     log 線形補間して 16/14step を生成。値はセル内で再現算出し、文書値と一致を assert。
#     (arXiv:2503.21774 Table7 は GenEval スコア表で sigma 値は無い／公式 repo の oss_flux.py は
#      毎回 DP 探索 search_OSS=<30s 不可。固定で引けるのは ComfyUI 蒸留版のみ。)
#
#   使い方: exp_033_oss_oneshot.py 経由（再起動→1行）。本ファイルは単体 exec も可（スタック構築済み前提）。
#   Setting A 7値・config 既定・production コードには触れない（in-memory override のみ）。判定は PO 目視。
# ═══════════════════════════════════════════════════════════════════════════
import os
import time
import functools
from importlib import import_module

import numpy as np
import torch
from PIL import Image

# ── 定数 ──────────────────────────────────────────────────────────────────
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
PATH_D20 = os.path.join(OUT_DIR, "skin_abl_D20.png")
PATH_OSS16 = os.path.join(OUT_DIR, "skin_abl_OSS16.png")
PATH_OSS14 = os.path.join(OUT_DIR, "skin_abl_OSS14.png")
PATH_D28 = os.path.join(OUT_DIR, "skin_abl_D28_28step.png")   # 既存流用(identity gold)
PATH_GRID = os.path.join(OUT_DIR, "skin_abl_GRID_OSS.png")

# ── OSS sigma 実値（ComfyUI OptimalStepsScheduler を忠実再現）────────────────
# NOISE_LEVELS["FLUX"]（10step ネイティブ・末尾は実質0）
FLUX_BASE = [0.9968, 0.9886, 0.9819, 0.975, 0.966, 0.9471, 0.9158, 0.8287, 0.5512, 0.2808, 0.001]


def _loglinear_interp(t_steps, num_steps):
    """ComfyUI comfy_extras/nodes_optimalsteps.py と同一の log 線形補間。"""
    xs = np.linspace(0, 1, len(t_steps))
    ys = np.log(np.array(t_steps)[::-1])
    new_xs = np.linspace(0, 1, num_steps)
    new_ys = np.interp(new_xs, xs, ys)
    return np.exp(new_ys)[::-1].copy()


def _oss_final_sigmas(steps):
    """steps 用の OSS 最終 sigma（非ゼロ N 値）。ComfyUI: get_sigmas(denoise=1.0) の末尾0を除いた列。"""
    s = list(FLUX_BASE)
    if (steps + 1) != len(s):
        s = list(_loglinear_interp(s, steps + 1))
    s = s[-(steps + 1):]
    s[-1] = 0.0
    return [float(x) for x in s[:-1]]   # diffusers は末尾0を自前付与するため非ゼロ N 値を渡す/上書きに使う


OSS16 = _oss_final_sigmas(16)
OSS14 = _oss_final_sigmas(14)

# 文書値（report_EXP-033_*.md と一致）— 推測混入の検出
_DOC_OSS16 = [0.9968, 0.99167, 0.98692, 0.98274, 0.97844, 0.97387, 0.96824, 0.95887,
              0.9471, 0.92741, 0.8932, 0.83912, 0.67585, 0.50664, 0.33237, 0.0339]
_DOC_OSS14 = [0.9968, 0.99094, 0.98572, 0.98091, 0.97598, 0.96985, 0.96056, 0.9471,
              0.92464, 0.8774, 0.78181, 0.58426, 0.37491, 0.05609]
assert np.allclose(OSS16, _DOC_OSS16, atol=1e-4), f"[exp033][STOP] OSS16 再現不一致: {OSS16}"
assert np.allclose(OSS14, _DOC_OSS14, atol=1e-4), f"[exp033][STOP] OSS14 再現不一致: {OSS14}"

OBS_LINES = []


def _obs(line):
    OBS_LINES.append(line)
    print(line)


def _health_warn(label, img):
    """崩れ/単色の粗い検知（PO 目視の補助）。低 stddev は崩れ/真っ黒の疑い。"""
    try:
        from PIL import ImageStat
        st = ImageStat.Stat(img.convert("RGB"))
        sd = sum(st.stddev) / len(st.stddev)
        if sd < 8.0:
            print(f"[exp033][WARN] {label}: stddev={sd:.1f} 低 → 崩れ/単色の疑い。PO 確認必須。")
        return round(sd, 1)
    except Exception:
        return None


# ── 1. orchestrator + config 解決 ─────────────────────────────────────────
pm04 = import_module("04_pipeline_manager")
orch, _err = pm04._depth_find_orch(None)
assert orch is not None, f"[exp033][STOP] orchestrator 未取得: {_err}"
pm = orch.pm
sysc = orch.sys_cfg
cfg_mod = import_module("01_config")

_og = getattr(orch.generate, "__globals__", {}) or {}
_cfg = import_module("01_config")
GenerationConfig = _og.get("GenerationConfig") or _cfg.GenerationConfig
IdentityConfig = _og.get("IdentityConfig") or _cfg.IdentityConfig
StudioMode = _og.get("StudioMode") or _cfg.StudioMode

os.makedirs(OUT_DIR, exist_ok=True)
_TF_CLS = type(getattr(pm, "_shared_transformer", None) or getattr(pm, "transformer", None)).__name__

# ── 2. ★必須検証: no-Hyper / INT4（違反なら STOP）─────────────────────────
_loaded = getattr(pm, "_hyper_flux_loaded", None)
_enable = getattr(sysc, "enable_hyper_flux", None)
_obs(f"[OBS] preflight | _hyper_flux_loaded={_loaded} | enable_hyper_flux={_enable} | "
     f"hyper_flux_weight={getattr(sysc,'hyper_flux_weight',None)} | quant(transformer)={_TF_CLS}")
assert _loaded is not True, (
    f"[exp033][STOP] Hyper-FLUX が既にロード済み(_hyper_flux_loaded={_loaded})。別経路ロード疑い → 司令部報告。"
)
assert _enable is not True, f"[exp033][STOP] enable_hyper_flux={_enable}（no-Hyper でない）→ 報告。"
if "nunchaku" not in _TF_CLS.lower() and "int4" not in _TF_CLS.lower():
    print(f"[exp033][WARN] transformer={_TF_CLS} が INT4/Nunchaku に見えない。PO 確認。")

# ── 3. 公式6枚 ───────────────────────────────────────────────────────────
assert len(REF_FILES) == 6, f"[exp033][STOP] REF_FILES が6枚でない: {len(REF_FILES)}"
_ref_paths = [os.path.join(FACE_DIR, f) for f in REF_FILES]
_missing = [p for p in _ref_paths if not os.path.exists(p)]
assert not _missing, f"[exp033][STOP] 公式 ref 不足（フォールバックしない）: {_missing}"
refs = [Image.open(p).convert("RGB") for p in _ref_paths]

# ── 4. 注入ハーネス（set_timesteps を instance-wrap）────────────────────────
_sched = pm.pipe_base.scheduler
assert _sched is not None, "[exp033][STOP] pipe_base.scheduler が None"
_INJECT = {"force_sigmas": None, "captured": []}
_orig_set = _sched.set_timesteps   # bound method


@functools.wraps(_orig_set)
def _patched_set(*args, **kwargs):
    # 1) まず通常どおり set_timesteps を走らせる（device/型/mu 等を正しく構築）
    _orig_set(*args, **kwargs)
    # 2) OSS 条件なら scheduler.sigmas を OSS 最終 sigma で強制上書き（= shift 二重適用を無効化）
    fs = _INJECT.get("force_sigmas")
    if fs is not None:
        dev = _sched.sigmas.device
        dt = _sched.sigmas.dtype
        ntt = float(getattr(_sched.config, "num_train_timesteps", 1000) or 1000)
        s = torch.tensor(list(fs) + [0.0], dtype=dt, device=dev)
        _sched.sigmas = s
        _sched.timesteps = (s[:-1] * ntt).to(dev)
        try:
            _sched.num_inference_steps = len(fs)
        except Exception:
            pass
    # 3) 実際に使われた sigma を必ず捕捉（[OBS] 検証ゲート用）
    try:
        _INJECT["captured"].append(
            [round(float(x), 5) for x in _sched.sigmas.detach().float().cpu().tolist()]
        )
    except Exception:
        pass


_sched.set_timesteps = _patched_set
_orig_p3 = getattr(cfg_mod, "PHASE3_ENABLED", True)


def _gen(label, steps, force_sigmas, phase3_on, save_path=None):
    """1 条件を生成し、(img, wall_clock, result, captured_sigmas) を返す。"""
    _INJECT["force_sigmas"] = list(force_sigmas) if force_sigmas is not None else None
    _INJECT["captured"].clear()
    cfg_mod.PHASE3_ENABLED = bool(phase3_on)

    gen_cfg = GenerationConfig(prompt=PROMPT, width=W, height=H, seed=int(SEED))
    gen_cfg.num_inference_steps = int(steps)     # 明示 → resolved_steps はこの値
    gen_cfg.guidance_scale = float(GUIDANCE)
    gen_cfg.enable_pass2 = False
    id_cfg = IdentityConfig(reference_image=refs[0], reference_images=list(refs))
    id_cfg.pulid_weight = float(PULID)

    print(f"[exp033] ▶ {label}: 生成中 … steps={steps} "
          f"sigma={'OSS' if force_sigmas is not None else '既定'} phase3={'ON' if phase3_on else 'OFF'} "
          f"pulid={PULID} {W}x{H} seed={SEED}")
    t0 = time.perf_counter()
    r = orch.generate(gen_cfg=gen_cfg, id_cfg=id_cfg, mode=StudioMode.PORTRAIT, save=False)
    wall = time.perf_counter() - t0

    _INJECT["force_sigmas"] = None   # 即時 disarm（後続の意図せぬ上書き防止）
    assert r.error is None, f"[exp033][STOP] {label} 生成失敗: {r.error}"
    assert r.final_image is not None, f"[exp033][STOP] {label} final_image=None"
    img = r.final_image.convert("RGB")
    cap = _INJECT["captured"][-1] if _INJECT["captured"] else None
    if save_path is not None:
        img.save(save_path)
        print(f"[exp033] 保存: {save_path}")
    return img, wall, r, cap


def _verify_sigma(label, injected, cap):
    """[OBS] 検証ゲート: 注入 OSS sigma が実際に denoise に乗ったか（二重シフト/fallback を検出）。"""
    if cap is None:
        _obs(f"[OBS] {label} sigma-applied: ❌ 捕捉なし（set_timesteps 未通過？）→ 報告")
        return False
    used = cap[:-1]              # 末尾0を除いた実 sigma 列
    nstep = len(cap) - 1
    if injected is None:
        _obs(f"[OBS] {label} 既定schedule | 実step={nstep} | "
             f"actual_sigmas={[round(x,4) for x in used]}")
        return True
    len_ok = (len(used) == len(injected))
    maxd = max(abs(a - b) for a, b in zip(used, injected)) if len_ok else 999.0
    ok = len_ok and maxd < 1e-3
    _obs(f"[OBS] {label} sigma-applied: 実step={nstep} len_match={len_ok} maxΔ={maxd:.5f} -> "
         f"{'OSS APPLIED ✓' if ok else '❌ FALLBACK/二重シフト疑い → 判定に進まず報告'}")
    _obs(f"[OBS] {label} injected={[round(x,4) for x in injected]}")
    _obs(f"[OBS] {label} actual  ={[round(x,4) for x in used]}")
    return ok


try:
    # ── 5. ウォームアップ（1回捨て・GPU カーネル温め）──────────────────────
    print("=" * 72)
    print("[exp033] warm-up（1回捨て生成・計測に含めない）…")
    _gen("WARM", 8, None, False, save_path=None)

    # ── 6. 本計測 ───────────────────────────────────────────────────────────
    print("=" * 72)
    img_d20, t_d20, r_d20, cap_d20 = _gen("D20", 20, None, False, PATH_D20)
    img_o16, t_o16, r_o16, cap_o16 = _gen("OSS16", 16, OSS16, False, PATH_OSS16)   # ★<30s 本命(phase3 OFF)
    _, t_o16_on, r_o16_on, _ = _gen("OSS16_p3on", 16, OSS16, True, save_path=None)  # GFPGAN コスト計測用
    img_o14, t_o14, r_o14, cap_o14 = _gen("OSS14", 14, OSS14, False, PATH_OSS14)

finally:
    # ── 復元（prod 不変の担保）───────────────────────────────────────────────
    try:
        del _sched.set_timesteps      # instance override を外す → class メソッドに復帰
    except Exception:
        pass
    try:
        cfg_mod.PHASE3_ENABLED = _orig_p3
    except Exception:
        pass
    print(f"[exp033] 復元完了: set_timesteps=原状 / PHASE3_ENABLED={getattr(cfg_mod,'PHASE3_ENABLED',None)}")

# ── 7. ★検証ゲート（指示書 §3）────────────────────────────────────────────
print("=" * 72)
print("[exp033] sigma 適用検証（注入値 vs 実使用値）:")
_v_d20 = _verify_sigma("D20", None, cap_d20)
_v_o16 = _verify_sigma("OSS16", OSS16, cap_o16)
_v_o14 = _verify_sigma("OSS14", OSS14, cap_o14)

# 健全性 stddev
sd_d20 = _health_warn("D20", img_d20)
sd_o16 = _health_warn("OSS16", img_o16)
sd_o14 = _health_warn("OSS14", img_o14)

# ── 8. wall-clock（指示書 §4）─────────────────────────────────────────────
p3_cost_diff = t_o16_on - t_o16
p3_elapsed = getattr(r_o16_on, "phase3_elapsed_sec", None)
_obs(f"[OBS] wall-clock(end-to-end) | D20={t_d20:.2f}s | OSS16(p3off)={t_o16:.2f}s | "
     f"OSS14(p3off)={t_o14:.2f}s | OSS16(p3on)={t_o16_on:.2f}s")
_obs(f"[OBS] GFPGAN(phase3) コスト | OSS16: p3on-p3off={p3_cost_diff:.2f}s | "
     f"phase3_elapsed_sec(直接計測)={p3_elapsed} | "
     f"p3on_applied={getattr(r_o16_on,'phase3_applied',None)} "
     f"bypass={getattr(r_o16_on,'phase3_bypass_triggered',None)}")
_obs(f"[OBS] <30s 判定材料 | OSS16(p3off)={t_o16:.2f}s {'<30s ✓' if t_o16<30 else '≥30s ✗'} | "
     f"OSS14(p3off)={t_o14:.2f}s {'<30s ✓' if t_o14<30 else '≥30s ✗'} | "
     f"D20(p3off)={t_d20:.2f}s（基準）")
_obs(f"[OBS] 共通条件 | hyper=OFF(not loaded) | pulid={PULID} | quant={_TF_CLS} | "
     f"{W}x{H} | seed={SEED} | guidance={GUIDANCE} | "
     f"stddev D20={sd_d20}/OSS16={sd_o16}/OSS14={sd_o14}")

# ── 9. GRID（D20 | OSS16 | OSS14、identity 用に D28 併置可）─────────────────
_panels = [
    (f"D20 20step 既定σ ({t_d20:.1f}s)", img_d20),
    (f"OSS16 ({t_o16:.1f}s p3off)", img_o16),
    (f"OSS14 ({t_o14:.1f}s p3off)", img_o14),
]
_ncols = 3
if os.path.exists(PATH_D28):
    try:
        _panels.append(("D28 28step (identity gold)", Image.open(PATH_D28).convert("RGB")))
        _ncols = 4
        print(f"[exp033] D28 を identity 参照として GRID 併置: {PATH_D28}")
    except Exception as e:
        print(f"[exp033] (warn) D28 読込失敗（継続）: {e}")
else:
    print(f"[exp033] D28 不在（identity 参照は省略・GRID は D20|OSS16|OSS14）: {PATH_D28}")

try:
    pm04._depth_grid(
        _panels, PATH_GRID, ncols=_ncols, show=True,
        title="EXP-033 OSS (PO: skin 毛穴/産毛/grain → 肌◎? + Nika identity 保持? + <30s?)")
    print(f"[exp033] グリッド: {PATH_GRID}")
except Exception as e:
    print(f"[exp033] (warn) グリッド生成失敗（継続）: {e}")

# ── 10. まとめ（PO へ・結論は書かない）──────────────────────────────────────
print("=" * 72)
print("[exp033] 完了。PO 判定材料（結論は書かない）:")
print("  ① まず検証ゲート: OSS16/OSS14 が『OSS APPLIED ✓』か（❌なら判定に進まず報告）。")
print("  ② 健全性: D20/OSS16/OSS14 が崩れ/過蒸留でない綺麗な絵か（stddev / 目視）。")
print("  ③ 肌: 毛穴・産毛・肌グレインで OSS16(/14) ≥ D20 か（A/B）。")
print("  ④ identity: OSS16(/14) が Nika を保持か（D28 gold と比較）。")
print("  ⑤ <30s: OSS16(p3off) の wall-clock。GFPGAN 切りで何秒浮くか（p3on-p3off）。")
print(f"   D20  : {PATH_D20}")
print(f"   OSS16: {PATH_OSS16}")
print(f"   OSS14: {PATH_OSS14}")
print(f"   GRID : {PATH_GRID}")
print("-" * 72)
print("[exp033] [OBS] 実値ログ全文:")
for ln in OBS_LINES:
    print("   " + ln)
print("[exp033] 読み筋(§6): OSS16 肌≥D20 + Nika 保持 + <30s(特に p3off) → 案A 採用=決着 /")
print("                      OSS16 弱い or OSS14 境界 → max_shift 微調整 or σ-gate or step 微増 /")
print("                      GFPGAN off で ~10s 浮く → portrait の phase3 無効化を別途検討（PO 判断）。")
print("=" * 72)
