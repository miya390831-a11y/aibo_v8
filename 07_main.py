"""
================================================================================
🌌 AIBO CYBER STUDIO v7.2 · Section 7 · Main Entry Point
================================================================================

📌 ファイル名: 07_main.py

📌 このファイルの責務:
    全 6 セクションを統合する司令塔。

    run() を呼ぶと以下の Phase が順次実行される:
      Phase A: Bootstrap     (Drive マウント + 依存 install + Nunchaku + PuLID clone)
      Phase B: 戦略確定
      Phase C: Pipeline build (FLUX モデル DL · 5-10 分)
      Phase D: Identity 初期化
      Phase E: AssetManager 初期化
      Phase F: Orchestrator 初期化
      Phase G: UI 起動 (share=True で公開 URL 発行)

    各 Phase でエラーが出た場合は詳細ログを出力し、
    可能なものは安全側にフォールバック (例: ControlNet 失敗 → OFF にして続行)。

依存:
    - 01_config.py
    - 02_colab_setup.py
    - 03_identity_engine.py
    - 04_pipeline_manager.py
    - 05_orchestrator.py
    - 06_ui.py

使い方 (Colab セル):
    from importlib import import_module
    main = import_module("07_main")
    main.run()

Author: 🥷 CTO くろうど
Date:   2026-05-03
Version: v7.2
================================================================================
"""

from __future__ import annotations

import sys
import time
import traceback
from importlib import import_module
from typing import Any, Optional


# ─── 各セクションの動的 import (実行時に解決) ───
def _import_modules():
    """全モジュールをまとめて import"""
    return {
        "cfg":   import_module("01_config"),
        "setup": import_module("02_colab_setup"),
        "ident": import_module("03_identity_engine"),
        "pipe":  import_module("04_pipeline_manager"),
        "orch":  import_module("05_orchestrator"),
        "ui":    import_module("06_ui"),
    }


# ============================================================================
# 🌌 Section 7.1 · AiboMain (統合司令塔)
# ============================================================================

class AiboMain:
    """
    全 7 セクションを統合する司令塔。

    使い方:
        m = AiboMain()
        m.run()                  # 全自動 (Bootstrap + UI 起動)

        # 段階的実行 (デバッグ用):
        m.phase_a_bootstrap()
        m.phase_c_build_pipeline()
        m.phase_g_launch_ui()
    """

    def __init__(self):
        self.modules = _import_modules()
        self.cfg = self.modules["cfg"]
        self.setup_mod = self.modules["setup"]
        self.ident = self.modules["ident"]
        self.pipe = self.modules["pipe"]
        self.orch_mod = self.modules["orch"]
        self.ui_mod = self.modules["ui"]
        self.logger = self.cfg.logger

        # ─── 各 Phase で構築されるオブジェクト ───
        self.sys_cfg = None
        self.bootstrap = None
        self.pipeline_mgr = None
        self.identity_engine = None
        self.asset_mgr = None
        self.orchestrator = None
        self.ui_app = None

        # ─── 進捗計測 ───
        self._phase_times: dict[str, float] = {}

    # ────────────────────────────────────────
    # Phase A · Bootstrap (Drive + 依存 + Nunchaku + PuLID)
    # ────────────────────────────────────────

    def phase_a_bootstrap(self, *, skip_if_done: bool = True) -> bool:
        """Drive マウント + 依存ライブラリ + Nunchaku install + PuLID clone"""
        self.logger.info("=" * 60)
        self.logger.info("🚀 PHASE A · Bootstrap")
        self.logger.info("=" * 60)
        t0 = time.perf_counter()

        try:
            self.sys_cfg = self.cfg.SystemConfig()
            self.bootstrap = self.setup_mod.ColabBootstrap(self.sys_cfg)

            # 既に Bootstrap 済みなら skip 判定
            if skip_if_done and self.sys_cfg.strategy is not None:
                self.logger.info("ℹ️ 既に SystemConfig.strategy が確定済 · Bootstrap 軽量版で実行")

            results = self.bootstrap.run()

            # 失敗判定 (bool False のみ · "(not needed)" 等の文字列は除外)
            ni = results.get("nunchaku_installed")
            if ni is False and self.sys_cfg.strategy is not None and self.sys_cfg.strategy.is_nunchaku():
                self.logger.warning("⚠️ Nunchaku install 失敗 · 戦略は GGUF にフォールバック済")

            self._phase_times["a_bootstrap"] = time.perf_counter() - t0
            self.logger.info(f"✅ Phase A 完了 ({self._phase_times['a_bootstrap']:.1f}s)")
            return True

        except Exception as e:
            self.logger.error(f"❌ Phase A 失敗: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # ────────────────────────────────────────
    # Phase B · 戦略確定 (Bootstrap 内で済むが念押し)
    # ────────────────────────────────────────

    def phase_b_resolve_strategy(self) -> bool:
        self.logger.info("=" * 60)
        self.logger.info("🔍 PHASE B · 戦略確定")
        self.logger.info("=" * 60)

        if self.sys_cfg is None:
            self.sys_cfg = self.cfg.SystemConfig()

        strategy = self.sys_cfg.resolve_strategy()
        self.logger.info(f"   戦略: {strategy.kind.value}")
        self.logger.info(f"   PuLID 注入方式: {strategy.pulid_injection_method()}")
        self.logger.info(f"   LoRA API: {strategy.lora_api()}")
        return True

    # ────────────────────────────────────────
    # Phase C · Pipeline build (FLUX モデル DL · 5-10 分)
    # ────────────────────────────────────────

    def phase_c_build_pipeline(self) -> bool:
        """FLUX/Nunchaku モデルをロードして pipeline を構築"""
        self.logger.info("=" * 60)
        self.logger.info("🏛️ PHASE C · Pipeline Build (FLUX モデル DL · 重い)")
        self.logger.info("=" * 60)
        t0 = time.perf_counter()

        try:
            self.pipeline_mgr = self.pipe.FluxA100PipelineManager(self.sys_cfg)
            ok = self.pipeline_mgr.build()

            if not ok:
                self.logger.error("❌ Pipeline build 失敗")
                return False

            self._phase_times["c_pipeline"] = time.perf_counter() - t0
            self.logger.info(f"✅ Phase C 完了 ({self._phase_times['c_pipeline']:.1f}s)")
            self.logger.info(f"   Pipeline status: {self.pipeline_mgr.status()}")
            return True

        except Exception as e:
            self.logger.error(f"❌ Phase C 失敗: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # ────────────────────────────────────────
    # Phase D · Identity 初期化
    # ────────────────────────────────────────

    def phase_d_identity(self) -> bool:
        """IdentityEngine + 各サブエンジンの初期化"""
        self.logger.info("=" * 60)
        self.logger.info("🌌 PHASE D · Identity Engine 初期化")
        self.logger.info("=" * 60)
        t0 = time.perf_counter()

        try:
            self.identity_engine = self.ident.IdentityEngine(self.sys_cfg)

            # ControlNet を pipeline の前に lazy_init (重い · オプション)
            if self.identity_engine.controlnet:
                ok = self.identity_engine.controlnet.lazy_init()
                if not ok:
                    self.logger.warning("⚠️ ControlNet 初期化失敗 · ControlNet なしで続行")

            # IP-Adapter は pipeline.load_ip_adapter() を呼ぶので pipeline build 後に必要
            if self.identity_engine.ip_adapter:
                ok = self.identity_engine.ip_adapter.lazy_init(self.pipeline_mgr.pipe_base)
                if not ok:
                    self.logger.warning("⚠️ IP-Adapter 初期化失敗 · IP-Adapter なしで続行")

            self._phase_times["d_identity"] = time.perf_counter() - t0
            self.logger.info(f"✅ Phase D 完了 ({self._phase_times['d_identity']:.1f}s)")
            return True

        except Exception as e:
            self.logger.error(f"❌ Phase D 失敗: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # ────────────────────────────────────────
    # Phase E · AssetManager 初期化
    # ────────────────────────────────────────

    def phase_e_assets(self) -> bool:
        """LoRA + Upscaler + ReferenceDB の統合管理"""
        self.logger.info("=" * 60)
        self.logger.info("📦 PHASE E · Asset Manager")
        self.logger.info("=" * 60)
        t0 = time.perf_counter()

        try:
            self.asset_mgr = self.pipe.AssetManager(self.sys_cfg, self.pipeline_mgr)
            self._phase_times["e_assets"] = time.perf_counter() - t0
            self.logger.info(f"✅ Phase E 完了 ({self._phase_times['e_assets']:.1f}s)")
            return True

        except Exception as e:
            self.logger.error(f"❌ Phase E 失敗: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # ────────────────────────────────────────
    # Phase F · Orchestrator 初期化
    # ────────────────────────────────────────

    def phase_f_orchestrator(self) -> bool:
        """生成司令塔の初期化"""
        self.logger.info("=" * 60)
        self.logger.info("🎬 PHASE F · Orchestrator")
        self.logger.info("=" * 60)
        t0 = time.perf_counter()

        try:
            self.orchestrator = self.orch_mod.CharacterOrchestrator(
                sys_cfg=self.sys_cfg,
                pipeline_mgr=self.pipeline_mgr,
                identity_engine=self.identity_engine,
                asset_mgr=self.asset_mgr,
            )
            self._phase_times["f_orchestrator"] = time.perf_counter() - t0
            self.logger.info(f"✅ Phase F 完了 ({self._phase_times['f_orchestrator']:.1f}s)")
            return True

        except Exception as e:
            self.logger.error(f"❌ Phase F 失敗: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # ────────────────────────────────────────
    # Phase G · UI 起動
    # ────────────────────────────────────────

    def phase_g_launch_ui(
        self,
        *,
        share: bool = True,
        server_port: int = 7860,
        inbrowser: bool = False,
        debug: bool = False,
    ) -> bool:
        """Gradio UI を起動 · share=True で公開 URL 発行"""
        self.logger.info("=" * 60)
        self.logger.info("🚀 PHASE G · UI 起動")
        self.logger.info("=" * 60)
        t0 = time.perf_counter()

        try:
            # 念のため戦略を再確認 (UI のヘッダーに反映)
            self.sys_cfg.resolve_strategy()

            builder = self.ui_mod.AiboUIBuilder(self.sys_cfg, self.orchestrator)
            self.ui_app = builder.build()

            self._phase_times["g_ui"] = time.perf_counter() - t0
            self.logger.info(f"✅ Phase G ビルド完了 ({self._phase_times['g_ui']:.1f}s)")

            self._log_summary()

            self.logger.info("=" * 60)
            self.logger.info("🎉 AIBO CYBER STUDIO v7.2 · 全 Phase 完了")
            self.logger.info(f"   share={share}, port={server_port}")
            self.logger.info("=" * 60)

            # launch (ブロッキング)
            self.ui_app.launch(
                share=share,
                server_port=server_port,
                inbrowser=inbrowser,
                debug=debug,
                show_error=True,
            )
            return True

        except Exception as e:
            self.logger.error(f"❌ Phase G 失敗: {e}")
            self.logger.error(traceback.format_exc())
            return False

    # ────────────────────────────────────────
    # 全 Phase を順次実行
    # ────────────────────────────────────────

    def run(
        self,
        *,
        share: bool = True,
        server_port: int = 7860,
        inbrowser: bool = False,
        enable_gradio: bool = True,
    ) -> bool:
        """
        全 Phase を順番に実行。
        どこかで失敗したら以降を中止。
        """
        self.logger.info("\n" + "🌌" * 30)
        self.logger.info("🌌 AIBO CYBER STUDIO v7.2 · 起動シーケンス開始")
        self.logger.info("🌌" * 30 + "\n")

        t0_total = time.perf_counter()

        # ─── Phase 0 · module-manifest preflight(恒久対策 B2・検証のみ・生成非改変)───
        #   committed manifest と runtime モジュールの md5 を照合。silent な desync
        #   (例 04新/05旧)を build 前に大声で検出して STOP する。GATE① の真因の再発防止。
        #   ツール不在/import 不可なら warn して続行(ガード未導入環境は壊さない)。
        self._verify_module_manifest_preflight()

        if not self.phase_a_bootstrap():
            return False
        if not self.phase_b_resolve_strategy():
            return False
        if not self.phase_c_build_pipeline():
            return False
        if not self.phase_d_identity():
            self.logger.warning("⚠️ Phase D 部分失敗 · UI は起動するが Identity 機能制限")
        if not self.phase_e_assets():
            return False
        if not self.phase_f_orchestrator():
            return False

        total = time.perf_counter() - t0_total
        self.logger.info("=" * 60)
        self.logger.info(f"🎉 起動準備完了 (合計 {total:.1f}s)")
        self.logger.info("=" * 60)

        # Phase G: Gradio launch (A方式運用ではスキップ可能)
        if enable_gradio:
            return self.phase_g_launch_ui(
                share=share,
                server_port=server_port,
                inbrowser=inbrowser,
            )
        else:
            try:
                self.logger.info("⏭️ Phase G (Gradio) スキップ · A方式運用")
            except Exception:
                print("⏭️ Phase G (Gradio) スキップ · A方式運用")
            return True

    # ────────────────────────────────────────
    # Phase 0 · module-manifest preflight(恒久対策 B2)
    # ────────────────────────────────────────

    def _verify_module_manifest_preflight(self) -> None:
        """tools/check_manifest.verify_module_manifest() を呼び、committed manifest と
        runtime モジュールの md5 desync を build 前に検出する。検証のみ(生成非改変)。
        desync(strict)時は SystemExit で即死。ツール不在/import 不可は warn して続行。"""
        import os
        try:
            try:
                checker = import_module("tools.check_manifest")
            except Exception:
                # namespace package が解決できない環境向けの file ロードフォールバック
                import importlib.util
                here = os.path.dirname(os.path.abspath(__file__))
                p = os.path.join(here, "tools", "check_manifest.py")
                if not os.path.exists(p):
                    self.logger.warning(f"⚠️ [manifest] checker 不在({p})→ preflight skip")
                    return
                spec = importlib.util.spec_from_file_location("aibo_check_manifest", p)
                checker = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(checker)
            checker.verify_module_manifest(strict=True)
        except SystemExit:
            # desync 検出 = 意図した即死。build を止める。
            raise
        except Exception as e:
            self.logger.warning(f"⚠️ [manifest] preflight 実行不可(続行): {e}")

    # ────────────────────────────────────────
    # サマリーログ
    # ────────────────────────────────────────

    def _log_summary(self):
        self.logger.info("─" * 60)
        self.logger.info("📊 各 Phase の所要時間:")
        for name, sec in self._phase_times.items():
            self.logger.info(f"   {name:25s}: {sec:7.1f}s")
        self.logger.info("─" * 60)

    # ────────────────────────────────────────
    # 終了処理
    # ────────────────────────────────────────

    def shutdown(self):
        """終了時のクリーンアップ"""
        self.logger.info("🛑 シャットダウン処理")
        if self.bootstrap is not None:
            self.bootstrap.shutdown()


# ============================================================================
# 🚀 Section 7.2 · 公開関数
# ============================================================================

# シングルトン (再起動防止)
_AIBO_MAIN_INSTANCE: Optional[AiboMain] = None


def run(
    *,
    share: bool = True,
    server_port: int = 7860,
    inbrowser: bool = False,
) -> bool:
    """
    AIBO CYBER STUDIO v7.2 を起動。

    Colab セル使用例:
        from importlib import import_module
        main = import_module("07_main")
        main.run()
    """
    global _AIBO_MAIN_INSTANCE

    if _AIBO_MAIN_INSTANCE is None:
        _AIBO_MAIN_INSTANCE = AiboMain()

    return _AIBO_MAIN_INSTANCE.run(
        share=share,
        server_port=server_port,
        inbrowser=inbrowser,
    )


def get_instance() -> Optional[AiboMain]:
    """既存のインスタンスを取得 (デバッグ用)"""
    return _AIBO_MAIN_INSTANCE


def shutdown():
    """シャットダウン"""
    global _AIBO_MAIN_INSTANCE
    if _AIBO_MAIN_INSTANCE is not None:
        _AIBO_MAIN_INSTANCE.shutdown()
        _AIBO_MAIN_INSTANCE = None


# ============================================================================
# 🌐 Section 7.2 · FastAPI バックグラウンド起動 (Cursor #3a · Gradio と並行)
# ============================================================================

def launch_fastapi_in_background(
    orchestrator_instance,
    pipeline_manager_instance=None,
    port: int = 8000,
) -> Any:
    """
    FastAPI (09_fastapi_server.py) を別スレッドで起動する。

    Colab 例:
        import importlib
        main = import_module("07_main")
        main.launch_fastapi_in_background(m.orchestrator, m.pipeline_mgr, port=8000)
    """
    import threading

    srv_mod = import_module("09_fastapi_server")
    srv_mod.attach_orchestrator(orchestrator_instance, pipeline_manager_instance)

    def _run() -> None:
        srv_mod.run_server(host="0.0.0.0", port=port)

    thread = threading.Thread(target=_run, daemon=True, name="aibo-fastapi")
    thread.start()
    print(f"✅ AIBO FastAPI server launched in background on port {port}")
    return thread


# ============================================================================
# 🔧 Section 7.3 · スタンドアロン動作確認
# ============================================================================

if __name__ == "__main__":
    sys.dont_write_bytecode = True

    print("=" * 60)
    print("🌌 AIBO v7.2 · Section 7 (Main) 動作確認")
    print("=" * 60)

    print()
    print("🧪 モジュール import 確認:")
    try:
        modules = _import_modules()
        for k, v in modules.items():
            print(f"  ✅ {k}: {v.__name__}")
    except Exception as e:
        print(f"  ❌ {e}")

    print()
    print("🧪 AiboMain 初期化 (重い処理は呼ばない):")
    try:
        m = AiboMain()
        print("  ✅ AiboMain 初期化 OK")
        print(f"  attributes: sys_cfg={m.sys_cfg}, pipeline_mgr={m.pipeline_mgr}")
    except Exception as e:
        print(f"  ❌ {e}")
        traceback.print_exc()

    print()
    print("⚠️ 全 Phase 実行は重い処理 (Pipeline build に 5-10 分):")
    print("   from importlib import import_module")
    print("   main = import_module('07_main')")
    print("   main.run()")
    print()
    print("   段階実行 (デバッグ用):")
    print("   from importlib import import_module")
    print("   mod = import_module('07_main')")
    print("   m = mod.AiboMain()")
    print("   m.phase_a_bootstrap()")
    print("   m.phase_c_build_pipeline()")
    print("   m.phase_g_launch_ui()")

    print()
    print("✅ Section 7 動作確認完了")
