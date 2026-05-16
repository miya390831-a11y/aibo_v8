"""
================================================================================
🌌 AIBO CYBER STUDIO v7.2 · Section 6 · Gradio UI (3-Mode × 3-Column)
================================================================================

📌 ファイル名: 06_ui.py

📌 このファイルの責務:
    1. AiboUIBuilder: gr.Blocks 構築の司令塔
    2. _build_three_column_layout: 3 カラム (Left 340px / Center flex / Right 360px)
    3. _build_left_panel:  Face Reference + Detail Accordion + Prompt
    4. _build_center_panel: Pictogram (3軸スライダー) + Body Adjustment 6スライダー
    5. _build_right_panel: Preview + Seed + Generate ボタン
    6. UICallbacks: Generate ボタン押下時の orchestrator.generate 呼び出し
    7. AIBO_CSS: cyber-cyan/magenta + Geist フォントのフルテーマ

依存:
    - 01_config.py
    - 03_identity.py
    - 04_pipeline_manager.py
    - 05_orchestrator.py
    - gradio (>=5.0)
    - PIL

設計思想:
    - 3 モード (Portrait/Coordinate/Situation) は同じレイアウトを共有
    - Tab で切替 · モードごとに State を別々に保持
    - cyber-cyan (#9bd5ff) + cyber-magenta (#dd92db) のグラデーションで識別性向上

Author: 🥷 CTO くろうど
Date:   2026-05-03
Version: v7.2
================================================================================
"""

from __future__ import annotations

import sys
import time
from importlib import import_module
from typing import Any

# ─── 01_config から型を import ───
_cfg_mod = import_module("01_config")
SystemConfig     = _cfg_mod.SystemConfig
GenerationConfig = _cfg_mod.GenerationConfig
IdentityConfig   = _cfg_mod.IdentityConfig
ModeConfig       = _cfg_mod.ModeConfig
StudioMode       = _cfg_mod.StudioMode
logger           = _cfg_mod.logger

# ─── 後段モジュール (実行時に解決) ───
# CharacterOrchestrator は重い依存なので main 側から渡す


# ============================================================================
# 🎨 Section 6.1 · AIBO CSS (UI.txt のデザイン言語移植)
# ============================================================================

AIBO_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Geist:wght@400;500;600;700&family=Geist+Mono:wght@400;500;600&display=swap');

:root {
  --cyber-bg:        oklch(0.14 0.02 260);
  --cyber-card:      oklch(0.18 0.025 260);
  --cyber-popover:   oklch(0.16 0.025 260);
  --cyber-border:    oklch(0.28 0.04 260);
  --cyber-input:     oklch(0.22 0.03 260);
  --cyber-muted:     oklch(0.22 0.02 260);
  --cyber-muted-fg:  oklch(0.7 0.03 240);
  --cyber-fg:        oklch(0.96 0.01 200);
  --cyber-cyan:      oklch(0.85 0.18 200);
  --cyber-magenta:   oklch(0.7 0.27 340);
  --grid-line:       oklch(0.3 0.04 260 / 0.35);
}

/* ─── 全体トーン ─── */
body, .gradio-container {
  background: var(--cyber-bg) !important;
  color: var(--cyber-fg) !important;
  font-family: 'Geist', sans-serif !important;
}

.gradio-container {
  max-width: 100% !important;
  padding: 0 !important;
}

/* ─── ヘッダー ─── */
.aibo-header {
  background: linear-gradient(180deg, var(--cyber-card), transparent);
  padding: 12px 24px !important;
  border-bottom: 1px solid var(--cyber-border);
}

.gradient-text {
  background: linear-gradient(90deg, var(--cyber-cyan), var(--cyber-magenta));
  -webkit-background-clip: text;
  background-clip: text;
  -webkit-text-fill-color: transparent;
  font-weight: 700;
  letter-spacing: 0.3em;
}

.gradient-bg {
  background: linear-gradient(135deg, var(--cyber-cyan), var(--cyber-magenta)) !important;
}

.glow-cyan {
  box-shadow: 0 0 14px color-mix(in oklch, var(--cyber-cyan) 45%, transparent);
}
.glow-magenta {
  box-shadow: 0 0 14px color-mix(in oklch, var(--cyber-magenta) 45%, transparent);
}
.glow-gradient {
  box-shadow:
    0 0 18px color-mix(in oklch, var(--cyber-cyan) 35%, transparent),
    0 0 32px color-mix(in oklch, var(--cyber-magenta) 25%, transparent) !important;
}

/* ─── スキャンライン演出 ─── */
.scanline {
  background-image: repeating-linear-gradient(
    0deg, transparent, transparent 3px,
    color-mix(in oklch, var(--cyber-cyan) 8%, transparent) 3px,
    color-mix(in oklch, var(--cyber-cyan) 8%, transparent) 4px
  );
}

/* ─── グリッド背景 ─── */
.grid-bg {
  background-image:
    linear-gradient(var(--grid-line) 1px, transparent 1px),
    linear-gradient(90deg, var(--grid-line) 1px, transparent 1px);
  background-size: 24px 24px;
}

/* ─── セクションヘッダー ─── */
.section-header {
  font-size: 11px !important;
  font-family: 'Geist Mono', monospace !important;
  letter-spacing: 0.2em !important;
  text-transform: uppercase !important;
  color: var(--cyber-muted-fg) !important;
  margin: 12px 0 6px !important;
  padding-bottom: 4px;
  border-bottom: 1px solid var(--cyber-border);
}

/* ─── Generate ボタン ─── */
.generate-btn {
  height: 56px !important;
  background: linear-gradient(135deg, var(--cyber-cyan), var(--cyber-magenta)) !important;
  color: var(--cyber-bg) !important;
  font-weight: 700 !important;
  letter-spacing: 0.3em !important;
  text-transform: uppercase !important;
  font-size: 14px !important;
  border: none !important;
}

.generate-btn:hover {
  filter: brightness(1.1) !important;
  box-shadow:
    0 0 24px color-mix(in oklch, var(--cyber-cyan) 50%, transparent),
    0 0 44px color-mix(in oklch, var(--cyber-magenta) 35%, transparent) !important;
}

/* ─── Body Link ボタン ─── */
.body-link-btn {
  background: transparent !important;
  border: 1px solid var(--cyber-cyan) !important;
  color: var(--cyber-cyan) !important;
  font-family: 'Geist Mono', monospace !important;
  letter-spacing: 0.15em !important;
  font-size: 11px !important;
  text-transform: uppercase !important;
}

.body-link-btn:hover {
  background: color-mix(in oklch, var(--cyber-cyan) 15%, transparent) !important;
}

/* ─── モノスペース要素 ─── */
.font-mono, .font-mono input, .font-mono textarea {
  font-family: 'Geist Mono', monospace !important;
}

/* ─── テキストボックス系 ─── */
input, textarea, .gr-input, .gr-textbox textarea {
  background: var(--cyber-input) !important;
  color: var(--cyber-fg) !important;
  border: 1px solid var(--cyber-border) !important;
  border-radius: 8px !important;
}

input:focus, textarea:focus {
  border-color: var(--cyber-cyan) !important;
  outline: none !important;
}

/* ─── タブ ─── */
.aibo-mode-tabs button[role="tab"] {
  background: var(--cyber-card) !important;
  color: var(--cyber-muted-fg) !important;
  border: 1px solid var(--cyber-border) !important;
  font-family: 'Geist Mono', monospace !important;
  letter-spacing: 0.15em !important;
  text-transform: uppercase !important;
  font-size: 12px !important;
}

.aibo-mode-tabs button[role="tab"][aria-selected="true"] {
  background: linear-gradient(135deg, var(--cyber-cyan), var(--cyber-magenta)) !important;
  color: var(--cyber-bg) !important;
  border: none !important;
}

/* ─── アコーディオン ─── */
.gr-accordion {
  background: var(--cyber-card) !important;
  border: 1px solid var(--cyber-border) !important;
  border-radius: 8px !important;
}

/* ─── プレビュー枠 ─── */
.preview-frame {
  border: 1px solid var(--cyber-border) !important;
  border-radius: 12px !important;
  overflow: hidden;
  background: var(--cyber-card);
}

/* ─── フッター ─── */
.aibo-footer {
  background: var(--cyber-card);
  border-top: 1px solid var(--cyber-border);
  padding: 6px 16px !important;
  font-family: 'Geist Mono', monospace !important;
  font-size: 10px !important;
  color: var(--cyber-muted-fg) !important;
  letter-spacing: 0.1em;
}

.status-cyan { color: var(--cyber-cyan) !important; }
.status-magenta { color: var(--cyber-magenta) !important; }

/* ─── スライダー ─── */
.gr-slider input[type="range"] {
  accent-color: var(--cyber-cyan) !important;
}

/* ─── ボタン全般 ─── */
button {
  border-radius: 8px !important;
  font-family: 'Geist', sans-serif !important;
}
"""


# ============================================================================
# 🎨 Section 6.2 · UICallbacks (Generate ボタン処理)
# ============================================================================

class UICallbacks:
    """
    Gradio UI のイベントハンドラ群。
    orchestrator を呼んで画像生成 + 進捗管理 + エラー通知を担当。
    """

    def __init__(
        self,
        sys_cfg: SystemConfig,
        orchestrator,  # CharacterOrchestrator (型は実行時)
    ):
        self.sys_cfg = sys_cfg
        self.orch = orchestrator

    # ─────────────────────────────────────────────────
    # Generate コールバック (各モード共通)
    # ─────────────────────────────────────────────────

    def on_generate(
        self,
        # ─── モード ───
        mode_str: str,
        # ─── 顔参照 ───
        face_slot1: Any,
        face_slot2: Any,
        face_slot3: Any,
        face_strength: float,
        # ─── Prompt ───
        prompt: str,
        negative: str,
        # ─── Sampler ───
        steps: int,
        cfg_scale: float,
        # ─── Seed ───
        random_seed: bool,
        seed_val: int,
        # ─── Pictogram (3軸) ───
        yaw: float,
        pitch: float,
        roll: float,
        # ─── Body Adjustment (6 スライダー) ───
        body_height: float,
        body_weight: float,
        body_chest: float,
        body_waist: float,
        body_hip: float,
        body_shoulder: float,
        # ─── ControlNet weight ───
        controlnet_weight: float,
        # ─── IP-Adapter weight ───
        ip_adapter_weight: float,
        # ─── Pass 2 ───
        enable_pass2: bool,
        # ─── Upscale ───
        enable_upscale: bool,
        upscale_method: str,
        upscale_factor: int,
        # ─── 進捗 (gradio 5.x · 引数受け取りで明示) ───
        progress=None,
    ):
        """
        Generate ボタン押下時の処理。

        Returns:
            (final_image, status_text, metadata_text)
        """
        import gradio as gr
        if progress is None:
            try:
                progress = gr.Progress(track_tqdm=False)
            except Exception:
                progress = None

        try:
            # ─── 進捗 1/5: 入力組み立て ───
            if progress is not None:
                progress(0.05, desc="入力を準備中...")

            mode_enum = StudioMode(mode_str)

            # 顔参照 (最初に存在するスロットを採用 · 将来は extract_multi)
            ref_image = None
            for slot in (face_slot1, face_slot2, face_slot3):
                if slot is not None:
                    ref_image = slot
                    break

            # GenerationConfig
            gen_cfg = GenerationConfig(
                prompt=prompt,
                negative_prompt=negative,
                num_inference_steps=int(steps) if steps > 0 else -1,
                guidance_scale=float(cfg_scale),
                seed=-1 if random_seed else int(seed_val),
                enable_pass2=bool(enable_pass2),
                enable_upscale=bool(enable_upscale),
                upscale_method=str(upscale_method),
                upscale_factor=int(upscale_factor),
            )

            # IdentityConfig
            id_cfg = IdentityConfig(
                reference_image=ref_image,
                pulid_weight=2.5,  # v7.2.6 真黄金値 (2026-05-05 PO 実測)
                ip_adapter_weight=float(ip_adapter_weight) / 100.0,  # スライダーは 0-100
                controlnet_weight=float(controlnet_weight) / 100.0,
            )

            # ─── 進捗 2/5: 顔抽出 ───
            if progress is not None:
                progress(0.15, desc="顔特徴を抽出中...")

            # ─── 進捗 3/5: 生成中 ───
            if progress is not None:
                progress(0.30, desc=f"生成中 ({mode_enum.value})...")

            # 実生成
            t0 = time.perf_counter()
            result = self.orch.generate(
                gen_cfg=gen_cfg,
                id_cfg=id_cfg,
                mode=mode_enum,
                save=True,
            )
            elapsed = time.perf_counter() - t0

            # ─── 進捗 5/5: 完了 ───
            if progress is not None:
                progress(1.0, desc="完了!")

            # ─── ステータス文字列 ───
            if result.error:
                status = f"❌ エラー: {result.error}"
                meta = "(なし)"
                return None, status, meta

            status = (
                f"✅ 生成完了 · seed={result.seed} · {elapsed:.1f}s"
                + (f" · saved: {result.saved_path.name}" if result.saved_path else "")
            )
            meta_dict = result.to_metadata_dict()
            meta = "\n".join(f"{k}: {v}" for k, v in meta_dict.items())

            return result.final_image, status, meta

        except Exception as e:
            import traceback
            traceback.print_exc()
            return None, f"❌ 例外: {e}", "(エラー)"

    # ─────────────────────────────────────────────────
    # Roll Seed
    # ─────────────────────────────────────────────────

    def on_roll_seed(self):
        import random
        return random.randint(0, 2**31 - 1)


# ============================================================================
# 🏗 Section 6.3 · UI ビルダー (3 モード × 3 カラム)
# ============================================================================

class AiboUIBuilder:
    """
    Gradio UI を組み立てるメインクラス。

    使い方:
        builder = AiboUIBuilder(sys_cfg, orchestrator)
        app = builder.build()
        app.launch(share=True, server_port=7860, inbrowser=True)
    """

    def __init__(
        self,
        sys_cfg: SystemConfig,
        orchestrator,  # CharacterOrchestrator
    ):
        self.sys_cfg = sys_cfg
        self.orch = orchestrator
        self.callbacks = UICallbacks(sys_cfg, orchestrator)

    # ─────────────────────────────────────────────────
    # メイン: build()
    # ─────────────────────────────────────────────────

    def build(self):
        import gradio as gr

        with gr.Blocks(
            css=AIBO_CSS,
            theme=gr.themes.Base(
                primary_hue=gr.themes.colors.cyan,
                secondary_hue=gr.themes.colors.fuchsia,
                neutral_hue=gr.themes.colors.slate,
                font=("Geist", "sans-serif"),
                font_mono=("Geist Mono", "monospace"),
            ),
            title="AIBO CYBER STUDIO v7.2",
        ) as app:

            # ─── ヘッダー ───
            self._build_header(gr)

            # ─── モードタブ (3 モード) ───
            with gr.Tabs(elem_classes="aibo-mode-tabs"):
                for mode in StudioMode:
                    mode_cfg = ModeConfig.get(mode)
                    with gr.Tab(f"{mode_cfg.icon} {mode_cfg.label}", id=mode.value):
                        self._build_mode_tab(gr, mode)

            # ─── フッター ───
            self._build_footer(gr)

        return app

    # ─────────────────────────────────────────────────
    # ヘッダー
    # ─────────────────────────────────────────────────

    def _build_header(self, gr):
        gpu_label = self.sys_cfg.strategy.gpu_name if self.sys_cfg.strategy else "(unknown)"
        vram_label = (
            f"{self.sys_cfg.strategy.vram_gb:.0f}GB"
            if self.sys_cfg.strategy else "?GB"
        )

        gr.HTML(f"""
        <div class="aibo-header" style="display:flex; align-items:center; justify-content:space-between;">
          <div style="display:flex; align-items:center; gap:14px;">
            <div class="gradient-bg glow-gradient" style="width:36px; height:36px; border-radius:8px;"></div>
            <div>
              <div class="gradient-text" style="font-size:14px;">AIBO CYBER STUDIO</div>
              <div class="font-mono" style="font-size:9px; color:var(--cyber-muted-fg); letter-spacing:0.2em; text-transform:uppercase;">
                v7.2 · 3-MODE · POSE RIGGING · LoRA AUTO-ROUTE
              </div>
            </div>
          </div>
          <div class="font-mono" style="font-size:11px; color:var(--cyber-muted-fg);">
            <span class="status-cyan">{gpu_label}</span> · <span class="status-magenta">{vram_label}</span>
          </div>
        </div>
        """)

    # ─────────────────────────────────────────────────
    # モードタブの中身 (3 カラム)
    # ─────────────────────────────────────────────────

    def _build_mode_tab(self, gr, mode: StudioMode):
        """1 モード分の 3 カラムレイアウトを構築"""
        mode_cfg = ModeConfig.get(mode)

        with gr.Row(equal_height=False):
            # ─── LEFT PANEL ───
            with gr.Column(scale=2, min_width=340):
                left = self._build_left_panel(gr, mode_cfg)

            # ─── CENTER PANEL ───
            with gr.Column(scale=5):
                center = self._build_center_panel(gr, mode_cfg)

            # ─── RIGHT PANEL ───
            with gr.Column(scale=2, min_width=360):
                right = self._build_right_panel(gr, mode_cfg)

        # ─── Generate ボタンのバインド ───
        # gr.State は事前に Component として宣言する必要あり (gradio 5.x)
        mode_state = gr.State(value=mode.value)

        right["generate_btn"].click(
            fn=self.callbacks.on_generate,
            inputs=[
                mode_state,                            # mode_str (gr.State)
                left["face_slot1"], left["face_slot2"], left["face_slot3"],
                left["face_strength"],
                left["prompt"], left["negative"],
                left["steps"], left["cfg_scale"],
                right["random_seed"], right["seed_val"],
                center["yaw"], center["pitch"], center["roll"],
                center["body_height"], center["body_weight"],
                center["body_chest"], center["body_waist"],
                center["body_hip"], center["body_shoulder"],
                left["controlnet_weight"],
                left["ip_adapter_weight"],
                left["enable_pass2"],
                right["enable_upscale"],
                right["upscale_method"],
                right["upscale_factor"],
            ],
            outputs=[
                right["preview"],
                right["status"],
                right["metadata"],
            ],
        )

        # ─── Roll Seed ───
        right["roll_btn"].click(
            fn=self.callbacks.on_roll_seed,
            outputs=[right["seed_val"]],
        )

    # ─────────────────────────────────────────────────
    # LEFT PANEL · 設定 (340px)
    # ─────────────────────────────────────────────────

    def _build_left_panel(self, gr, mode_cfg: ModeConfig) -> dict:
        out: dict = {}

        # ─── 01 · Face Reference ───
        gr.HTML('<div class="section-header">01 · Face Reference</div>')

        with gr.Row():
            out["face_slot1"] = gr.Image(label="Slot 1", type="pil", height=80, sources=["upload", "clipboard"])
            out["face_slot2"] = gr.Image(label="Slot 2", type="pil", height=80, sources=["upload", "clipboard"])
            out["face_slot3"] = gr.Image(label="Slot 3", type="pil", height=80, sources=["upload", "clipboard"])

        out["face_strength"] = gr.Slider(0, 100, value=78, step=1, label="Face LoRA strength")

        # ─── 02 · Detail Settings ───
        gr.HTML('<div class="section-header">02 · Detail Settings</div>')

        with gr.Accordion("✨ Face Detail", open=False):
            out["skin_smooth"] = gr.Slider(0, 100, value=62, step=1, label="Skin smoothness")
            out["eye_emphasis"] = gr.Slider(0, 100, value=40, step=1, label="Eye emphasis")
            out["makeup"] = gr.Slider(0, 100, value=30, step=1, label="Makeup intensity")

        with gr.Accordion("🎨 Lighting & Color", open=True):
            out["key_light"] = gr.Slider(0, 100, value=70, step=1, label="Key light")
            out["fill_light"] = gr.Slider(0, 100, value=35, step=1, label="Fill / ambient")
            out["rim_light"] = gr.Slider(0, 100, value=55, step=1, label="Rim light")
            out["hdr_output"] = gr.Checkbox(value=True, label="HDR output")

        with gr.Accordion("🪄 Identity Strength", open=False):
            out["ip_adapter_weight"] = gr.Slider(0, 100, value=70, step=1, label="IP-Adapter weight")
            out["controlnet_weight"] = gr.Slider(0, 100, value=50, step=1, label="ControlNet weight")

        with gr.Accordion("🎚 Sampler", open=False):
            out["steps"] = gr.Slider(
                -1, 60, value=-1, step=1,
                label="Steps (-1 = auto · Hyper-FLUX 8 / FLUX-dev 28)",
            )
            out["cfg_scale"] = gr.Slider(1.0, 10.0, value=3.5, step=0.1, label="CFG Scale")
            out["enable_pass2"] = gr.Checkbox(value=True, label="Pass 2 (顔リファイン)")

        # ─── 03 · Prompt ───
        gr.HTML('<div class="section-header">03 · Prompt</div>')

        out["prompt"] = gr.Textbox(
            value=mode_cfg.default_prompt,
            lines=4,
            placeholder=f"describe {mode_cfg.sub_label}...",
            label="Prompt",
        )
        out["negative"] = gr.Textbox(
            value=mode_cfg.default_negative,
            lines=3,
            label="Negative Prompt",
        )

        return out

    # ─────────────────────────────────────────────────
    # CENTER PANEL · Pictogram + Body Adjustment
    # ─────────────────────────────────────────────────

    def _build_center_panel(self, gr, mode_cfg: ModeConfig) -> dict:
        out: dict = {}

        gr.HTML(f'<div class="section-header">Physics Canvas · {mode_cfg.label.upper()}</div>')

        # ─── Pictogram (3 軸スライダー版) ───
        gr.HTML(f"""
        <div class="grid-bg" style="
          height: 320px;
          border: 1px solid var(--cyber-border);
          border-radius: 12px;
          display: flex;
          align-items: center;
          justify-content: center;
          color: var(--cyber-muted-fg);
          font-family: 'Geist Mono', monospace;
          font-size: 11px;
          letter-spacing: 0.2em;
          text-transform: uppercase;
        ">
          🎯 Pictogram Preview · {mode_cfg.icon} {mode_cfg.label}
          <br><span style="font-size:9px; opacity:0.6;">(yaw / pitch / roll で姿勢調整)</span>
        </div>
        """)

        with gr.Row():
            out["yaw"] = gr.Slider(-180, 180, value=0, step=1, label="Yaw (左右回転)")
            out["pitch"] = gr.Slider(-90, 90, value=0, step=1, label="Pitch (上下)")
            out["roll"] = gr.Slider(-180, 180, value=0, step=1, label="Roll (傾き)")

        # ─── Body Adjustment 6 スライダー ───
        gr.HTML('<div class="section-header" style="margin-top:24px;">Body Adjustment · 6-Axis</div>')

        with gr.Row():
            with gr.Column():
                gr.HTML('<div style="font-size:10px; color:var(--cyber-cyan); font-family:Geist Mono; letter-spacing:0.15em; text-transform:uppercase;">BASE</div>')
                out["body_height"] = gr.Slider(0, 100, value=50, step=1, label="Height")
                out["body_weight"] = gr.Slider(0, 100, value=50, step=1, label="Weight")
            with gr.Column():
                gr.HTML('<div style="font-size:10px; color:var(--cyber-magenta); font-family:Geist Mono; letter-spacing:0.15em; text-transform:uppercase;">PROPORTION</div>')
                out["body_chest"] = gr.Slider(0, 100, value=50, step=1, label="Chest")
                out["body_waist"] = gr.Slider(0, 100, value=50, step=1, label="Waist")
            with gr.Column():
                gr.HTML('<div style="font-size:10px; color:var(--cyber-cyan); font-family:Geist Mono; letter-spacing:0.15em; text-transform:uppercase;">SILHOUETTE</div>')
                out["body_hip"] = gr.Slider(0, 100, value=50, step=1, label="Hip")
                out["body_shoulder"] = gr.Slider(0, 100, value=50, step=1, label="Shoulder")

        return out

    # ─────────────────────────────────────────────────
    # RIGHT PANEL · Preview + Seed + Generate
    # ─────────────────────────────────────────────────

    def _build_right_panel(self, gr, mode_cfg: ModeConfig) -> dict:
        out: dict = {}

        # ─── Preview ───
        gr.HTML(f'<div class="section-header">Preview · {mode_cfg.label.upper()}</div>')

        out["preview"] = gr.Image(
            label=None,
            type="pil",
            height=400,
            interactive=False,
            elem_classes="preview-frame",
            show_label=False,
        )

        # ─── Status ───
        out["status"] = gr.Textbox(
            label="Status",
            interactive=False,
            value="🟢 READY",
            elem_classes="font-mono",
        )

        # ─── Seed Settings ───
        with gr.Accordion("🎲 Seed Settings", open=True):
            out["random_seed"] = gr.Checkbox(value=True, label="Random seed (生成のたびに新しい seed)")
            with gr.Row():
                out["seed_val"] = gr.Number(value=4815162342, precision=0, label="Seed")
                out["roll_btn"] = gr.Button("🎲 Roll", size="sm")

        # ─── Upscale ───
        with gr.Accordion("🚀 Upscale", open=False):
            out["enable_upscale"] = gr.Checkbox(value=False, label="Enable upscale")
            out["upscale_method"] = gr.Dropdown(
                choices=["real-esrgan", "real-esrgan-anime", "esrgan", "supir"],
                value="real-esrgan",
                label="Method",
            )
            out["upscale_factor"] = gr.Slider(2, 4, value=2, step=2, label="Scale (2x / 4x)")

        # ─── Body Link ───
        out["body_link_btn"] = gr.Button(
            "🔗 LINK BODY → COORDINATE",
            elem_classes="body-link-btn",
        )

        # ─── Generate Button ───
        gr.HTML('<div style="margin-top: 12px;"></div>')
        out["generate_btn"] = gr.Button(
            "✨ GENERATE",
            elem_classes="generate-btn glow-gradient",
            variant="primary",
        )

        # ─── Metadata (折りたたみ) ───
        with gr.Accordion("📊 Metadata", open=False):
            out["metadata"] = gr.Textbox(
                label=None,
                lines=10,
                interactive=False,
                value="(no generation yet)",
                elem_classes="font-mono",
                show_label=False,
            )

        return out

    # ─────────────────────────────────────────────────
    # フッター
    # ─────────────────────────────────────────────────

    def _build_footer(self, gr):
        strategy_label = self.sys_cfg.strategy.kind.value if self.sys_cfg.strategy else "?"
        pulid_label = self.sys_cfg.strategy.pulid_injection_method() if self.sys_cfg.strategy else "?"

        gr.HTML(f"""
        <div class="aibo-footer" style="display:flex; justify-content:space-between;">
          <div>
            <span>STRATEGY: <span class="status-cyan">{strategy_label}</span></span>
            <span style="margin-left:16px;">PULID: <span class="status-magenta">{pulid_label}</span></span>
            <span style="margin-left:16px;">CONTROLNET: Union Pro 2.0</span>
          </div>
          <div>
            <span>STATUS: <span class="status-cyan">READY</span></span>
          </div>
        </div>
        """)


# ============================================================================
# 🚀 Section 6.4 · launch ヘルパ
# ============================================================================

def launch_ui(
    sys_cfg: SystemConfig,
    orchestrator,
    *,
    share: bool = True,
    server_port: int = 7860,
    inbrowser: bool = True,
    debug: bool = False,
):
    """UI を起動するヘルパ"""
    builder = AiboUIBuilder(sys_cfg, orchestrator)
    app = builder.build()
    logger.info("=" * 60)
    logger.info("🚀 AIBO CYBER STUDIO v7.2 UI 起動")
    logger.info(f"   share={share}, port={server_port}")
    logger.info("=" * 60)
    app.launch(
        share=share,
        server_port=server_port,
        inbrowser=inbrowser,
        debug=debug,
    )


# ============================================================================
# 🔧 Section 6.5 · スタンドアロン動作確認
# ============================================================================

if __name__ == "__main__":
    sys.dont_write_bytecode = True

    print("=" * 60)
    print("🌌 AIBO v7.2 · Section 6 (Gradio UI) 動作確認")
    print("=" * 60)

    sys_cfg = SystemConfig()
    sys_cfg.resolve_strategy()

    print()
    print(f"🔍 戦略: {sys_cfg.strategy.kind.value}")

    # ─── クラス定義確認 ───
    print()
    print("🧪 クラス定義確認:")
    print(f"  AIBO_CSS: {len(AIBO_CSS)} bytes")
    print(f"  UICallbacks:    {UICallbacks.__name__}")
    print(f"  AiboUIBuilder:  {AiboUIBuilder.__name__}")

    # ─── Gradio import 確認 ───
    print()
    print("🧪 Gradio バージョン確認:")
    try:
        import gradio as gr
        print(f"  ✅ gradio {gr.__version__}")
    except ImportError as e:
        print(f"  ❌ gradio 未インストール: {e}")

    # ─── 軽量ダミー Builder 起動テスト (実 build はしない) ───
    print()
    print("🧪 AiboUIBuilder 初期化:")
    print("  実 build() は orchestrator が必要なので skip")
    print("  実起動は Section 7 (main) で:")
    print("    from importlib import import_module")
    print("    main = import_module('07_main')")
    print("    main.run()")

    print()
    print("✅ Section 6 動作確認完了")
