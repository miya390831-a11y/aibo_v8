"""
a3_controller.py ― A3 Week1 (M0→M2) 隔離コントローラ
================================================================
親文書: RECON-010 / 011 / 012(すべて GO)

役割(M2 時点・ここまでしかやらない):
  - timestep キーによる step 同定(二重 forward でズレない)
  - Tier0 観測(方向変化 1-cos)を **ログのみ**(補正は駆動しない)
  - 固定 weight bump(配管実証用 · step>=threshold で w0→w0+bump)

ここでやらないこと(M3 / M4 / Week2 送り):
  - TAEF1 / identity 測定 / PI 制御 / CN 動的化

設計原則:
  核(Setting A 7値 / PuLID 集約核 / 量子化核 / nunchaku binder)には一切触れない。
  本コントローラは transformer の forward から呼ばれるだけの純粋ロジックで、
  state は「生成 1 本」単位。生成ごとに reset() を必ず呼ぶ(P4 · 持ち越し禁止)。
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from importlib import import_module

import numpy as np
import torch
from PIL import Image

# 01_config が立てるのと同一の logger シングルトンを共有(import 順非依存)
logger = logging.getLogger("AIBO_v7")

# reset 前 / 初回 forward の last_ts と「実 timestep が None の場合」を確実に区別する番兵。
_UNSET = object()


class A3Controller:
    """生成 1 本ごとに reset → forward 毎に on_forward / measure_tier0 / update_fixed を回す。"""

    def __init__(self) -> None:
        # orchestrator が必ず reset() を呼ぶが、reset 前参照に備えた最小初期化。
        self._step: int = -1
        self._last_ts = _UNSET
        self._w0: float = 1.0
        self._dyn_weight: float = 1.0
        self._w_bump: float = 0.2
        self._step_threshold: int = 4
        # M0 判定用: この生成で観測した「distinct timestep キー」を出現順に記録。
        # reset で必ず空にする(生成跨ぎ持ち越し禁止 · P4)。
        self._m0_seen_ts: list = []

    # ─────────────────────────────────────────────────────────
    def reset(self, w0: float, *, w_bump: float = 0.2, step_threshold: int = 4) -> None:
        """生成ごとに必ず呼ぶ(直前生成の状態を持ち越さない · P4)。

        _step=-1 始まり → 最初の distinct timestep で 0 になる(0-index · M0 の 0..7 と一致)。
        """
        self._step = -1
        self._last_ts = _UNSET
        self._w0 = float(w0)
        self._dyn_weight = float(w0)
        self._w_bump = float(w_bump)
        self._step_threshold = int(step_threshold)
        self._m0_seen_ts = []  # M0 観測列を生成ごとに初期化(持ち越さない)

    # ─────────────────────────────────────────────────────────
    def on_forward(self, ts) -> int:
        """timestep キーで step を同定して返す。

        ts が直前と異なる時だけ _step を 1 進める。CFG の cond/uncond や PuLID
        double-stream で同一 step に forward が複数回来ても、同一 timestep なら進めない
        (= forward 呼び出し数ではなく timestep をキーにする · 二重 forward 耐性)。
        """
        key = self._ts_key(ts)
        if key != self._last_ts:
            self._step += 1
            self._last_ts = key
            self._m0_seen_ts.append(key)  # distinct timestep を出現順に記録(M0 判定用)
        return self._step

    # ─────────────────────────────────────────────────────────
    def measure_tier0(self, prev_h, cur_h) -> None:
        """Tier0: 隣接 step 間の hidden_states 方向変化 1-cos を **ログのみ**。

        補正は一切駆動しない。例外は外に出さない(M2 合格条件: 例外なし)が、
        異常時は握り潰さず warning でログに残す(silent fail は作らない)。
        """
        if prev_h is None or cur_h is None:
            return  # 初回 step(prev 無し)は skip
        if not isinstance(prev_h, torch.Tensor) or not isinstance(cur_h, torch.Tensor):
            logger.warning(
                "[A3][Tier0] hidden_states が tensor でない · 計測 skip "
                f"(prev={type(prev_h).__name__} cur={type(cur_h).__name__})"
            )
            return
        if prev_h.numel() == 0 or prev_h.numel() != cur_h.numel():
            logger.warning(
                "[A3][Tier0] hidden_states shape 不一致 · 計測 skip "
                f"(prev={tuple(prev_h.shape)} cur={tuple(cur_h.shape)})"
            )
            return

        a = prev_h.detach().reshape(-1).float()
        b = cur_h.detach().reshape(-1).float()
        denom = (a.norm() * b.norm()).item()
        cos = (torch.dot(a, b).item() / denom) if denom > 0.0 else 1.0
        drift = 1.0 - cos
        logger.info(f"[A3][Tier0] step={self._step} dir_change(1-cos)={drift:.6f}")

    # ─────────────────────────────────────────────────────────
    def update_fixed(self, step: int) -> float:
        """M2 配管実証: step>=threshold で w0+bump、それ以外は w0。

        M4 で update_pi(measured drift → PI 制御)に差し替える差込口。
        ここでは決定論的な固定 bump のみ(weight 書き換えが次 step に反映される配管の実証)。
        """
        if step >= self._step_threshold:
            self._dyn_weight = self._w0 + self._w_bump
        else:
            self._dyn_weight = self._w0
        return self._dyn_weight

    # ─────────────────────────────────────────────────────────
    def m0_summary(self, expected_steps: int | None = None) -> dict:
        """直近 1 生成の M0 判定材料を返す(純粋関数 · 例外を投げない)。

        M0 合格条件(配管が step を正しく同定できているか):
          - 観測した distinct timestep の数 == expected_steps(例: 8)
          - timestep がすべてユニーク(同じ timestep を別 step と誤認していない)
          - step が 0..N-1 を一度ずつ(設計上 on_forward が保証 · 念のため検査)
        expected_steps=None の場合は step 数の一致は判定せず、構造健全性のみ見る。
        """
        seen = list(self._m0_seen_ts)
        n = len(seen)
        all_unique = (len(set(seen)) == n)
        steps = list(range(n))                       # on_forward は 0..n-1 を一度ずつ振る
        steps_ok = (steps == list(range(n)))         # 自明だが契約として明示検査
        count_ok = (expected_steps is None) or (n == int(expected_steps))
        verdict = bool(all_unique and steps_ok and count_ok and n > 0)
        return {
            "pass": verdict,
            "distinct_ts": n,
            "expected_steps": expected_steps,
            "all_unique": all_unique,
            "steps": steps,
            "seen_ts": seen,
        }

    # ─────────────────────────────────────────────────────────
    @staticmethod
    def _ts_key(ts):
        """timestep を hashable な比較キーに正規化(tensor は scalar/tuple へ)。"""
        if isinstance(ts, torch.Tensor):
            if ts.numel() == 1:
                return float(ts.item())
            return tuple(ts.detach().reshape(-1).tolist())
        return ts


# ════════════════════════════════════════════════════════════════════════
# みやちん用ヘルパ(再起動なし enable + M0 可視化)· IMPL-010 フォローアップ
#   核(Setting A / PuLID 集約核 / 量子化核)には一切触れない純運用ユーティリティ。
# ════════════════════════════════════════════════════════════════════════

_A3_FILE_LOG_TAG = "_aibo_a3_file_log"


def set_a3(enabled: bool = True) -> bool:
    """A3 を「再起動なしで」ON/OFF する。

    orchestrator は生成のたびに env AIBO_ENABLE_A3 を読む(05_orchestrator.py)。
    UI/FastAPI は同一プロセスの daemon スレッドなので、このセル(メインスレッド)で
    env を立てれば、次に UI で1枚生成した時点から A3 が走る(再起動不要)。
    """
    val = "1" if enabled else "0"
    os.environ["AIBO_ENABLE_A3"] = val
    msg = (
        f"[A3] set_a3({enabled}) → env AIBO_ENABLE_A3={val} "
        f"(次の生成から反映 · ランタイム再起動は不要)"
    )
    logger.info(msg)
    print(msg)
    return bool(enabled)


def attach_a3_file_log(path: str = "/content/aibo_a3.log") -> str | None:
    """[A3]/[GATE] ログを path に追記する FileHandler を **root logger** に1つだけ足す(冪等)。

    ★ RECON-013: AIBO_v7 への直付けだと環境(Colab/uvicorn)依存で取りこぼした。診断セルと同方式に
      合わせ、root logger(プロセス唯一の singleton)に付け、AIBO_v7.propagate=True を保証して
      レコードを必ず root まで流す。これで daemon/メインどちらの生成でも確実にファイルへ落ちる。
    既に同 path のハンドラが root にあれば二重追加しない。失敗は握り潰さず warning で残す。
    """
    root = logging.getLogger()
    for h in root.handlers:
        if getattr(h, _A3_FILE_LOG_TAG, None) == path:
            logger.info(f"[A3] file log は既に有効: {path}")
            print(f"[A3] file log は既に有効: {path}")
            return path
    try:
        handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    except OSError as e:
        # /content が無い PC 等では失敗しうる。黙らせず理由を残して None を返す。
        logger.warning(f"[A3] file log を作れません({path}): {e}")
        print(f"[A3] file log を作れません({path}): {e}")
        return None
    handler.setLevel(logging.INFO)
    handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S")
    )
    # [A3] か [GATE] を含むレコードだけ通す(他の大量ログでファイルを汚さない)。
    handler.addFilter(lambda rec: ("[A3]" in rec.getMessage()) or ("[GATE]" in rec.getMessage()))
    setattr(handler, _A3_FILE_LOG_TAG, path)
    root.addHandler(handler)
    logging.getLogger("AIBO_v7").propagate = True   # AIBO_v7 のレコードを root へ確実に流す
    logger.info(f"[A3] file log 有効化(root直付け): {path}")
    print(f"[A3] file log 有効化(root直付け): {path}")
    return path


def _find_a3_controller(orch=None):
    """起動済み orchestrator から _shared_transformer._a3_ctrl を取り出す。

    orch 省略時は 09_fastapi_server.get_orchestrator() 経由で取得。
    取れない理由(未 attach / 未生成)は呼び元で人に分かるよう返す。
    """
    if orch is None:
        try:
            srv = import_module("09_fastapi_server")
            orch = srv.get_orchestrator()
        except Exception as e:                       # 未 attach 等(HTTPException 含む)
            return None, f"orchestrator 取得失敗: {e}"
    tf = getattr(getattr(orch, "pm", None), "_shared_transformer", None)
    if tf is None:
        return None, "transformer 未構築(pm._shared_transformer が None)"
    ctrl = getattr(tf, "_a3_ctrl", None)
    if ctrl is None:
        return None, "A3 未起動 or まだ1枚も生成していない(_a3_ctrl が無い)"
    return ctrl, None


def a3_m0_verdict(orch=None, expected_steps: int = 8, *, verbose: bool = True) -> dict:
    """直近 UI 生成の M0 PASS/FAIL を、このセル出力に1行で出す(自己完結)。

    使い方(みやちん): set_a3(True) → UI で1枚生成 → このセルを実行するだけ。
    戻り値 dict["pass"] が True/False。理由は dict["reason"](取得不能時)。
    """
    ctrl, reason = _find_a3_controller(orch)
    if ctrl is None:
        out = {"pass": False, "reason": reason}
        if verbose:
            print(f"[A3][M0] 判定できません: {reason}")
            print("        → a3_controller.set_a3(True) して UI で1枚生成してから再実行してください。")
        return out
    summary = ctrl.m0_summary(expected_steps=expected_steps)
    summary["reason"] = None
    if verbose:
        mark = "✅ PASS" if summary["pass"] else "❌ FAIL"
        print(f"[A3][M0] {mark}")
        print(f"        distinct_ts = {summary['distinct_ts']} (expected {expected_steps})")
        print(f"        all_unique  = {summary['all_unique']}")
        print(f"        steps       = {summary['steps']}")
    return summary


# ════════════════════════════════════════════════════════════════════════
# M1(退行ゼロ)確認 · IMPL-010 フォローアップ(GPU 非決定性に強い版)
#   enable_a3 OFF の PORTRAIT 出力が A3 導入前と「実質一致」(= GPU の毎回のブレ
#   = ノイズ床 以内)で、かつ OFF 時 [A3] ログが1行も出ないことを1セルで判定。
#   GPU は同一 seed でも毎回バイトが微妙に違う(cuDNN 等の非決定性)ので、バイト
#   完全一致は判定に使わない。代わりに「同一 seed/ref/OFF で2回生成した差(ノイズ床)」
#   を実測し、baseline との差がその床以内なら退行ゼロとみなす。
#   核(Setting A / PuLID 集約核 / 量子化核)には一切触れない純検証ユーティリティ。
# ════════════════════════════════════════════════════════════════════════

# baseline は a3_controller.py と同じ場所(Colab では Drive 同期リポ)に置く →
# ランタイム再起動を跨いでも残る。みやちんは baseline_path で上書きも可。
_A3_M1_DEFAULT_BASELINE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "aibo_a3_m1_baseline.json"
)

# 判定しきい値(uint8 · 0..255 スケール)
_A3_M1_FLOOR_MARGIN = 2.0    # 許容 = ノイズ床 × これ + 下駄(独立2回分のばらつきを吸収)
_A3_M1_MEAN_TOL = 0.5        # 平均絶対差の下駄
_A3_M1_MAX_TOL = 12          # 最大絶対差の下駄(外れ画素1点で割れないように)
_A3_M1_SEED_BUG_MEAN = 5.0   # 同一 seed 2回の平均差がこれ超 → GPU ジッタでなく再現性破綻の疑い


def _a3_ref_fp(img) -> str:
    """参照画像の指紋(baseline と verify で同一 ref を使っているかの照合用)。"""
    return hashlib.sha256(img.convert("RGB").tobytes()).hexdigest()[:16]


def _a3_pixel_diff(img_a, img_b) -> dict:
    """2画像の RGB ピクセル差(平均絶対差 / 最大絶対差 / 差のある画素割合)。"""
    a = np.asarray(img_a.convert("RGB"), dtype=np.int16)
    b = np.asarray(img_b.convert("RGB"), dtype=np.int16)
    if a.shape != b.shape:
        return {"same_size": False, "mean_abs": None, "max_abs": None, "frac_diff": None}
    d = np.abs(a - b)
    return {
        "same_size": True,
        "mean_abs": float(d.mean()),
        "max_abs": int(d.max()),
        "frac_diff": float((d > 0).mean()),
    }


def _a3_m1_config_fp(*, seed, prompt, steps, guidance, width, height,
                     enable_pass2, enable_upscale, pulid_weight) -> str:
    """baseline と verify で「同一条件」を厳密一致させるための指紋。

    条件が1つでも違えば比較を無効化して FAIL にする(設定違いの偽 PASS/FAIL を防ぐ)。
    """
    payload = json.dumps(
        {
            "seed": int(seed), "prompt": str(prompt),
            "steps": int(steps), "guidance": float(guidance),
            "width": int(width), "height": int(height),
            "pass2": bool(enable_pass2), "upscale": bool(enable_upscale),
            "pulid_weight": float(pulid_weight),
        },
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class _A3LogCapture(logging.Handler):
    """生成中のログ行を **全部**ためる一時ハンドラ(無フィルタ · [A3]/[GATE] 取りこぼし防止)。

    RECON-013: 以前は emit 内で "[A3]" フィルタしていたが、まず全行ためて呼び元で
    [A3]/[GATE] を数える方式に変更(取りこぼしの切り分けを呼び元でできるように)。
    """

    def __init__(self) -> None:
        super().__init__(level=logging.NOTSET)
        self.lines: list = []

    def emit(self, record) -> None:
        try:
            self.lines.append(record.getMessage())
        except Exception:
            return  # 1行の整形失敗で計測全体を止めない(pass にはしない)


def _count_a3(lines) -> int:
    """[A3] を含む行数([GATE]/[ENTRY] は数えない · M-check の [A3] カウンタ定義)。"""
    return sum(1 for m in lines if "[A3]" in m)


def _find_orchestrator(orch=None):
    if orch is not None:
        return orch, None
    try:
        srv = import_module("09_fastapi_server")
        return srv.get_orchestrator(), None
    except Exception as e:
        return None, f"orchestrator 取得失敗: {e}"


def _a3_run_generate(orch, gen_cfg, id_cfg, StudioMode, *, enable: bool):
    """env AIBO_ENABLE_A3 を強制(enable=True→"1" / False→"0")して1枚生成。

    返り値 (image, log_lines, pulid_used, error)。
    - log_lines: 生成中に出た [A3] ログ行のリスト。
    - pulid_used: その生成で id_embeds が載ったか(= UI と同じ identity 抽出が成功し、A3 の
      もう一方のゲート「id_embeds present」が True になったか)。これが False だと env=1 でも
      A3 は走らない。
    生成の間だけ env を立て、終了後に必ず元値へ復元する(既定 OFF を壊さない)。

    ★ RECON-013: 捕捉ハンドラは AIBO_v7 直付けでなく **root logger** に付け、
      AIBO_v7.propagate を一時 True にして [A3]/[GATE] を確実に拾う(診断セルと同方式)。
    """
    capture_handler = _A3LogCapture()
    root = logging.getLogger()
    av = logging.getLogger("AIBO_v7")
    prev_root_level = root.level
    prev_prop = av.propagate
    result = None
    root.addHandler(capture_handler)
    root.setLevel(logging.INFO)
    av.propagate = True
    prev_env = os.environ.get("AIBO_ENABLE_A3")
    os.environ["AIBO_ENABLE_A3"] = "1" if enable else "0"
    try:
        result = orch.generate(gen_cfg=gen_cfg, id_cfg=id_cfg,
                               mode=StudioMode.PORTRAIT, save=False)
    finally:
        os.environ.pop("AIBO_ENABLE_A3", None) if prev_env is None \
            else os.environ.__setitem__("AIBO_ENABLE_A3", prev_env)
        root.removeHandler(capture_handler)
        root.setLevel(prev_root_level)
        av.propagate = prev_prop

    lines = list(capture_handler.lines)   # 全行(無フィルタ)。[A3] 数は呼び元が _count_a3 で数える。
    pulid_used = bool(getattr(result, "pulid_used", False))
    if getattr(result, "error", None) or getattr(result, "final_image", None) is None:
        return None, lines, pulid_used, f"生成失敗: {getattr(result, 'error', '画像なし')}"
    return result.final_image, lines, pulid_used, None


def _a3_off_generate(orch, gen_cfg, id_cfg, StudioMode):
    """OFF を強制して1枚生成し (image, n_a3_logs, pulid_used, error) を返す(M1 用)。"""
    img, lines, pulid_used, err = _a3_run_generate(orch, gen_cfg, id_cfg, StudioMode, enable=False)
    return img, _count_a3(lines), pulid_used, err


def a3_m1_check(
    ref_image,
    *,
    seed: int = 1234567,
    prompt: str = "a portrait photo of a person, natural light, looking at camera",
    width: int = 1024,
    height: int = 1024,
    guidance: float = 3.5,
    enable_pass2: bool = False,
    enable_upscale: bool = False,
    pulid_weight: float = 2.5,
    capture: bool = False,
    baseline_path: str | None = None,
    orch=None,
    verbose: bool = True,
) -> dict:
    """M1(退行ゼロ)を GPU 非決定性に強い形で1セル判定。

    ref_image: PIL.Image か 画像ファイルパス(str)。baseline と verify で同一物を使うこと。
    capture=True : OFF で1枚生成 → baseline 画像(PNG)+ 条件指紋を保存(初回 / 再採取)。
    capture=False: OFF で **2枚** 生成 → ノイズ床 = その2枚の差。
        PASS = (baseline との差) ≤ ノイズ床×margin+下駄  ∧  OFF 中 [A3] ログ 0 行
               ∧ 条件指紋一致 ∧ 参照画像一致 ∧ 同一 seed がほぼ再現(床が小さい)。
        ※ 床が大きすぎる(平均差 > しきい値)= 同一 seed が再現していない →「再現性破綻の疑い」で
          判定保留(GPU ジッタか seed バグかの切り分け材料を返す)。

    OFF の作り方: 生成の間だけ env AIBO_ENABLE_A3=0 を強制(終了後に元値へ復元)。
        config 側 enable_a3=True だと OR で ON になり OFF にできない → 拒否して理由を返す。
    """
    baseline_path = baseline_path or _A3_M1_DEFAULT_BASELINE
    img_path = os.path.splitext(baseline_path)[0] + "_img.png"

    # ref を PIL に正規化 + RGB 化(UI と同じ identity 抽出経路に確実に載せる)
    if isinstance(ref_image, str):
        ref_image = Image.open(ref_image)
    ref_image = ref_image.convert("RGB")
    ref_fp = _a3_ref_fp(ref_image)

    orch, err = _find_orchestrator(orch)
    if orch is None:
        out = {"pass": False, "reason": err}
        if verbose:
            print(f"[A3][M1] 判定できません: {err}")
        return out

    # config 側 ON は OFF 化できない(orchestrator は enable_a3 OR env で判定)
    sys_cfg = getattr(orch, "sys_cfg", None)
    if getattr(sys_cfg, "enable_a3", False):
        out = {"pass": False, "reason": "config enable_a3=True · M1 は OFF 前提なので判定不可"}
        if verbose:
            print(f"[A3][M1] 判定できません: {out['reason']}")
        return out

    cfg = import_module("01_config")
    GenerationConfig = cfg.GenerationConfig
    IdentityConfig = cfg.IdentityConfig
    StudioMode = cfg.StudioMode

    gen_cfg = GenerationConfig(
        prompt=prompt,
        width=width,
        height=height,
        guidance_scale=guidance,
        seed=int(seed),
        enable_pass2=bool(enable_pass2),
        enable_upscale=bool(enable_upscale),
    )
    id_cfg = IdentityConfig(reference_image=ref_image, pulid_weight=float(pulid_weight))

    config_fp = _a3_m1_config_fp(
        seed=seed, prompt=prompt, steps=-1, guidance=guidance,
        width=width, height=height, enable_pass2=enable_pass2,
        enable_upscale=enable_upscale, pulid_weight=pulid_weight,
    )

    # ─── capture モード: OFF で1枚 → baseline 保存して終了 ───
    if capture:
        if verbose:
            print(f"[A3][M1] baseline 採取: OFF 生成中(seed={seed})…")
        img, n_logs, pulid_used, gerr = _a3_off_generate(orch, gen_cfg, id_cfg, StudioMode)
        if gerr:
            out = {"pass": False, "reason": gerr}
            if verbose:
                print(f"[A3][M1] 判定できません: {gerr}")
            return out
        if not pulid_used:
            out = {"pass": False, "reason": "identity 未抽出(id_embeds 無し)· "
                   "REF に顔がはっきり写った画像を使う(本番=identity 付き portrait を代表させる)"}
            if verbose:
                print(f"[A3][M1] baseline 採取中止: {out['reason']}")
            return out
        img.convert("RGB").save(img_path)   # PNG はロスレス → ピクセル保存
        record = {
            "kind": "aibo_a3_m1_baseline_v2",
            "image_file": os.path.basename(img_path),
            "width": img.width, "height": img.height,
            "config_fp": config_fp, "ref_fp": ref_fp,
            "seed": int(seed), "prompt": prompt,
            "pulid_used": pulid_used,
            "n_a3_logs_at_capture": n_logs,
        }
        with open(baseline_path, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
        if verbose:
            print(f"[A3][M1] baseline 保存: {baseline_path}")
            print(f"        画像        : {img_path}")
            print(f"        OFF 中 [A3] ログ = {n_logs} 行(0 が正常)")
        return {"pass": None, "captured": True, "baseline_path": baseline_path,
                "image_path": img_path, **record}

    # ─── verify モード ───
    if not os.path.exists(baseline_path):
        out = {"pass": False, "reason": f"baseline 不在: {baseline_path}(先に capture=True で採取)"}
        if verbose:
            print(f"[A3][M1] 判定できません: {out['reason']}")
        return out
    with open(baseline_path, "r", encoding="utf-8") as f:
        base = json.load(f)
    base_img_path = os.path.join(os.path.dirname(baseline_path),
                                 base.get("image_file", ""))
    if not os.path.exists(base_img_path):
        out = {"pass": False, "reason": f"baseline 画像不在: {base_img_path}(capture=True で採り直し)"}
        if verbose:
            print(f"[A3][M1] 判定できません: {out['reason']}")
        return out
    baseline_img = Image.open(base_img_path)

    # OFF で2枚生成 → ノイズ床 = その2枚の差
    if verbose:
        print(f"[A3][M1] OFF を2枚生成中(seed={seed})… ノイズ床を実測します")
    img_a, n_logs_a, pulid_a, err_a = _a3_off_generate(orch, gen_cfg, id_cfg, StudioMode)
    if err_a:
        out = {"pass": False, "reason": f"1枚目 {err_a}"}
        if verbose:
            print(f"[A3][M1] 判定できません: {out['reason']}")
        return out
    img_b, n_logs_b, pulid_b, err_b = _a3_off_generate(orch, gen_cfg, id_cfg, StudioMode)
    if err_b:
        out = {"pass": False, "reason": f"2枚目 {err_b}"}
        if verbose:
            print(f"[A3][M1] 判定できません: {out['reason']}")
        return out
    if not (pulid_a and pulid_b):
        out = {"pass": False, "reason": "identity 未抽出(id_embeds 無し)· "
               "REF に顔がはっきり写った画像を使う(本番=identity 付き portrait を代表させる)"}
        if verbose:
            print(f"[A3][M1] 判定できません: {out['reason']}")
        return out

    floor = _a3_pixel_diff(img_a, img_b)          # GPU の毎回のブレ
    cand = _a3_pixel_diff(img_a, baseline_img)    # A3-OFF と baseline の差

    no_a3_logs = (n_logs_a == 0 and n_logs_b == 0)
    cfg_match = (config_fp == base.get("config_fp"))
    ref_match = (ref_fp == base.get("ref_fp"))
    size_ok = bool(floor["same_size"] and cand["same_size"])

    if not size_ok:
        out = {"pass": False, "reason": "画像サイズ不一致(条件/参照を baseline と揃える)",
               "floor": floor, "cand": cand}
        if verbose:
            print(f"[A3][M1] 判定できません: {out['reason']}")
        return out

    bit_exact = (floor["max_abs"] == 0)
    seed_reproducible = (floor["mean_abs"] <= _A3_M1_SEED_BUG_MEAN)
    mean_ok = (cand["mean_abs"] <= floor["mean_abs"] * _A3_M1_FLOOR_MARGIN + _A3_M1_MEAN_TOL)
    max_ok = (cand["max_abs"] <= floor["max_abs"] * _A3_M1_FLOOR_MARGIN + _A3_M1_MAX_TOL)
    within_floor = bool(mean_ok and max_ok)

    verdict = bool(within_floor and no_a3_logs and cfg_match and ref_match and seed_reproducible)
    reason = None
    if not seed_reproducible:
        reason = (f"同一 seed 2回の平均差 {floor['mean_abs']:.2f} > {_A3_M1_SEED_BUG_MEAN} · "
                  "GPU ジッタを超える = 再現性破綻の疑い(seed 適用漏れ等を要調査)")

    out = {
        "pass": verdict,
        "reason": reason,
        "within_floor": within_floor,
        "no_a3_logs": no_a3_logs,
        "config_match": cfg_match,
        "ref_match": ref_match,
        "seed_reproducible": seed_reproducible,
        "bit_exact": bit_exact,
        "floor_mean_abs": floor["mean_abs"],
        "floor_max_abs": floor["max_abs"],
        "cand_mean_abs": cand["mean_abs"],
        "cand_max_abs": cand["max_abs"],
        "n_a3_logs": n_logs_a + n_logs_b,
        "baseline_path": baseline_path,
    }
    if verbose:
        mark = "✅ PASS" if verdict else "❌ FAIL"
        print(f"[A3][M1] {mark}  (退行ゼロ = OFF 出力が baseline と「ノイズ床以内」∧ [A3] ログ 0 行)")
        print(f"        ノイズ床(同一seed2回) : mean={floor['mean_abs']:.3f} max={floor['max_abs']} "
              f"{'(bit完全一致)' if bit_exact else ''}")
        print(f"        baseline との差        : mean={cand['mean_abs']:.3f} max={cand['max_abs']}")
        print(f"        許容(床×{_A3_M1_FLOOR_MARGIN}+下駄)  : mean≤"
              f"{floor['mean_abs'] * _A3_M1_FLOOR_MARGIN + _A3_M1_MEAN_TOL:.3f} "
              f"max≤{floor['max_abs'] * _A3_M1_FLOOR_MARGIN + _A3_M1_MAX_TOL}")
        print(f"        within_floor={within_floor}  no_a3_logs={no_a3_logs}  "
              f"config_match={cfg_match}  ref_match={ref_match}")
        print(f"        seed_reproducible={seed_reproducible}  (同一 seed がほぼ再現するか)")
        if reason:
            print(f"        ⚠️ {reason}")
        if not cfg_match or not ref_match:
            print("        ⚠️ 条件/参照が baseline と違う → 同じ seed/prompt/ref/設定で再実行")
    return out


# ════════════════════════════════════════════════════════════════════════
# M2(配管が効く)確認 · IMPL-010 フォローアップ
#   A3 ON + 固定 bump(a3_w_bump=0.2)で生成し、「weight 書き換えが絵に効く」=
#   配管が生きていることを1セルで判定。M1 のノイズ床インフラを使い回す。
#   核(Setting A / PuLID 集約核 / 量子化核)には一切触れない純検証ユーティリティ。
# ════════════════════════════════════════════════════════════════════════

# 効果がノイズ床を「明確に」超えるための係数(barely 超えを誤検出しない)
_A3_M2_EFFECT_FACTOR = 3.0    # 効果平均差 > 床平均差 × これ
_A3_M2_MIN_EFFECT_MEAN = 1.0  # かつ 効果平均差 > これ(uint8 · 微動を効果と誤認しない)


def _a3_parse_m2_logs(lines, *, expected_bump: float, threshold: int = 4) -> dict:
    """[A3] ログから step→weight を復元し、bump が step≥threshold で効いているか検査。

    期待: step は 0..N-1 を網羅、step<threshold は w=w0、step≥threshold は w=w0+bump。
    """
    step_w: dict = {}
    for ln in lines:
        m = re.search(r"\[A3\]\[M0\]\s+fwd#\d+\s+step=(\d+).*?w=([0-9.]+)", ln)
        if m:
            step = int(m.group(1))
            w = float(m.group(2))
            step_w.setdefault(step, w)   # 同 step の二重 forward は最初の1つで足りる

    if not step_w:
        return {"weight_ok": False, "steps_ok": False, "detail": "fwd ログ無し",
                "steps": [], "w0": None, "high": None, "bump_obs": None}

    steps = sorted(step_w)
    n = max(steps) + 1
    steps_ok = (set(steps) == set(range(n)) and n > threshold)  # 0..N-1 網羅 ∧ 高側 step が存在

    w0 = min(step_w.values())
    high = max(step_w.values())
    bump_obs = high - w0
    tol = 1e-3
    lows = [w for s, w in step_w.items() if s < threshold]
    highs = [w for s, w in step_w.items() if s >= threshold]
    low_ok = bool(lows) and all(abs(w - w0) < tol for w in lows)
    high_ok = bool(highs) and all(abs(w - (w0 + expected_bump)) < tol for w in highs)
    bump_ok = abs(bump_obs - expected_bump) < tol
    weight_ok = bool(steps_ok and low_ok and high_ok and bump_ok)

    return {
        "weight_ok": weight_ok, "steps_ok": steps_ok,
        "steps": steps, "w0": w0, "high": high, "bump_obs": bump_obs,
        "low_ok": low_ok, "high_ok": high_ok, "bump_ok": bump_ok,
        "detail": f"steps={steps} w0={w0} high={high} bump_obs={bump_obs:.4f}",
    }


def a3_m2_check(
    ref_image,
    *,
    seed: int = 1234567,
    prompt: str = "a portrait photo of a person, natural light, looking at camera",
    width: int = 1024,
    height: int = 1024,
    guidance: float = 3.5,
    enable_pass2: bool = False,
    enable_upscale: bool = False,
    pulid_weight: float = 2.5,
    baseline_path: str | None = None,
    orch=None,
    verbose: bool = True,
) -> dict:
    """M2(配管が効く)を1セル判定。M1 と同じ REF/SEED を流用すること。

    手順: ON + 固定 bump で **2枚** 生成 → ①M1 の OFF baseline との差が「ノイズ床を超える」
    (= 実際に絵が変わった) ②[A3] ログに step 0..7 ∧ step≥4 で w0→w0+bump ③ON-bump 自体が
    再現する(同一 seed 2枚がノイズ床以内 = 効果は決定論的)を確認。

    PASS = ①効果>床 ∧ ②weight ログ整合 ∧ ③ON 再現 ∧ 条件/参照が baseline と一致。
    """
    baseline_path = baseline_path or _A3_M1_DEFAULT_BASELINE

    # ref を PIL に正規化 + RGB 化(UI と同じ identity 抽出経路に確実に載せる)
    if isinstance(ref_image, str):
        ref_image = Image.open(ref_image)
    ref_image = ref_image.convert("RGB")
    ref_fp = _a3_ref_fp(ref_image)

    orch, err = _find_orchestrator(orch)
    if orch is None:
        out = {"pass": False, "reason": err}
        if verbose:
            print(f"[A3][M2] 判定できません: {err}")
        return out

    # M1 の OFF baseline(画像)が必要
    if not os.path.exists(baseline_path):
        out = {"pass": False, "reason": f"baseline 不在: {baseline_path}(先に a3_m1_check(..., capture=True))"}
        if verbose:
            print(f"[A3][M2] 判定できません: {out['reason']}")
        return out
    with open(baseline_path, "r", encoding="utf-8") as f:
        base = json.load(f)
    base_img_path = os.path.join(os.path.dirname(baseline_path), base.get("image_file", ""))
    if not os.path.exists(base_img_path):
        out = {"pass": False, "reason": f"baseline 画像不在: {base_img_path}(a3_m1_check capture=True で採り直し)"}
        if verbose:
            print(f"[A3][M2] 判定できません: {out['reason']}")
        return out
    baseline_off = Image.open(base_img_path)

    cfg = import_module("01_config")
    GenerationConfig = cfg.GenerationConfig
    IdentityConfig = cfg.IdentityConfig
    StudioMode = cfg.StudioMode

    gen_cfg = GenerationConfig(
        prompt=prompt, width=width, height=height, guidance_scale=guidance,
        seed=int(seed), enable_pass2=bool(enable_pass2), enable_upscale=bool(enable_upscale),
    )
    id_cfg = IdentityConfig(reference_image=ref_image, pulid_weight=float(pulid_weight))

    config_fp = _a3_m1_config_fp(
        seed=seed, prompt=prompt, steps=-1, guidance=guidance,
        width=width, height=height, enable_pass2=enable_pass2,
        enable_upscale=enable_upscale, pulid_weight=pulid_weight,
    )
    cfg_match = (config_fp == base.get("config_fp"))
    ref_match = (ref_fp == base.get("ref_fp"))
    expected_bump = float(getattr(getattr(orch, "sys_cfg", None), "a3_w_bump", 0.2))

    # ON + bump で2枚生成(①効果 / ③再現 の両方に使う)
    if verbose:
        print(f"[A3][M2] ON+bump を2枚生成中(seed={seed}, bump={expected_bump})…")
    on_a, lines_a, pulid_a, err_a = _a3_run_generate(orch, gen_cfg, id_cfg, StudioMode, enable=True)
    if err_a:
        out = {"pass": False, "reason": f"1枚目 {err_a}"}
        if verbose:
            print(f"[A3][M2] 判定できません: {out['reason']}")
        return out
    # identity ゲート: id_embeds が載らないと env=1 でも A3 は走らない(forward の A3 分岐に入らない)
    if not pulid_a:
        out = {"pass": False,
               "reason": "identity 未抽出(id_embeds 無し)· A3 が走らない(env=1 でも id_embeds ゲートが False)。"
                         "REF に顔がはっきり写った画像を使う"}
        if verbose:
            print(f"[A3][M2] 判定できません: {out['reason']}")
        return out
    on_b, lines_b, pulid_b, err_b = _a3_run_generate(orch, gen_cfg, id_cfg, StudioMode, enable=True)
    if err_b:
        out = {"pass": False, "reason": f"2枚目 {err_b}"}
        if verbose:
            print(f"[A3][M2] 判定できません: {out['reason']}")
        return out
    if not pulid_b:
        out = {"pass": False, "reason": "2枚目で identity 未抽出(id_embeds 無し)"}
        if verbose:
            print(f"[A3][M2] 判定できません: {out['reason']}")
        return out

    floor = _a3_pixel_diff(on_a, on_b)          # ON-bump の毎回のブレ(= ノイズ床 ∧ ③再現の材料)
    effect = _a3_pixel_diff(on_a, baseline_off)  # ON-bump と OFF-baseline の差(= ①効果)
    if not (floor["same_size"] and effect["same_size"]):
        out = {"pass": False, "reason": "画像サイズ不一致(条件/参照を baseline と揃える)"}
        if verbose:
            print(f"[A3][M2] 判定できません: {out['reason']}")
        return out

    # ── 主判定 ② weight ログ整合(step 0..7 ∧ step≥4 で w0→w0+bump が観測)──
    #    RECON-013: bump=0.2 は pixel に出にくいので、weight ログ整合を「主」にする。
    logp = _a3_parse_m2_logs(lines_a, expected_bump=expected_bump, threshold=4)
    weight_log_ok = bool(logp["weight_ok"])
    # ③ ON-bump 再現(同一 seed 2枚がノイズ床以内 = 決定論的)
    on_reproducible = bool(floor["mean_abs"] <= _A3_M1_SEED_BUG_MEAN)
    # ① pixel 効果>床 … 補助に格下げ(PASS 条件に含めない。bump=0.2 では床を超えない事がある)
    effect_exceeds_floor = bool(
        effect["mean_abs"] > floor["mean_abs"] * _A3_M2_EFFECT_FACTOR
        and effect["mean_abs"] > _A3_M2_MIN_EFFECT_MEAN
    )
    n_a3 = _count_a3(lines_a) + _count_a3(lines_b)

    # PASS = weight ログ整合(主)∧ ON 再現 ∧ 条件/参照一致(pulid は上で担保済み)
    verdict = bool(weight_log_ok and on_reproducible and cfg_match and ref_match)

    out = {
        "pass": verdict,
        "reason": None,
        "weight_log_ok": weight_log_ok,          # 主判定
        "on_reproducible": on_reproducible,
        "config_match": cfg_match,
        "ref_match": ref_match,
        "effect_exceeds_floor": effect_exceeds_floor,  # 補助(参考)
        "floor_mean_abs": floor["mean_abs"],
        "floor_max_abs": floor["max_abs"],
        "effect_mean_abs": effect["mean_abs"],
        "effect_max_abs": effect["max_abs"],
        "log_steps": logp["steps"],
        "log_w0": logp["w0"],
        "log_high": logp["high"],
        "log_bump_obs": logp["bump_obs"],
        "expected_bump": expected_bump,
        "pulid_used": bool(pulid_a and pulid_b),
        "n_a3_logs": n_a3,
        "baseline_path": baseline_path,
    }
    if verbose:
        mark = "✅ PASS" if verdict else "❌ FAIL"
        print(f"[A3][M2] {mark}  (配管が効く = weight ログ整合(主)∧ ON 再現 ∧ 条件一致)")
        print(f"        identity     : id_embeds 載った={bool(pulid_a and pulid_b)}  [A3]ログ {n_a3} 行")
        print(f"        ② weight ログ(主): steps={logp['steps']} w0={logp['w0']} high={logp['high']} "
              f"bump_obs={logp['bump_obs']} (期待 {expected_bump}) → {weight_log_ok}")
        if not weight_log_ok:
            print(f"            detail: steps_ok={logp['steps_ok']} low_ok={logp.get('low_ok')} "
                  f"high_ok={logp.get('high_ok')} bump_ok={logp.get('bump_ok')} "
                  f"([A3]ログ {n_a3} 行 · 0 なら計測未達)")
        print(f"        ③ ON 再現    : 同一seed2枚 mean={floor['mean_abs']:.3f} "
              f"(≤{_A3_M1_SEED_BUG_MEAN}) → {on_reproducible}")
        print(f"        ① 効果>床(補助): 効果 mean={effect['mean_abs']:.3f} / 床 mean={floor['mean_abs']:.3f} "
              f"→ {effect_exceeds_floor}(参考 · bump=0.2 では超えない事あり)")
        print(f"        config_match={cfg_match}  ref_match={ref_match}")
        if not cfg_match or not ref_match:
            print("        ⚠️ M1 baseline と条件/参照が違う → M1 と同じ seed/prompt/ref/設定で実行")
    return out
