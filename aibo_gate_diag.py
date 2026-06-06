"""
aibo_gate_diag.py ― RECON-013 自己完結ゲート診断(貼って実行で原因確定)
================================================================
診断のみ。core(Setting A / PuLID 集約核 / 量子化核)・判定式・OFF 出力には一切触れない。
A3 が「未起動(n_a3_logs=0)」になる原因を、PO が1セル実行だけで切り分ける。

なぜこのツールが要るか:
  attach_a3_file_log と a3_m2_check の [A3] カウンタは、ログを **"[A3]" を含む行だけ**に
  フィルタしている。案A の [GATE] 行は "[A3]" を含まないので、両方に拾われず PO から見えなかった
  (= aibo_a3.log 空 / [A3]ログ0行 の正体)。本ツールは root logger に **無フィルタ** の捕捉
  ハンドラを付け、どの名前のロガー・どのスレッドの logger.info も取りこぼさず拾う。

使い方(Colab · 1セル):
    from importlib import import_module
    import_module("aibo_gate_diag").run("/content/your_ref_face.jpg", seed=1234567)
"""
from __future__ import annotations

import inspect
import logging
import os
from importlib import import_module


def _getsource_has(method, needle: str):
    """method のソースに needle が在るか。(found, error) を返す。"""
    try:
        src = inspect.getsource(method)
    except Exception as e:  # noqa: BLE001  (診断のため理由を返すだけ · 握り潰さない)
        return None, f"getsource 失敗: {e}"
    return (needle in src), None


def run(ref_path, *, seed: int = 1234567,
        prompt: str = "a portrait photo of a person, natural light, looking at camera",
        orch=None, verbose: bool = True) -> dict:
    """A3 ON で1回だけ生成し、[GATE] 行 / 実走メソッド / env / id_embeds を1行 VERDICT で返す。"""
    from PIL import Image

    cfg = import_module("01_config")
    if orch is None:
        srv = import_module("09_fastapi_server")
        orch = srv.get_orchestrator()

    out: dict = {}

    # ── 1) freshness 証明: m2 の内部生成が実際に呼ぶメソッドに [GATE] が在るか ──
    #     (再起動・同期が効かず古いコードが載っている "stale module" 説を確実に潰す)
    fresh = {}
    for name in ("_run_pass1", "_run_pass1_with_cn"):
        meth = getattr(type(orch), name, None)
        found, err = _getsource_has(meth, "[GATE]") if meth else (None, "メソッド無し")
        fresh[name] = {"gate_in_source": found, "err": err}
        if verbose:
            print(f"[FRESH] {name}: [GATE] in source = {found}  {err or ''}")
    out["freshness"] = fresh
    stale = any(v["gate_in_source"] is not True for v in fresh.values())
    if stale:
        # 確実に潰す: stale なら以降の生成は無意味なので明示して止める
        out["verdict"] = "STALE_MODULE"
        if verbose:
            print("[VERDICT] ❌ STALE: 走っているコードに [GATE] が無い "
                  "→ 再起動/4拠点同期が反映されていない。Cell0 から再起動して .py を読み直す。")
        return out

    # ── 2) root logger に無フィルタ catch-all(どの名前のロガーでも必ず拾う)──
    records: list[str] = []

    class _Catch(logging.Handler):
        def emit(self, r):
            try:
                records.append(r.getMessage())
            except Exception:  # noqa: BLE001
                return  # 1行の整形失敗で診断全体を止めない(pass にはしない)

    catch = _Catch()
    catch.setLevel(logging.INFO)
    root = logging.getLogger()
    prev_root_level = root.level
    root.addHandler(catch)
    root.setLevel(logging.INFO)
    # "AIBO_v7" が propagate=False だと root に来ないので一時 True(後で戻す)
    av = logging.getLogger("AIBO_v7")
    prev_prop = av.propagate
    av.propagate = True

    # ── 5) 生成入口でメソッド名・経路を1行ログ(_run_pass1 / _with_cn を一時ラップ)──
    #     [GATE] が万一出なくても「どのメソッド=どの経路が走ったか」を確実に掴む。
    orig_p1 = orch._run_pass1
    orig_cn = orch._run_pass1_with_cn
    called: list[str] = []

    def _w1(*a, **k):
        called.append("_run_pass1 (route=PORTRAIT · 05:564)")
        av.info("[ENTRY] route=PORTRAIT method=_run_pass1")
        return orig_p1(*a, **k)

    def _wcn(*a, **k):
        called.append("_run_pass1_with_cn (route=Multi-CN · 05:560)")
        av.info("[ENTRY] route=Multi-CN method=_run_pass1_with_cn")
        return orig_cn(*a, **k)

    orch._run_pass1 = _w1
    orch._run_pass1_with_cn = _wcn

    # ── 3) A3 ON で1回だけ生成(m2 と同じ入口 = orch.generate / PORTRAIT)──
    ref = Image.open(ref_path).convert("RGB")
    gen_cfg = cfg.GenerationConfig(prompt=prompt, seed=int(seed),
                                   enable_pass2=False, enable_upscale=False)
    id_cfg = cfg.IdentityConfig(reference_image=ref, pulid_weight=2.5)
    prev_env = os.environ.get("AIBO_ENABLE_A3")
    os.environ["AIBO_ENABLE_A3"] = "1"
    gen_err = None
    pulid_used = None
    try:
        if verbose:
            print(f"[RUN] A3 ON 生成中(env=1, seed={seed})…")
        result = orch.generate(gen_cfg=gen_cfg, id_cfg=id_cfg,
                               mode=cfg.StudioMode.PORTRAIT, save=False)
        pulid_used = bool(getattr(result, "pulid_used", False))
        gen_err = getattr(result, "error", None)
    except Exception as e:  # noqa: BLE001  (例外でも捕捉ログを見たいので握らず記録)
        gen_err = f"{type(e).__name__}: {e}"
    finally:
        os.environ.pop("AIBO_ENABLE_A3", None) if prev_env is None \
            else os.environ.__setitem__("AIBO_ENABLE_A3", prev_env)
        orch._run_pass1 = orig_p1
        orch._run_pass1_with_cn = orig_cn
        root.removeHandler(catch)
        root.setLevel(prev_root_level)
        av.propagate = prev_prop

    # ── 4) 1行 VERDICT ──
    gate_lines = [m for m in records if m.startswith("[GATE]")]
    a3_lines = [m for m in records if "[A3]" in m]
    entry_lines = [m for m in records if m.startswith("[ENTRY]")]
    out.update({
        "gate_lines": gate_lines, "a3_lines_count": len(a3_lines),
        "called_methods": called, "entry_lines": entry_lines,
        "pulid_used": pulid_used, "gen_error": gen_err,
    })
    out["verdict"] = "GATE_FIRED" if gate_lines else "GATE_NOT_REACHED"

    if verbose:
        print("=" * 72)
        print(f"[VERDICT] pulid_used={pulid_used} gen_error={gen_err} "
              f"| 実走メソッド={called or '(どちらも未呼出)'} "
              f"| [GATE]={len(gate_lines)}行 [A3]={len(a3_lines)}行 [ENTRY]={len(entry_lines)}行")
        if gate_lines:
            print("  ✅ [GATE] 出力あり → 下記が env / route / id_embeds / _a3_on の真値:")
            for g in gate_lines:
                print("     ", g)
            print("  読み方: _a3_on=False の主因 = "
                  "(env が '1' 以外なら env)/(route=Multi-CN なら経路)/(id_embeds=False なら identity)")
        else:
            print("  ⚠️ [GATE] 行なし = ゲート未到達 or 出力前に抜けた。")
            print(f"     実際に走った生成メソッド: {called or '(none)'}")
            print(f"     参考 [A3] 行: {a3_lines[:3]}")
            print("     → メソッドが走っているのに [GATE] 0 なら logger/level 異常。"
                  "メソッドも未呼出なら generate が pass1 前で抜けている(例外/早期 return)。")
    return out


if __name__ == "__main__":
    import sys
    _ref = sys.argv[1] if len(sys.argv) > 1 else None
    if _ref:
        run(_ref)
    else:
        print("usage: import_module('aibo_gate_diag').run('/content/your_ref_face.jpg')")
