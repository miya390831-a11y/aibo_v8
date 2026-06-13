# ═══════════════════════════════════════════════════════════════════════════
# EXP-032b prebuild — Hyper-FLUX を“最初から載せない”構築にする(SystemConfig override)
#
#   用途: EXP-032b Part②(exp_032b_DnoHyper.py)用。Hyper LoRA 未ロードのスタックを作るため、
#         SystemConfig の既定を enable_hyper_flux=False / hyper_flux_weight=0.0 に書き換える。
#
#   ★実行順(必ずこの順・別 fresh runtime):
#     1) ランタイム再起動:  import os; os.kill(os.getpid(), 9)
#     2) 再起動後 **Cell 0 / setup を走らせる前に** 本ファイルを1行で実行:
#          exec(open("/content/drive/MyDrive/aibo_v7/exp_032b_prebuild.py", encoding="utf-8").read())
#     3) Cell 0 / setup を実行(= Hyper 未ロードのスタックが構築される)
#     4) exec(open(".../exp_032b_DnoHyper.py", encoding="utf-8").read())
#
#   なぜ __defaults__ を書き換えるか:
#     dataclass の field 既定は __init__ に焼かれる(クラス生成時に __defaults__ へ格納)。
#     class 属性への代入(SystemConfig.enable_hyper_flux=False)だけでは SystemConfig() の
#     生成値は変わらない。よって __init__.__defaults__ を直接書き換える(+ class 属性も保険で更新)。
#     02_colab_setup が import 時に SystemConfig を束縛しても同一クラスオブジェクトなので有効。
#
#   prod ファイルは編集しない(in-memory override のみ)。Setting A 7値には触れない。
# ═══════════════════════════════════════════════════════════════════════════
import importlib
import inspect

_cfg = importlib.import_module("01_config")
_SC = _cfg.SystemConfig

_OVERRIDES = (("enable_hyper_flux", False), ("hyper_flux_weight", 0.0))

_names = [p.name for p in inspect.signature(_SC.__init__).parameters.values() if p.name != "self"]
_defs = list(_SC.__init__.__defaults__ or ())
# __defaults__ は「既定を持つ末尾パラメータ群」に1:1対応する
_defaulted = _names[-len(_defs):] if _defs else []

_applied = []
_skipped = []
for _nm, _val in _OVERRIDES:
    if _nm in _defaulted:
        _defs[_defaulted.index(_nm)] = _val
        setattr(_SC, _nm, _val)          # class 属性も保険で更新
        _applied.append(f"{_nm}={_val}")
    else:
        _skipped.append(_nm)

_SC.__init__.__defaults__ = tuple(_defs)

# 検証: 新規 SystemConfig() が override を反映するか(prebuild の自己確認)
_probe = _SC()
_ok_enable = (getattr(_probe, "enable_hyper_flux", None) is False)
_ok_weight = (float(getattr(_probe, "hyper_flux_weight", 1.0)) == 0.0)

print("=" * 64)
print(f"[prebuild] SystemConfig defaults patched: {', '.join(_applied) if _applied else '(none)'}")
if _skipped:
    print(f"[prebuild][WARN] 既定引数に無く未適用: {_skipped}(SystemConfig の定義変更を疑う)")
print(f"[prebuild] 自己検証 SystemConfig(): enable_hyper_flux={_probe.enable_hyper_flux} "
      f"hyper_flux_weight={_probe.hyper_flux_weight}")
assert _ok_enable and _ok_weight, (
    "[prebuild][STOP] override が SystemConfig() に反映されていない。"
    "SystemConfig の定義/構築経路を確認(別名 import・再 import 等)。Cell 0 を走らせないこと。"
)
print("[prebuild] OK → 次に Cell 0 / setup を実行(Hyper 未ロードで構築されます)。")
print("=" * 64)
