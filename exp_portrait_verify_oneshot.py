# ═══════════════════════════════════════════════════════════════════════════
# 本番 portrait phase-gate 検証 ワンセル(再起動→1行・本番挙動をそのまま測る)
#
#   目的: prod portrait(OSS-14 + no-Hyper + pass2 off + phase3 off・ceab744)を
#         「本番の素の経路」で叩き、4点 phase-gate を一括検証する。
#         ★実験のように OSS を再注入しない。prod 既定のフックがそのまま効く前提で測る。
#
#   ★使い方(再起動 → Cell 0 build → このセル):
#     1) ランタイム再起動(ボタン/別セルの os.kill)
#     2) Cell 0 / setup を実行(= ceab744 の no-Hyper + OSS フックが build 時に効く)
#     3) このセルを1行で実行:
#          exec(open("/content/drive/MyDrive/aibo_v7/exp_portrait_verify_oneshot.py", encoding="utf-8").read())
#
#   検証4点:
#     ① [OSS] APPLIED ログ : prod が出す `[OSS] APPLIED n=14 maxΔ≈0.0 ✓` を捕捉・再掲。出なければ ❌(ship 不可)。
#     ② wall-clock         : warm 後に N=14 end-to-end を計測 → <30s 判定(~24s 目標)。
#     ③ 肌+identity(複数seed): N=14 を seed 3つ生成+GRID。★PO 目視(機械判定しない)。
#     ④ step が効くか       : N=14 と N=28 で実 step 数と wall-clock が変わるか([OBS])。
#
#   厳守: prod 非改変(呼ぶ・生成するだけ)。ref 公式6枚 / 1024×1536 / pulid=0.7(IdentityConfig 既定)。
#         二重ビルドしない(既存 orchestrator を再利用。無ければ STOP=Cell 0 を促す)。判定は PO 目視。
# ═══════════════════════════════════════════════════════════════════════════

# ── ★再起動後の ModuleNotFound 回避(sys.path + chdir・3行)──────────────────
import sys
import os
sys.path.insert(0, "/content/aibo_src")   # code=GitHub clone(DriveFS 非経由)。data は Drive 絶対パス
os.chdir("/content/aibo_src")

import time
import logging
from importlib import import_module

from PIL import Image

# ── 定数(本番 UI 既定に合わせる)──────────────────────────────────────────
DRIVE = "/content/drive/MyDrive/aibo_v7"
PROMPT = (
    "close-up portrait photo of a young woman, soft natural daylight, "
    "looking directly at camera, 85mm lens, photorealistic, sharp focus on face"
)
NEG = None
GUIDANCE = 4.0          # ★本番 UI 既定(portrait-mode.tsx useState(4.0))。EXP-033 は 3.5。
W, H = 1024, 1536
N_MAIN = 14             # default(slider 既定)
N_HIGH = 28             # slider 上限(step が効くか確認用)
SEEDS_N14 = [12345, 2024, 7777]

FACE_DIR = "/content/drive/MyDrive/顔"
REF_FILES = [
    "Screenshot_20260414-124011.png",
    "Screenshot_20260414-124040.png",
    "Screenshot_20260414-124119.png",
    "Screenshot_20260414-124130.png",
    "Screenshot_20260414-124144.png",
    "Screenshot_20260510-150734.png",
]
OUT_DIR = os.path.join(DRIVE, "experiments")
PATH_N28 = os.path.join(OUT_DIR, "portrait_verify_n28.png")
PATH_GRID = os.path.join(OUT_DIR, "portrait_verify_GRID.png")

OBS_LINES = []


def _obs(line):
    OBS_LINES.append(line)
    print(line)


def _health_warn(label, img):
    """崩れ/単色の粗い検知(PO 目視の補助)。低 stddev は崩れ/真っ黒の疑い。"""
    try:
        from PIL import ImageStat
        st = ImageStat.Stat(img.convert("RGB"))
        sd = sum(st.stddev) / len(st.stddev)
    except Exception as _e:
        logging.getLogger("AIBO_v7").debug(f"[verify] stddev 計算スキップ: {_e}")
        return None
    if sd < 8.0:
        print(f"[verify][WARN] {label}: stddev={sd:.1f} 低 → 崩れ/単色の疑い。PO 確認必須。")
    return round(sd, 1)


# ── モジュール解決 ─────────────────────────────────────────────────────────
srv = import_module("09_fastapi_server")
pm04 = import_module("04_pipeline_manager")
cfg_mod = import_module("01_config")

# ── orchestrator 再利用(build しない。無ければ STOP)────────────────────────
try:
    orch = srv.get_orchestrator()
except Exception as _e:
    raise SystemExit(f"[verify][STOP] orchestrator 未 attach。先に Cell 0 / setup を実行してください: {_e}")
assert orch is not None, "[verify][STOP] orchestrator=None。Cell 0 build を実行。"
pm = orch.pm
sysc = orch.sys_cfg
assert getattr(pm, "pipe_base", None) is not None, "[verify][STOP] pipe_base 無し。Cell 0 build を確認。"
StudioMode = srv._resolve_studio_mode()
os.makedirs(OUT_DIR, exist_ok=True)

# ── prod 状態 preflight(本番既定が効いてるか)──────────────────────────────
_TF = type(getattr(pm, "_shared_transformer", None) or getattr(pm, "transformer", None)).__name__
_hyper_enable = getattr(sysc, "enable_hyper_flux", None)
_hyper_loaded = getattr(pm, "_hyper_flux_loaded", None)
_p3_enable = getattr(cfg_mod, "PHASE3_ENABLED", None)
_pass2_default = getattr(cfg_mod.GenerationConfig(), "enable_pass2", None)
_pulid_default = getattr(cfg_mod.IdentityConfig(), "pulid_weight", None)
_hook_on = getattr(getattr(pm.pipe_base, "scheduler", None), "_oss_hook_installed", False)
_obs(f"[OBS] preflight | quant(transformer)={_TF} | enable_hyper_flux={_hyper_enable} "
     f"_hyper_flux_loaded={_hyper_loaded} | PHASE3_ENABLED={_p3_enable} | "
     f"enable_pass2(default)={_pass2_default} | pulid_weight(default)={_pulid_default} | "
     f"oss_hook_installed={_hook_on}")
if _hyper_enable is True or _hyper_loaded is True:
    print("[verify][WARN] Hyper が有効/ロード済に見える(本番 no-Hyper でない疑い)→ PO 確認。")
if not _hook_on:
    print("[verify][WARN] OSS フック未装着(build が ceab744 を反映してない疑い)→ Cell 0 再 build 確認。")

# ── 公式6枚 ───────────────────────────────────────────────────────────────
assert len(REF_FILES) == 6, f"[verify][STOP] REF_FILES が6枚でない: {len(REF_FILES)}"
_ref_paths = [os.path.join(FACE_DIR, f) for f in REF_FILES]
_missing = [p for p in _ref_paths if not os.path.exists(p)]
assert not _missing, f"[verify][STOP] 公式 ref 不足(フォールバックしない): {_missing}"
refs = [Image.open(p).convert("RGB") for p in _ref_paths]

# ── prod [OSS] ログ捕捉(handler 追加・prod 非改変)──────────────────────────
_oss_logs = []


class _OSSCatch(logging.Handler):
    def emit(self, record):
        try:
            msg = record.getMessage()
        except Exception:
            return
        if "[OSS]" in msg:
            _oss_logs.append(msg)


_aibo_log = logging.getLogger("AIBO_v7")
_catch = _OSSCatch()
_catch.setLevel(logging.DEBUG)
_aibo_log.addHandler(_catch)


def _gen(label, n_steps, seed, save_path):
    """本番 _build_configs + orch.generate をそのまま呼ぶ(再注入なし)。"""
    _oss_logs.clear()
    gen_cfg, id_cfg = srv._build_configs(
        face_imgs=refs, prompt=PROMPT, negative_prompt=NEG,
        num_inference_steps=int(n_steps), guidance_scale=float(GUIDANCE),
        seed=int(seed), width=W, height=H,
    )
    print(f"[verify] ▶ {label}: 生成中 … N={n_steps} guidance={GUIDANCE} seed={seed} {W}x{H}")
    t0 = time.perf_counter()
    r = orch.generate(gen_cfg, id_cfg, mode=StudioMode.PORTRAIT, save=False)
    wall = time.perf_counter() - t0
    assert getattr(r, "error", None) is None, f"[verify][STOP] {label} 生成失敗: {r.error}"
    assert getattr(r, "final_image", None) is not None, f"[verify][STOP] {label} final_image=None"
    img = r.final_image.convert("RGB")
    if save_path is not None:
        img.save(save_path)
        print(f"[verify] 保存: {save_path}")
    # prod [OSS] APPLIED ログ(最後の APPLIED 行)
    oss_line = None
    for m in reversed(_oss_logs):
        if "APPLIED" in m:
            oss_line = m
            break
    # 実 step 数(scheduler.sigmas 長 - 1)
    actual_step = None
    try:
        _sig = pm.pipe_base.scheduler.sigmas
        actual_step = int(_sig.shape[0]) - 1
    except Exception as _e:
        _aibo_log.debug(f"[verify] sigmas 読取スキップ: {_e}")
    steps_resolved = getattr(r, "steps_pass1", None)
    return {
        "label": label, "N": int(n_steps), "seed": int(seed), "img": img, "wall": wall,
        "oss_line": oss_line, "actual_step": actual_step, "steps_resolved": steps_resolved,
        "phase3_applied": getattr(r, "phase3_applied", None),
        "pulid_used": getattr(r, "pulid_used", None),
        "stddev": _health_warn(label, img), "path": save_path,
    }


res14 = []
res28 = None
try:
    # ── warm(1回捨て・計測に含めない)──────────────────────────────────────
    print("=" * 72)
    print("[verify] warm-up(1回捨て生成)…")
    _gen("WARM", N_MAIN, SEEDS_N14[0], None)

    # ── ③ N=14 × 3 seed ───────────────────────────────────────────────────
    print("=" * 72)
    for i, sd in enumerate(SEEDS_N14):
        p = os.path.join(OUT_DIR, f"portrait_verify_n14_seed{chr(97 + i)}.png")
        res14.append(_gen(f"N14 seed{sd}", N_MAIN, sd, p))

    # ── ④ N=28(step 効果確認・seed は N14 seed a と同一=step 単離)─────────
    res28 = _gen(f"N28 seed{SEEDS_N14[0]}", N_HIGH, SEEDS_N14[0], PATH_N28)
finally:
    _aibo_log.removeHandler(_catch)

# ── [OBS] 各生成 ────────────────────────────────────────────────────────────
print("=" * 72)
for r in res14 + ([res28] if res28 else []):
    _obs(f"[OBS] {r['label']} | N={r['N']} | 実step={r['actual_step']} | resolved={r['steps_resolved']} | "
         f"wall={r['wall']:.2f}s | OSS='{r['oss_line']}' | "
         f"phase3_applied={r['phase3_applied']} | pulid_used={r['pulid_used']} | stddev={r['stddev']}")

# ── 4点 phase-gate 判定 ─────────────────────────────────────────────────────
def _oss_ok(r):
    ln = r.get("oss_line") or ""
    return ("APPLIED" in ln) and (f"n={r['N']}" in ln) and ("✓" in ln)


# ① [OSS] APPLIED
_g1_items = res14 + ([res28] if res28 else [])
_g1 = all(_oss_ok(r) for r in _g1_items)
# ② wall-clock <30s(N=14 全 seed)
_walls14 = [r["wall"] for r in res14]
_g2 = all(w < 30.0 for w in _walls14)
# ③ 肌+identity → PO 目視(機械判定しない)
# ④ step が効くか(実 step が N と一致し N14≠N28・wall も増加)
_step14 = res14[0]["actual_step"] if res14 else None
_step28 = res28["actual_step"] if res28 else None
_g4 = (
    res28 is not None
    and _step14 == N_MAIN and _step28 == N_HIGH
    and (res28["wall"] > res14[0]["wall"])
)

print("=" * 72)
print("[verify] ★4点 phase-gate 判定サマリ:")
_obs(f"[GATE①] OSS APPLIED(機械)        : {'✓' if _g1 else '❌ OSS 未適用=ship しない'} "
     f"(各生成で APPLIED n=<N> ✓ を要求)")
_obs(f"[GATE②] wall-clock <30s(機械)    : {'✓' if _g2 else '❌'} "
     f"| N14 walls={[round(w,1) for w in _walls14]}s(目標 ~24s)")
_obs(f"[GATE③] 肌+identity              : ☐ PO 目視(機械判定しない) "
     f"| N14 ×3seed + N28 を GRID で D20級肌 / Nika 保持を複数画で確認")
_obs(f"[GATE④] step が効く(機械)        : {'✓' if _g4 else '❌'} "
     f"| 実step N14={_step14} N28={_step28} / wall N14={res14[0]['wall']:.1f}s "
     f"N28={(res28['wall'] if res28 else float('nan')):.1f}s")

# ── GRID(N14 a|b|c | N28)────────────────────────────────────────────────
_panels = [(f"N14 seed{r['seed']} ({r['wall']:.1f}s)", r["img"]) for r in res14]
if res28:
    _panels.append((f"N28 seed{res28['seed']} ({res28['wall']:.1f}s)", res28["img"]))
try:
    pm04._depth_grid(
        _panels, PATH_GRID, ncols=len(_panels), show=True,
        title="portrait verify (PO: 毛穴/産毛/grain=D20級肌? + Nika identity 保持? ×複数seed)")
    print(f"[verify] グリッド: {PATH_GRID}")
except Exception as _e:
    print(f"[verify] (warn) グリッド生成失敗(継続): {_e}")

# ── まとめ ──────────────────────────────────────────────────────────────────
print("=" * 72)
print("[verify] 完了。PO 判定材料(結論は書かない):")
print(f"  guidance={GUIDANCE}(本番UI既定・EXP-033 は 3.5)/ pulid_weight 既定={_pulid_default} / quant={_TF}")
print("  ① OSS: 上の [GATE①]。❌ なら本番でフックが効いてない=ship 不可(Cell 0 再 build 確認)。")
print("  ② <30s: [GATE②]。N14 全 seed の wall。")
print("  ③ 肌+identity: ★PO が GRID を目視(D20級肌 + Nika 保持を複数 seed で)。")
print("  ④ step: [GATE④]。N14=14 / N28=28 で実 step と wall が変わるか(slider→backend 配線代理)。")
print("     ※ UI スライダー自体の動作は localhost:3000 で別途目視。")
for i, r in enumerate(res14):
    print(f"   N14 seed{r['seed']}: {r['path']}")
if res28:
    print(f"   N28: {PATH_N28}")
print(f"   GRID: {PATH_GRID}")
print("-" * 72)
print("[verify] [OBS] 実値ログ全文:")
for ln in OBS_LINES:
    print("   " + ln)
print("=" * 72)
