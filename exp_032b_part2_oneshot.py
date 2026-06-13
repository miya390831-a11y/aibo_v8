# ═══════════════════════════════════════════════════════════════════════════
# EXP-032b Part② ワンセル — 再起動後にコピペ1行で D16/D28(no-Hyper, portrait-only)
#
#   このファイル1つで ①Hyper OFF ②portrait 専用の最小 setup(ControlNet / IP-Adapter は
#   読まない=さっきの CN ロード OOM 回避)③D16/D28 生成 を一気通貫で行う。
#
#   ★使い方(os.kill の再起動だけは別=ランタイムメニュー/ボタンで):
#     1) ランタイム再起動(ボタン、または別セルで  import os; os.kill(os.getpid(), 9) )
#     2) 再起動後、このセルをコピペして実行(1行):
#          exec(open("/content/drive/MyDrive/aibo_v7/exp_032b_part2_oneshot.py", encoding="utf-8").read())
#
#   設計(prod 不変・コード実機確認):
#     ① Hyper OFF: SystemConfig を build 前に enable_hyper_flux=False / hyper_flux_weight=0.0 に
#        instance 上書き(AiboMain インスタンスを握れるので __defaults__ patch は不要)。
#        → _build_nunchaku が Hyper LoRA を注入しない(04:480)。set_lora_strength は一切使わない。
#     ② portrait 専用 最小 setup: AiboMain の Phase A→C→(軽量 D)→E→F のみ。
#        - build() は ControlNet を読まない(CN は ensure_controlnet の lazy・04:600)。
#        - IP-Adapter は Phase D の lazy_init で読まれる → ★その lazy_init を呼ばない。
#        - さらに enable_controlnet=False / enable_ip_adapter=False で IdentityEngine の
#          controlnet/ip_adapter を None 化(03:1490-1493)→ 生成時に CN/IP 経路へ入らない
#          (portrait=PuLID のみ)。enable_redux=False で Redux prior も読まない(VRAM 節約)。
#        - orchestrator を 09_fastapi_server に attach(_depth_find_orch が拾えるように)。
#     ③ exec(exp_032b_DnoHyper.py): Hyper 未ロードを冒頭検証 → D16/D28 生成 → GRID/[OBS]。
#
#   VRAM: no-Hyper / no-CN / no-IP / no-Redux の INT4 PuLID は ~24GB で 40GB に収まる。
#   Setting A 7値・config 既定・production コードには触れない(in-memory override のみ)。判定は PO 目視。
# ═══════════════════════════════════════════════════════════════════════════
import os
from importlib import import_module

DRIVE = "/content/drive/MyDrive/aibo_v7"
DNOHYPER = os.path.join(DRIVE, "exp_032b_DnoHyper.py")

srv = import_module("09_fastapi_server")

# ── 既存スタックがあれば再ビルドしない(再起動忘れの二重ビルド=OOM を防ぐ)──
_existing = None
try:
    _existing = srv.get_orchestrator()
except Exception:
    _existing = None

if _existing is not None and getattr(getattr(_existing, "pm", None), "pipe_base", None) is not None:
    print("[oneshot] 既存 orchestrator を再利用(再ビルドしない)。")
    print(f"[oneshot]   enable_hyper_flux={getattr(_existing.sys_cfg,'enable_hyper_flux',None)} "
          f"_hyper_flux_loaded={getattr(_existing.pm,'_hyper_flux_loaded',None)}")
else:
    print("=" * 72)
    print("[oneshot] ① Hyper OFF + ② portrait 専用 最小 setup(CN/IP/Redux 読まない)")
    print("=" * 72)
    main_mod = import_module("07_main")
    m = main_mod.AiboMain()

    assert m.phase_a_bootstrap(), "[oneshot][STOP] Phase A(bootstrap)失敗"
    assert m.phase_b_resolve_strategy(), "[oneshot][STOP] Phase B(strategy)失敗"

    # ① Hyper OFF + portrait-only(build 前に sys_cfg instance を上書き)
    m.sys_cfg.enable_hyper_flux = False     # Hyper LoRA を注入しない(04:480)
    m.sys_cfg.hyper_flux_weight = 0.0
    m.sys_cfg.enable_controlnet = False     # CN を読まない(IdentityEngine.controlnet=None)
    m.sys_cfg.enable_ip_adapter = False     # IP を読まない(IdentityEngine.ip_adapter=None)
    m.sys_cfg.enable_redux = False          # Redux prior を読まない(VRAM 節約)
    print(f"[oneshot] sys_cfg override: enable_hyper_flux={m.sys_cfg.enable_hyper_flux} "
          f"enable_controlnet={m.sys_cfg.enable_controlnet} "
          f"enable_ip_adapter={m.sys_cfg.enable_ip_adapter} "
          f"enable_redux={m.sys_cfg.enable_redux}")

    assert m.phase_c_build_pipeline(), "[oneshot][STOP] Phase C(build)失敗"

    # ② 軽量 Phase D: IdentityEngine だけ構築(CN/IP の lazy_init は呼ばない)
    m.identity_engine = m.ident.IdentityEngine(m.sys_cfg)
    print(f"[oneshot] IdentityEngine: controlnet={m.identity_engine.controlnet} "
          f"ip_adapter={m.identity_engine.ip_adapter}(=None なら portrait=PuLID のみ)")

    assert m.phase_e_assets(), "[oneshot][STOP] Phase E(assets)失敗"
    assert m.phase_f_orchestrator(), "[oneshot][STOP] Phase F(orchestrator)失敗"

    srv.attach_orchestrator(m.orchestrator, m.pipeline_mgr)
    print(f"[oneshot] orchestrator attached。"
          f"_hyper_flux_loaded={getattr(m.pipeline_mgr,'_hyper_flux_loaded',None)} "
          f"enable_hyper_flux={m.sys_cfg.enable_hyper_flux}")
    print("=" * 72)

# ── ③ D16/D28 生成(Hyper 未ロード検証は DnoHyper 冒頭で実施)──────────────
assert os.path.exists(DNOHYPER), f"[oneshot][STOP] {DNOHYPER} が無い(Drive 同期を確認)"
print(f"[oneshot] ③ exec: {DNOHYPER}")
exec(open(DNOHYPER, encoding="utf-8").read())
