# ═══════════════════════════════════════════════════════════════════════════
# EXP-033 案A検証 — OSS-16/14「<30s × 20step 品質」ワンセル（再起動→1行）
#
#   このファイル1つで ①Hyper OFF ②portrait 専用の最小 setup（ControlNet / IP-Adapter /
#   Redux は読まない=CN ロード OOM 回避）③OSS sigma 注入で D20/OSS16/OSS14 計測 を一気通貫。
#   既存 no-Hyper スタックがあれば再利用（再起動忘れの二重ビルド=OOM を防ぐ）。
#
#   ★使い方（os.kill の再起動だけは別=ランタイムメニュー/ボタンで）:
#     1) ランタイム再起動（ボタン、または別セルで  import os; os.kill(os.getpid(), 9) ）
#     2) 再起動後、このセルをコピペして実行（1行）:
#          exec(open("/content/drive/MyDrive/aibo_v7/exp_033_oss_oneshot.py", encoding="utf-8").read())
#
#   設計（prod 不変・コード実機確認・EXP-032b part2 と同型）:
#     ① Hyper OFF: build 前に sys_cfg を enable_hyper_flux=False / hyper_flux_weight=0.0 に上書き
#        → _build_nunchaku が Hyper LoRA を注入しない（04:480）。set_lora_strength は使わない。
#     ② portrait 専用 最小 setup: enable_controlnet/ip_adapter/redux=False で IdentityEngine の
#        controlnet/ip_adapter を None 化 → 生成は PuLID のみ（CN/IP 経路に入らない）。
#     ③ exec(exp_033_oss_core.py): OSS sigma 注入（dynamic-shift OFF=最終sigma 強制上書き）→
#        D20/OSS16/OSS14 生成 + [OBS] 検証ゲート（注入値 vs 実使用値）+ wall-clock + GFPGAN on/off + GRID。
#
#   VRAM: no-Hyper / no-CN / no-IP / no-Redux の INT4 PuLID は ~24GB で 40GB に収まる。
#   Setting A 7値・config 既定・production コードには触れない（in-memory override のみ）。判定は PO 目視。
# ═══════════════════════════════════════════════════════════════════════════
import os
from importlib import import_module

DRIVE = "/content/drive/MyDrive/aibo_v7"
CORE = os.path.join(DRIVE, "exp_033_oss_core.py")

srv = import_module("09_fastapi_server")

# ── 既存スタックがあれば再ビルドしない ────────────────────────────────────
_existing = None
try:
    _existing = srv.get_orchestrator()
except Exception:
    _existing = None

if _existing is not None and getattr(getattr(_existing, "pm", None), "pipe_base", None) is not None:
    print("[oneshot] 既存 orchestrator を再利用（再ビルドしない）。")
    print(f"[oneshot]   enable_hyper_flux={getattr(_existing.sys_cfg,'enable_hyper_flux',None)} "
          f"_hyper_flux_loaded={getattr(_existing.pm,'_hyper_flux_loaded',None)}")
else:
    print("=" * 72)
    print("[oneshot] ① Hyper OFF + ② portrait 専用 最小 setup（CN/IP/Redux 読まない）")
    print("=" * 72)
    main_mod = import_module("07_main")
    m = main_mod.AiboMain()

    assert m.phase_a_bootstrap(), "[oneshot][STOP] Phase A(bootstrap)失敗"
    assert m.phase_b_resolve_strategy(), "[oneshot][STOP] Phase B(strategy)失敗"

    # ① Hyper OFF + portrait-only（build 前に sys_cfg instance を上書き）
    m.sys_cfg.enable_hyper_flux = False
    m.sys_cfg.hyper_flux_weight = 0.0
    m.sys_cfg.enable_controlnet = False
    m.sys_cfg.enable_ip_adapter = False
    m.sys_cfg.enable_redux = False
    print(f"[oneshot] sys_cfg override: enable_hyper_flux={m.sys_cfg.enable_hyper_flux} "
          f"enable_controlnet={m.sys_cfg.enable_controlnet} "
          f"enable_ip_adapter={m.sys_cfg.enable_ip_adapter} "
          f"enable_redux={m.sys_cfg.enable_redux}")

    assert m.phase_c_build_pipeline(), "[oneshot][STOP] Phase C(build)失敗"

    # ② 軽量 Phase D: IdentityEngine だけ構築（CN/IP の lazy_init は呼ばない）
    m.identity_engine = m.ident.IdentityEngine(m.sys_cfg)
    print(f"[oneshot] IdentityEngine: controlnet={m.identity_engine.controlnet} "
          f"ip_adapter={m.identity_engine.ip_adapter}（=None なら portrait=PuLID のみ）")

    assert m.phase_e_assets(), "[oneshot][STOP] Phase E(assets)失敗"
    assert m.phase_f_orchestrator(), "[oneshot][STOP] Phase F(orchestrator)失敗"

    srv.attach_orchestrator(m.orchestrator, m.pipeline_mgr)
    print(f"[oneshot] orchestrator attached。"
          f"_hyper_flux_loaded={getattr(m.pipeline_mgr,'_hyper_flux_loaded',None)} "
          f"enable_hyper_flux={m.sys_cfg.enable_hyper_flux}")
    print("=" * 72)

# ── ③ OSS 実験 core を実行（no-Hyper / INT4 検証は core 冒頭で実施）──────────
assert os.path.exists(CORE), f"[oneshot][STOP] {CORE} が無い（Drive 同期を確認）"
print(f"[oneshot] ③ exec: {CORE}")
exec(open(CORE, encoding="utf-8").read())
