"""
================================================================================
🌌 AIBO CYBER STUDIO v7.2 · Section 1 · Config & Runtime Strategy
================================================================================

📌 このファイルの責務:
    1. 全システム共通のデータクラス定義 (GenerationConfig, IdentityConfig,
       LoRAEntry, SystemConfig, ModeConfig)
    2. 環境検出ロジック (RuntimeStrategy)
       - A100 80GB → bf16 純正
       - A100 40GB → Nunchaku INT4 / または GGUF フォールバック
       - T4 16GB   → GGUF Q5_K_M + CPU offload
    3. 3 モード (Portrait/Coordinate/Situation) のデフォルト設定
    4. PuLID/Hyper-FLUX/ControlNet など各種定数

依存:
    - torch (環境検出用)
    - 他の Section ファイルに依存しない (このファイルが起点)

使い方:
    from importlib import import_module
    cfg_mod = import_module("01_config")
    strategy = cfg_mod.RuntimeStrategy.detect()
    print(strategy.summary())

Author: 🥷 CTO くろうど
Date:   2026-05-03
Version: v7.2

履歴:
    2026-05-08: Cursor #2 v3 hotfix — PHASE3B_ENABLED をデフォルト False に変更
                (検証 + 専門家分析により v8.0 で Phase 3b は既定 OFF を確定。
                復活は PHASE3B_ENABLED=True で明示)
================================================================================
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import torch
from PIL import Image

# ─── ロギング設定 (グローバル) ───
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
logger = logging.getLogger("AIBO_v7")

# ─── Phase 3 ハイブリッド γ パラメータ ───
PHASE3_ENABLED: bool = True

# ─── Phase 3 細粒度制御 (Cursor #2 v2 · v3 hotfix で 3b デフォルト変更) ───
PHASE3A_ENABLED: bool = True  # GFPGAN による低周波構造補正

# ★ Phase 3b は v8.0 デフォルト OFF (2026-05-08 検証 + 専門家分析で確定)
#
# 理由:
#   - VAE エンコード時に GFPGAN の高周波細部が不可逆に間引かれる
#   - Diffusion の Prior 引き寄せで GFPGAN の痕跡が上書きされやすい
#   - INT4 量子化が平均化を加速し、のっぺりした結果になりやすい
#   - FILL_DENOISING を変えても Phase 3a 単独より劣化するケースが実証された
#
# コードは削除しない:
#   - Fill INT4 + VRAM 戦略は将来資産 (v8.1 順序試行 / v9.0 CodeFormer・SUPIR 等)
#
# 復活:
#   PHASE3B_ENABLED = True にすれば従来どおり Phase 3b が動く
#
PHASE3B_ENABLED: bool = False

# Fill 推論の VRAM 戦略 (PHASE3B_ENABLED=True 時 · 24GB 互換 · A100 OOM 回避)
FILL_USE_CPU_OFFLOAD: bool = True
MAIN_PIPELINE_CPU_DURING_FILL: bool = True

# 2026-05-23: O3 コンサル + 実機検証で default OFF に確定
# 旧 0.35 は Phase 3a silent fail 時代の値で、実機では顔の個性を均しすぎた
GFPGAN_STRENGTH: float = 0.0
FILL_DENOISING: float = 0.25
ANGLE_BYPASS_YAW_DEG: float = 35.0
FACE_MASK_FEATHER_PX: int = 21
FACE_MASK_MARGIN_RATIO: float = 0.20

# ─── 立体感 Step1.6(RECON-020): VAE tiling 動的ガード ───
# True で「Pass1 直前に解像度判定で VAE tiling を自動 on/off」:
#   max(W,H) > 1536 → ON(whole-frame decode の OOM 回避)/ ≤1536 → OFF(高周波=立体感を残す)。
# 素朴な env グローバル False フリップは共有 VAE + 最大2048 で OOM(本番500)になるため使わない。
# env AIBO_VAE_TILING の明示指定はこのガードに優先(明示 > 自動)。
# 既定 False = 現状維持(後退ゼロ)。本番フリップは確認スイープ合格後に司令部が True にする。
VAE_TILING_GUARD: bool = True

# ─── Phase 3 用プロンプト ───
NEGATIVE_PROMPT_BASE: str = (
    "smooth skin, plastic, cgi, airbrushed, doll-like, "
    "overly smooth face, perfect skin, mannequin, waxy skin, "
    "overly retouched, blurry, low quality, distorted, lowres, bad anatomy"
)

POSITIVE_PROMPT_TEXTURE: str = (
    "natural skin texture, visible pores, individual hair strands, "
    "film grain, subsurface scattering, photorealistic skin, "
    "subtle skin imperfections"
)


# ============================================================================
# 🎨 Section 1.1 · 戦略列挙
# ============================================================================

class StrategyKind(str, Enum):
    """環境別ロード戦略"""

    A100_80GB_BF16     = "a100_80gb_bf16"       # bf16 純正 + 自前 PuLID Processor
    A100_40GB_NUNCHAKU = "a100_40gb_nunchaku"   # Nunchaku INT4 + pulid_forward
    A100_40GB_GGUF     = "a100_40gb_gguf"       # Nunchaku 失敗時のフォールバック
    T4_GGUF_Q5         = "t4_gguf_q5"           # Colab Free 用
    UNSUPPORTED        = "unsupported"


class StudioMode(str, Enum):
    """3 モード (UI.txt 由来)"""

    PORTRAIT   = "portrait"
    COORDINATE = "coordinate"
    SITUATION  = "situation"


# ============================================================================
# 🔍 Section 1.2 · RuntimeStrategy (環境検出)
# ============================================================================

@dataclass
class RuntimeStrategy:
    """
    起動時に環境を検出し、適切な戦略を選択する。

    判定優先順位:
        1. CUDA 利用可能か
        2. VRAM 容量 (80GB / 40GB / 16GB)
        3. Nunchaku 利用可否 (40GB の場合のみ判定)
    """

    kind: StrategyKind
    vram_gb: float
    gpu_name: str
    cuda_available: bool
    nunchaku_available: bool
    torch_version: str
    cuda_version: Optional[str]

    @classmethod
    def detect(cls) -> "RuntimeStrategy":
        """環境を検出して戦略を返す"""

        cuda_available = torch.cuda.is_available()

        if not cuda_available:
            return cls(
                kind=StrategyKind.UNSUPPORTED,
                vram_gb=0.0,
                gpu_name="(no CUDA)",
                cuda_available=False,
                nunchaku_available=False,
                torch_version=torch.__version__,
                cuda_version=None,
            )

        props = torch.cuda.get_device_properties(0)
        vram_gb = props.total_memory / (1024 ** 3)
        gpu_name = props.name
        cuda_version = torch.version.cuda

        # Nunchaku の利用可否を import で判定 (40GB の場合のみ意味を持つ)
        nunchaku_available = cls._probe_nunchaku()

        # 戦略選択
        # 40GB は Nunchaku INT4 が VRAM 戦略上ほぼ必須なので、
        # 未 install の場合は A100_40GB_NUNCHAKU を選択して
        # ColabBootstrap で install を試みる (失敗時に GGUF へフォールバック)
        if vram_gb >= 75.0:
            kind = StrategyKind.A100_80GB_BF16
        elif vram_gb >= 38.0:
            # 40GB は常に Nunchaku を第一選択 (install 試行)
            # Bootstrap 側で install 失敗時に A100_40GB_GGUF へ降格
            kind = StrategyKind.A100_40GB_NUNCHAKU
        elif vram_gb >= 14.0:
            kind = StrategyKind.T4_GGUF_Q5
        else:
            kind = StrategyKind.UNSUPPORTED

        return cls(
            kind=kind,
            vram_gb=vram_gb,
            gpu_name=gpu_name,
            cuda_available=cuda_available,
            nunchaku_available=nunchaku_available,
            torch_version=torch.__version__,
            cuda_version=cuda_version,
        )

    @staticmethod
    def _probe_nunchaku() -> bool:
        """Nunchaku が import 可能かを検出 (副作用なし)"""
        try:
            import importlib.util
            spec = importlib.util.find_spec("nunchaku")
            if spec is None:
                return False
            # NunchakuFluxTransformer2dModel が実体としてあるか確認
            mod = importlib.import_module("nunchaku")
            return hasattr(mod, "NunchakuFluxTransformer2dModel")
        except Exception:
            return False

    # ─── 戦略の判定ヘルパ ───

    def is_nunchaku(self) -> bool:
        return self.kind == StrategyKind.A100_40GB_NUNCHAKU

    def is_bf16_pure(self) -> bool:
        return self.kind == StrategyKind.A100_80GB_BF16

    def is_gguf(self) -> bool:
        return self.kind in (StrategyKind.A100_40GB_GGUF, StrategyKind.T4_GGUF_Q5)

    def needs_cpu_offload(self) -> bool:
        """CPU offload が必須な環境か (T4 等)"""
        return self.kind == StrategyKind.T4_GGUF_Q5

    def can_compile(self) -> bool:
        """torch.compile (regional) が使える環境か"""
        # Nunchaku は独自最適化のため compile 不要
        # CPU offload 環境は CUDA graph 衝突するため不可
        return self.kind == StrategyKind.A100_80GB_BF16

    # ─── PuLID 注入方式の判定 ───

    def pulid_injection_method(self) -> str:
        """PuLID 注入の実装方式を返す"""
        if self.is_nunchaku():
            return "pulid_forward_methodtype"  # nunchaku.models.pulid.pulid_forward
        else:
            return "aibo_pulid_attn_processor"  # 自前 FluxAttnProcessor2_0 継承

    # ─── LoRA API の判定 ───

    def lora_api(self) -> str:
        """LoRA ロード API を返す"""
        if self.is_nunchaku():
            return "transformer.update_lora_params"  # Nunchaku 専用
        else:
            return "pipeline.load_lora_weights"  # Diffusers 標準

    # ─── 表示用 ───

    def summary(self) -> str:
        lines = [
            "=" * 60,
            "🔍 RUNTIME STRATEGY DETECTED",
            "=" * 60,
            f"  Strategy:           {self.kind.value}",
            f"  GPU:                {self.gpu_name}",
            f"  VRAM:               {self.vram_gb:.1f} GB",
            f"  CUDA:               {self.cuda_version}",
            f"  PyTorch:            {self.torch_version}",
            f"  Nunchaku 利用可能:  {self.nunchaku_available}",
            f"  PuLID 注入方式:     {self.pulid_injection_method()}",
            f"  LoRA API:           {self.lora_api()}",
            f"  CPU Offload 必須:   {self.needs_cpu_offload()}",
            f"  torch.compile 可:   {self.can_compile()}",
            "=" * 60,
        ]
        return "\n".join(lines)

    def log(self):
        for line in self.summary().split("\n"):
            logger.info(line)


# ============================================================================
# 📐 Section 1.3 · データクラス (生成パラメータ)
# ============================================================================

@dataclass
class GenerationConfig:
    """1 枚分の生成パラメータ"""

    prompt: str = ""
    negative_prompt: str = "blurry, low quality, distorted, lowres, bad anatomy"
    width: int = 1024
    height: int = 1024
    num_inference_steps: int = -1        # -1 = auto (resolve で Nunchaku=8/bf16=28 切替)
    guidance_scale: float = 3.5
    seed: int = -1                        # -1 = random

    # Pass 2 (顔リファイン)
    enable_pass2: bool = True
    pass2_strength: float = 0.34         # 旧 0.45 → 0.34
    pass2_pulid_boost: float = 1.25      # 旧 1.5 → 1.25

    # Upscale
    enable_upscale: bool = False
    upscale_method: str = "supir"         # supir / real-esrgan / esrgan
    upscale_factor: int = 2

    # 推論最適化フラグ
    enable_regional_compile: bool = False  # bf16 環境のみ True 推奨

    def resolved_steps(self, strategy: RuntimeStrategy, *, hyper_flux_enabled: bool = True) -> int:
        """戦略に応じた推奨ステップ数を返す
        
        num_inference_steps < 0  → auto
            Hyper-FLUX 有効: 8 steps (どの戦略でも · デフォルト)
            Hyper-FLUX 無効: 28 steps (FLUX-dev 標準)
        num_inference_steps >= 0 → 明示指定値をそのまま使う
        """
        if self.num_inference_steps < 0:
            return 8 if hyper_flux_enabled else 28
        return self.num_inference_steps


@dataclass
class IdentityConfig:
    """キャラ一貫性パラメータ (PuLID + IP-Adapter + ControlNet)"""

    reference_image: Optional[Image.Image] = None
    # Week 1: PuLID 多枚フュージョン用 (同一人物の複数参照)
    reference_images: Optional[list[Image.Image]] = None

    # PuLID (v0.9.0 · Identity 優先版)
    pulid_weight: float = 0.7  # REVERT (2026-06-12): OP-CHANGE-001 の 0.7→0.6 を差し戻し。
                               #    OP-CHANGE-001 の 0.6 は「撤去済の第3脚(style-LoRA)」前提の
                               #    3 段並列値で、第3脚が無い現構成では identity 不足→別人化
                               #    (base 不保持の主因)。Setting A 確定時の実機検証値 0.7 へ revert
                               #    (PO 確認・Nika-chan 復活)。
                               # ── 以下は旧 0.6 の根拠(撤去済 第3脚前提・無効・履歴)──
                               # ※ 旧 3 段並列既定 = 0.6。D1 応答曲線 + PO 目視で決定:
                               #    cos 最適 = 1.0 だが焼け/プラスチック域 → 見た目最適 = 0.6
                               #    (似てる × 自然の両取り点)。商用 React→FastAPI の既定。
                               # ※ 単独運用時 (Stage 4-D-2 only) は 2.5 が黄金値(据置)
                               # ※ 0.7 = v7.4.0 Phase 1 実機確定値 (PO 探索 · 2026-05-06)。
                               #    PuLID 0.7/0.85/1.0 大差なし (エネルギー総量一定の法則)
                               # ※ 旧 3 段並列構成 = IP-Adapter 0.75 + style-LoRA(第3レバー)0.6 + PuLID 0.6
    # 2026-05-23: O3 コンサル + 実機検証で Setting A に刷新
    pulid_sigma_start: float = 0.25           # 旧 0.2 → 0.25
    pulid_sigma_end: float = 0.90             # 旧 1.0 → 0.90
    pulid_double_interval: int = 2

    # IP-Adapter Plus Face
    ip_adapter_weight: float = 0.75  # 旧 0.6 → 0.75 (ACE++ 撤去分を補填)
                                    # ※ ACE++ との競合を避けるため 1.0 → 0.6 へ半減

    # ─── ACE++ Portrait LoRA (v7.4.0 Phase 1 NEW) ──
    # リサーチ先生レポート 3-A 推奨値
    enable_ace_plus: bool = True                # ACE++ ON/OFF トグル
    ace_plus_weight: float = 0.6                # 黄金値 (並列構成時)
    ace_plus_lora_path: str = "/content/drive/MyDrive/aibo_v7/_models/ace_plus/ace_plus_portrait_lora.safetensors"

    # ─── ACE++ Subject LoRA (v7.4.0 Phase 2 v2 NEW · 2026-05-06) ──
    # 戦略 B' 改訂版 (USO Pivot)
    # サンダル先生 + リサーチ先生 双方一致判定
    # rank 16 軽量版 · 服/物体保持に特化
    enable_ace_plus_subject: bool = True                # ON/OFF トグル
    ace_plus_subject_weight: float = 0.0                # デフォルト 0.0 (Stage 1 想定)
                                                        # Stage 2 では 0.6 推奨
    ace_plus_subject_lora_path: str = "/content/drive/MyDrive/aibo_v7/_models/ace_plus/ace_plus_subject_lora.safetensors"

    # ─────────────────────────────────────────────────────
    # 🎭 ControlNet (legacy single-mode フィールド · 後方互換性のため維持)
    # ─────────────────────────────────────────────────────
    controlnet_weight: float = 0.5
    controlnet_type: str = "pose"  # pose / canny / depth / soft_edge / gray

    # ─────────────────────────────────────────────────────
    # 🎭 Multi-ControlNet (v7.2.2 Patch C · v5.7.x で実証済)
    # Task ID (Union Pro): 0=Canny, 1=Tile, 2=Depth, 3=Blur, 4=Pose, 5=Gray, 6=Low-Q
    # ─────────────────────────────────────────────────────
    enable_multi_cn: bool = False  # COORDINATE/SITUATION で True 化しやすい · PORTRAIT は通常 False

    cn_pose_weight: float = 0.9  # Union Pro 2.0 公式推奨寄り (0.9)
    cn_depth_weight: float = 0.7  # 公式 0.8 をやや弱化 → 立体感 + プロンプト忠実度のバランス

    cn_pose_guidance_end: float = 0.65  # Pose CN を効かせる範囲 (timestep 比率 · 65% 過ぎたら CN OFF 想定)
    cn_depth_guidance_end: float = 0.65  # 旧 0.80 → 0.65 (顔ディテール解放)

    cn_use_pose: bool = True   # Multi-CN 内で Pose を有効化
    cn_use_depth: bool = True  # Multi-CN 内で Depth を有効化 (AI 画像感を抑える主役)

    # InstantID (P2 候補 · 第 4 軸)
    enable_instantid: bool = False
    instantid_weight: float = 0.0

    # ─── ★ Patch C Stage 3c NEW: アプローチ X (顔/ポーズ分離) ───
    # 詳細: docs/Patch_C_Stage_3_Implementation_Design_v2.md セクション 2.2

    pose_reference_image: Optional[Image.Image] = None
    """
    ポーズ参照画像 (Optional · 全身写真推奨)。
    指定時: この画像から OpenposeDetector で骨格抽出
    None 時: reference_image から骨格抽出 (顔メイン画像だと不完全)
    """

    depth_reference_image: Optional[Image.Image] = None
    """
    深度参照画像 (Optional · シーン奥行き制御)。
    優先順位: depth_reference_image > pose_reference_image > reference_image
    None 時: ポーズ参照 or 顔参照から深度抽出
    """

    # ─── Multi-CN 抽出器設定 (Stage 3c NEW) ──────────────

    cn_depth_model_size: str = "large"
    """
    Depth-Anything-V2 モデルサイズ ('small' / 'base' / 'large')。

    ⚠️ ライセンス戦略:
        - 'large' (CC-BY-NC): 開発期·精度最優先 (デフォ)
        - 'small' (Apache 2.0): 商用化前に切替必須
        - 'base' (CC-BY-NC): 使わない (中途半端)
    """

    def get_reference_images(self) -> list[Image.Image]:
        """参照画像リストを取得 (新旧 API 統一)"""
        if self.reference_images:
            return self.reference_images
        if self.reference_image:
            return [self.reference_image]
        return []

    def resolved_pulid_weight(self, strategy: RuntimeStrategy) -> float:
        """環境別の推奨 PuLID weight を返す

        pulid_weight < 0  → auto (環境別デフォルト)
        pulid_weight >= 0 → 明示指定値をそのまま使う
        """
        if self.pulid_weight < 0:
            return 0.85 if strategy.is_nunchaku() else 1.5
        return self.pulid_weight


@dataclass
class LoRAEntry:
    """単一 LoRA エントリ"""

    name: str
    path: str                             # ローカルパス or HF Hub repo_id
    weight: float = 1.0
    enabled: bool = True
    trigger_words: str = ""

    # Nunchaku 環境では filename 指定が必要な場合がある
    hf_filename: Optional[str] = None     # 例: "Hyper-FLUX.1-dev-8steps-lora.safetensors"


@dataclass
class ModeConfig:
    """3 モード (PORTRAIT / COORDINATE / SITUATION) の表示・既定値"""

    mode: StudioMode
    label: str
    sub_label: str                        # 日本語サブラベル
    icon: str
    default_prompt: str
    default_negative: str
    aspect_ratio: tuple[int, int]         # (width, height)
    default_controlnet_type: str          # legacy 単一モード CN 用 (後方互換)

    # ─────────────────────────────────────────────────────
    # 🎭 Multi-CN 既定値 (Patch C 追加)
    # ─────────────────────────────────────────────────────
    default_enable_multi_cn: bool = False  # このモードで Multi-CN をデフォルトで有効化するか
    default_cn_use_pose: bool = True       # このモードで Pose CN をデフォルトで使うか
    default_cn_use_depth: bool = True      # このモードで Depth CN をデフォルトで使うか

    @classmethod
    def get(cls, mode: StudioMode) -> "ModeConfig":
        """モード定義を取得"""
        return _MODE_PRESETS[mode]


_MODE_PRESETS: dict[StudioMode, ModeConfig] = {
    StudioMode.PORTRAIT: ModeConfig(
        mode=StudioMode.PORTRAIT,
        label="Portrait",
        sub_label="人物撮影",
        icon="👤",
        default_prompt=(
            "full body shot, standing pose, head to toe, "
            "entire body visible including feet, "
            "wearing a fitted white top, slim skinny jeans, sneakers, "
            "soft key light, 50mm lens, professional fashion photography, "
            "clean studio background, cinematic, sharp focus"
        ),
        default_negative=(
            "cropped legs, cropped feet, headshot, close-up, bust shot, "
            "lowres, bad anatomy, blurry, extra fingers, jpeg artifacts, "
            "watermark, loose clothing, oversized clothes, baggy"
        ),
        aspect_ratio=(832, 1216),  # 2:3 (FLUX 全身ショット鉄板比率)
        default_controlnet_type="pose",
        # 🎭 Patch C: PORTRAIT は顔重視 → Multi-CN 無効 (現状維持)
        default_enable_multi_cn=False,
        default_cn_use_pose=False,
        default_cn_use_depth=False,
    ),
    StudioMode.COORDINATE: ModeConfig(
        mode=StudioMode.COORDINATE,
        label="Coordinate",
        sub_label="服装・体型",
        icon="👕",
        default_prompt=(
            "full body fashion shot, standing pose, "
            "fitted white top, slim skinny jeans, white sneakers, "
            "neutral studio background, soft fashion lighting, "
            "natural pose, photographic, cinematic"
        ),
        default_negative=(
            "lowres, bad anatomy, blurry, extra fingers, jpeg artifacts, watermark, "
            "deformed legs, awkward pose"
        ),
        aspect_ratio=(1024, 1536),  # 2:3 (full body)
        default_controlnet_type="pose",
        # 🎭 Patch C: COORDINATE は構図重視 → Pose + Depth 両方 ON
        default_enable_multi_cn=True,
        default_cn_use_pose=True,
        default_cn_use_depth=True,
    ),
    StudioMode.SITUATION: ModeConfig(
        mode=StudioMode.SITUATION,
        label="Situation",
        sub_label="演出・背景",
        icon="📸",
        default_prompt="walking through a park at golden hour, warm sunlight, 35mm handheld, lifestyle",
        default_negative="lowres, bad anatomy, blurry, extra fingers, jpeg artifacts, watermark",
        aspect_ratio=(1280, 1024),  # 5:4 (環境を含める横長)
        default_controlnet_type="depth",
        # 🎭 Patch C: SITUATION は背景立体感重視 → Depth 主力, Pose 副
        default_enable_multi_cn=True,
        default_cn_use_pose=False,  # Pose は人物姿勢用なのでシーン重視時は OFF
        default_cn_use_depth=True,
    ),
}


# ============================================================================
# ⚙️ Section 1.4 · システム全体設定
# ============================================================================

@dataclass
class SystemConfig:
    """システム全体の設定 (起動時に確定)"""

    # ─── 基本パス ───
    # PO 環境: G:\マイドライブ\あいぼすたじお2 → Colab 側では下記パスで見える
    drive_root: Path = Path("/content/drive/MyDrive/あいぼすたじお2")
    cache_dir:  Path = Path("/content/aibo_v7_cache")        # SSD 上の高速キャッシュ (Colab ローカル)
    output_dir: Path = Path("/content/aibo_v7_outputs")      # 生成物 (定期 rsync で drive_root/outputs へ)
    backup_dir: Path = Path("/content/drive/MyDrive/あいぼすたじお2/_backups")

    # ─── ベースモデル ───
    base_model_repo:  str = "black-forest-labs/FLUX.1-dev"
    nunchaku_repo:    str = "nunchaku-tech/nunchaku-flux.1-dev"
    nunchaku_filename_template: str = "svdq-{precision}_r32-flux.1-dev.safetensors"
    gguf_filename:    str = "flux1-dev-Q5_K_M.gguf"
    redux_repo:       str = "black-forest-labs/FLUX.1-Redux-dev"

    # ─── 周辺モデル ───
    controlnet_repo: str = "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0"
    ip_adapter_repo: str = "XLabs-AI/flux-ip-adapter"        # FLUX 用
    pulid_repo:      str = "guozinan/PuLID"
    pulid_filename:  str = "pulid_flux_v0.9.0.safetensors"   # ⚠️ v0.9.0 (Identity 優先)
    pulid_official_git: str = "https://github.com/ToTheBeginning/PuLID.git"
    hyper_flux_repo: str = "ByteDance/Hyper-SD"
    hyper_flux_filename: str = "Hyper-FLUX.1-dev-8steps-lora.safetensors"
    hyper_flux_weight: float = 0.125
    enable_hyper_flux: bool = True  # 8step 加速 LoRA · UI で OFF 切替可能

    # ─── 動作フラグ ───
    enable_pulid: bool = True
    enable_ip_adapter: bool = True
    enable_controlnet: bool = True
    enable_upscaler: bool = True
    enable_redux: bool = True
    enable_instantid: bool = False         # P2 候補

    # ─── LoRA Stack ───
    max_lora_count: int = 8

    # ─── 推論最適化 ───
    enable_regional_compile: bool = False  # 戦略確定後にセット
    enable_set_attention_impl: bool = True # Nunchaku 環境のみ "nunchaku-fp16"
    fbcache_threshold: float = 0.0          # 0.0 = 完全封印 (PuLID×CN 衝突防止)

    # ─── DTGI (CHRONO SINGULARITY) ───
    dtgi_decay_max: float = 0.30
    dtgi_decay_start: float = 0.5

    # ─── Colab セッション対策 ───
    enable_gdrive_sync: bool = True
    gdrive_sync_interval_sec: int = 300    # 5 分

    # ─── 戦略 (起動時に detect) ───
    strategy: Optional[RuntimeStrategy] = None

    def resolve_strategy(self) -> RuntimeStrategy:
        """戦略を確定 (まだなら detect, あれば再利用)"""
        if self.strategy is None:
            self.strategy = RuntimeStrategy.detect()
            self.strategy.log()

            # 戦略に応じてフラグを微調整
            if self.strategy.is_bf16_pure():
                # bf16 環境では regional_compile 推奨
                self.enable_regional_compile = True
            elif self.strategy.is_nunchaku():
                # Nunchaku 環境では compile 不要 + FBCache 封印確認
                self.enable_regional_compile = False
                self.fbcache_threshold = 0.0
            else:
                # GGUF/T4 環境は compile 不可
                self.enable_regional_compile = False

        return self.strategy

    def ensure_dirs(self):
        """必要なディレクトリを作成"""
        for d in (self.cache_dir, self.output_dir, self.backup_dir):
            d.mkdir(parents=True, exist_ok=True)
        logger.info(f"📁 ディレクトリ準備完了: cache={self.cache_dir}, output={self.output_dir}")

    # ─── 戦略別パラメータ resolver ───

    def resolve_nunchaku_filename(self) -> str:
        """Nunchaku の precision に応じたファイル名を返す"""
        precision = "int4"  # A100 (Ampere) デフォルト
        try:
            from nunchaku.utils import get_precision
            precision = get_precision()
        except Exception:
            pass
        return self.nunchaku_filename_template.format(precision=precision)


# ============================================================================
# 🛡️ Section 1.5 · ガード関数
# ============================================================================

def assert_supported_strategy(strategy: RuntimeStrategy) -> None:
    """サポート外環境では即座に失敗させる"""
    if strategy.kind == StrategyKind.UNSUPPORTED:
        raise RuntimeError(
            f"❌ サポート外環境です:\n"
            f"   GPU: {strategy.gpu_name}\n"
            f"   VRAM: {strategy.vram_gb:.1f} GB\n"
            f"   CUDA: {strategy.cuda_available}\n"
            f"\n"
            f"対応環境:\n"
            f"  - A100 80GB / H100 (推奨)\n"
            f"  - A100 40GB (Nunchaku INT4 必須)\n"
            f"  - T4 16GB  (Colab Free フォールバック)\n"
        )


# ============================================================================
# 🔧 Section 1.6 · スタンドアロン動作確認
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🌌 AIBO v7.2 · Section 1 (Config & Runtime Strategy) 動作確認")
    print("=" * 60)

    # 1. 環境検出
    strategy = RuntimeStrategy.detect()
    print(strategy.summary())

    # 2. SystemConfig 生成 + 戦略確定
    sys_cfg = SystemConfig()
    sys_cfg.resolve_strategy()
    print()
    print(f"📦 base_model_repo:    {sys_cfg.base_model_repo}")
    print(f"📦 pulid_filename:     {sys_cfg.pulid_filename}")
    print(f"📦 hyper_flux_repo:    {sys_cfg.hyper_flux_repo}")
    print(f"📦 enable_hyper_flux:   {sys_cfg.enable_hyper_flux}")
    print(f"📦 enable_compile:     {sys_cfg.enable_regional_compile}")
    print(f"📦 fbcache_threshold:  {sys_cfg.fbcache_threshold}")

    # 3. モード定義の確認
    print()
    print("🎨 ModeConfig (3 モード):")
    for mode in StudioMode:
        m = ModeConfig.get(mode)
        print(f"  {m.icon} {m.label} ({m.sub_label})")
        print(f"     prompt: {m.default_prompt[:60]}...")
        print(f"     aspect: {m.aspect_ratio}")
        print(f"     ctrl:   {m.default_controlnet_type}")

    # 4. データクラス生成テスト
    print()
    print("🧪 データクラス生成テスト:")
    gen_cfg = GenerationConfig(prompt="test", num_inference_steps=-1)
    print(f"  GenerationConfig: steps_resolved = {gen_cfg.resolved_steps(strategy, hyper_flux_enabled=sys_cfg.enable_hyper_flux)}")

    id_cfg = IdentityConfig(pulid_weight=-1.0)
    print(f"  IdentityConfig:   pulid_weight_resolved = {id_cfg.resolved_pulid_weight(strategy)}")

    print()
    print("✅ Section 1 動作確認完了")
