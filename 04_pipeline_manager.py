"""
================================================================================
🌌 AIBO CYBER STUDIO v7.2 · Section 4 · Pipeline Manager & Asset Stack
================================================================================

📌 このファイルの責務:
    1. FluxA100PipelineManager: 戦略別の FluxPipeline 構築
       - a100_40gb_nunchaku: NunchakuFluxTransformer2dModel + Hyper-FLUX LoRA
       - a100_80gb_bf16:    bf16 純正 + regional_compile
       - a100_40gb_gguf / t4_gguf_q5: GGUF + CPU offload
    2. MultiLoRAStack: 環境別 LoRA API 分岐 (Nunchaku 専用 vs Diffusers 標準)
    3. UpscalerHub: SUPIR / Real-ESRGAN / ESRGAN 切替 (lazy_init)
    4. ReferenceImageDB: 参照画像 + メタデータ管理
    5. AssetManager: 上記の統合管理

依存:
    - 01_config.py (SystemConfig, RuntimeStrategy, LoRAEntry)
    - 02_colab_setup.py (NunchakuInstaller で Nunchaku が install 済み)
    - 03_identity_engine.py (IdentityEngine 連携 · transformer 共有)
    - torch / diffusers / huggingface_hub

戦略別の構築フロー:
    a100_40gb_nunchaku:
        1. NunchakuFluxTransformer2dModel.from_pretrained()
        2. set_attention_impl("nunchaku-fp16")  ← 1.2x 高速化
        3. FluxPipeline(transformer=NC, text_encoder=None)  ← VRAM 節約
        4. Hyper-FLUX LoRA を update_lora_params() で注入 (オプション)
        5. FBCache を threshold=0.0 で封印 ← PuLID×CN 衝突防止
        6. FluxImg2ImgPipeline 共有 (Pass 2 用)

    a100_80gb_bf16:
        1. FluxPipeline.from_pretrained(torch_dtype=bf16).to("cuda")
        2. transformer.compile_repeated_blocks(fullgraph=True) ← regional compile
        3. Hyper-FLUX LoRA を pipe.load_lora_weights() で注入
        4. FluxImg2ImgPipeline 共有

Author: 🥷 CTO くろうど
Date:   2026-05-03
Version: v7.2
================================================================================
"""

from __future__ import annotations

import gc
import json
import os
import struct
from importlib import import_module
from pathlib import Path
from types import MethodType
from typing import Any, Optional

import torch
from PIL import Image

# ─── 01_config から型を import ───
_cfg_mod = import_module("01_config")
SystemConfig    = _cfg_mod.SystemConfig
RuntimeStrategy = _cfg_mod.RuntimeStrategy
StrategyKind    = _cfg_mod.StrategyKind
LoRAEntry       = _cfg_mod.LoRAEntry
logger          = _cfg_mod.logger

# 🎭 v7.2.2 Patch C: FluxControlNet 系 import (利用不可ならフラグでフォールバック)
try:
    from diffusers import FluxControlNetModel, FluxControlNetPipeline

    _CN_PIPELINE_AVAILABLE = True
except ImportError as _e_cn_imp:
    FluxControlNetModel = None  # type: ignore
    FluxControlNetPipeline = None  # type: ignore
    _CN_PIPELINE_AVAILABLE = False
    logger.warning(f"⚠️ FluxControlNetPipeline 利用不可 · Patch C 非対応: {_e_cn_imp}")

try:
    from diffusers.models import FluxMultiControlNetModel

    _MULTI_CN_AVAILABLE = True
except ImportError:
    FluxMultiControlNetModel = None  # type: ignore
    _MULTI_CN_AVAILABLE = False
    logger.warning("⚠️ FluxMultiControlNetModel 利用不可 · 単体 CN にフォールバック")

# ─── Stage 3e: Nunchaku 互換性ヘルパー ─────────────────────────────
class _DummyEncoderHidProj:
    """
    Nunchaku PuLIDFluxPipeline の IP-Adapter コードパス互換ダミー。

    背景:
        Nunchaku 純正 pipeline_flux_pulid.py line 662 が
        transformer.encoder_hid_proj.num_ip_adapters を無条件参照する。
        AIBO は IP-Adapter 不使用だが、属性が存在しないと AttributeError。

    対処:
        num_ip_adapters=0 のダミーを transformer に attach することで
        AIBO 経路 (IP-Adapter なし) で正常動作させる。
    """

    num_ip_adapters = 0

# ============================================================================
# ⚒️ Section 4.0 · ヘルパ
# ============================================================================

# ============================================================================
# 🛡️ C0 · safetensors ロード前検証ゲート (RECON-002 / IMPL-001)
#   Drive FUSE 越しの巨大 safetensors 途中切れ → 素 Flux 縮退(外国人化)を
#   ロード前に loud に fail-fast させる。header だけ読む軽量検証。
# ============================================================================

class C0VerificationError(RuntimeError):
    """C0 検証で safetensors の破損を検知した時に投げる。
    既存の degrade-except に飲まれず fail-fast させるための専用型。"""


def verify_safetensors(path) -> tuple[bool, str]:
    """safetensors を header だけ読んで完全性を検証する(全体は読まない)。
    戻り値 (ok, reason)。"""
    size = os.path.getsize(path)
    if size < 8:
        return (False, "smaller-than-header")
    with open(path, "rb") as f:
        N = struct.unpack("<Q", f.read(8))[0]          # header 長 (LE u64)
        if 8 + N > size:
            return (False, "header-truncated")
        head = f.read(N)
        if head[:1] != b"{":
            return (False, "not-json-header")
        meta = json.loads(head)
        max_end = max(v["data_offsets"][1]
                      for k, v in meta.items() if k != "__metadata__")
    expected = 8 + N + max_end
    if expected != size:
        return (False, f"not-fully-covered expected={expected} actual={size}")
    return (True, "ok")


def _c0_verify_file(name: str, path) -> None:
    """具体的なローカルパスに対し C0 検証。FAIL なら error ログ + raise。"""
    if not path or not os.path.exists(path):
        logger.warning(f"[C0] SKIP {name}: path unresolved/absent path={path}")
        return
    ok, reason = verify_safetensors(path)
    if ok:
        logger.info(f"[C0] OK {name} {path}")
        return
    logger.error(f"[C0] FAIL {name} safetensors: {reason} path={path}")
    raise C0VerificationError(f"[C0] {name}: {reason} path={path}")


def _c0_verify_hf_single(name: str, repo_id: str, filename: str) -> None:
    """HF cache 上の単一ファイルの実体パスを解決して C0 検証(DL はしない)。
    cache に無ければ warn でスキップ(握りつぶさない)。"""
    try:
        from huggingface_hub import try_to_load_from_cache
        path = try_to_load_from_cache(repo_id=repo_id, filename=filename)
    except Exception as e:
        logger.warning(f"[C0] SKIP {name}: cache 解決失敗 repo={repo_id} file={filename} ({e})")
        return
    if not isinstance(path, str):
        logger.warning(f"[C0] SKIP {name}: HF cache 未在 repo={repo_id} file={filename}")
        return
    _c0_verify_file(name, path)


def _c0_verify_hf_repo(name: str, repo_id: str) -> None:
    """repo 内の cache 済み *.safetensors を列挙して各々 C0 検証(best-effort)。
    snapshot を解決できなければ warn でスキップ(握りつぶさない)。"""
    try:
        from huggingface_hub import snapshot_download
        snap = snapshot_download(repo_id=repo_id,
                                 allow_patterns=["*.safetensors"],
                                 local_files_only=True)
    except Exception as e:
        logger.warning(f"[C0] SKIP {name}: snapshot 未解決 repo={repo_id} ({e})")
        return
    files = sorted(Path(snap).rglob("*.safetensors"))
    if not files:
        logger.warning(f"[C0] SKIP {name}: cache 済み safetensors 無し repo={repo_id}")
        return
    for fp in files:
        _c0_verify_file(f"{name}:{fp.name}", str(fp))


def _flush_vram():
    """VRAM クリーンアップ"""
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.synchronize()


def _vram_used_gb() -> float:
    if not torch.cuda.is_available():
        return 0.0
    return torch.cuda.memory_allocated() / (1024 ** 3)


# city96/FLUX.1-dev-gguf — flux1-dev-Q5_K_M.gguf 等はリポジトリに存在しない
_GGUF_CITY96_REPO = "city96/FLUX.1-dev-gguf"
_GGUF_CITY96_FALLBACK_ORDER = (
    "flux1-dev-Q5_K_S.gguf",
    "flux1-dev-Q5_0.gguf",
    "flux1-dev-Q5_1.gguf",
    "flux1-dev-Q4_K_S.gguf",
    "flux1-dev-Q8_0.gguf",
    "flux1-dev-Q4_0.gguf",
    "flux1-dev-Q6_K.gguf",
    "flux1-dev-Q4_1.gguf",
    "flux1-dev-Q3_K_S.gguf",
    "flux1-dev-Q2_K.gguf",
    "flux1-dev-F16.gguf",
)


def _resolve_city96_gguf_filename(preferred: str, repo_files: set[str]) -> tuple[str, bool]:
    """
    list_repo_files の結果から実在する GGUF を選択。
    Returns: (filename, matched_preferred)
    """
    candidates: list[str] = [preferred]
    for name in _GGUF_CITY96_FALLBACK_ORDER:
        if name not in candidates:
            candidates.append(name)
    for fn in candidates:
        if fn in repo_files:
            return fn, fn == preferred
    ggufs = sorted(f for f in repo_files if str(f).endswith(".gguf"))
    raise FileNotFoundError(
        f"{_GGUF_CITY96_REPO}: 希望・フォールバックとも欠落 "
        f"(tried {candidates[:8]}...). Repo .gguf: {ggufs}"
    )


# ============================================================================
# 🏛️ Section 4.1 · FluxA100PipelineManager
# ============================================================================

class FluxA100PipelineManager:
    """
    戦略別の FluxPipeline を構築・管理する司令塔。

    保持する pipeline:
        pipe_base : 主に txt2img · 戦略別の構築
        pipe_i2i  : Pass 2 顔リファイン用 (transformer 共有)
        pipe_prior: Redux Prior (画像参照用 · オプション)

    transformer は内部で _shared_transformer として保持し、
    pipe_base / pipe_i2i / IdentityEngine の全てが同じインスタンスを参照する。
    """

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self.strategy = sys_cfg.resolve_strategy()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.bfloat16

        # ─── pipeline 群 ───
        self.pipe_base = None          # FluxPipeline (主)
        self.pipe_i2i = None           # FluxImg2ImgPipeline (Pass 2)
        self.pipe_fill = None          # FluxFillPipeline (Phase 3b)
        self.pipe_prior = None         # FluxPriorReduxPipeline (オプション)

        # ─── 共有コンポーネント ───
        self._shared_transformer = None
        self._shared_vae = None

        # ─── 状態管理 ───
        self._initialized = False
        self._hyper_flux_loaded = False

        # 🎭 v7.2.2 Patch C Stage 2: Multi-ControlNet 用フィールド
        self.controlnet_model = None        # FluxMultiControlNetModel ラッパー
        self.pipe_cnet = None               # FluxControlNetPipeline (transformer 共有)
        self._controlnet_loaded = False     # lazy_init フラグ

        # Phase 3b: メインパイプ CPU 退避 ↔ GPU 復帰 (Fill INT4 lazy load 時)
        self._main_pipelines_offloaded = False

        # Phase C デバッグ: build() が False のとき最後の例外を外部から参照する
        self.last_build_error_message: str | None = None
        self.last_build_traceback: str | None = None

    # ─────────────────────────────────────────────────
    # 4.1.A · 公開 API: build()
    # ─────────────────────────────────────────────────

    def build(self) -> bool:
        """戦略に応じた pipeline を構築 (重い処理 · 数分かかる)"""
        if self._initialized:
            logger.info("ℹ️ [PipelineManager] 既に構築済 · skip")
            return True

        logger.info("=" * 60)
        logger.info(f"🏛️ FluxA100PipelineManager 構築開始 (strategy={self.strategy.kind.value})")
        logger.info("=" * 60)

        try:
            # Nunchaku / 大規模ロード前にキャッシュを空けてピーク VRAM を抑える
            if torch.cuda.is_available():
                torch.cuda.empty_cache()

            if self.strategy.is_nunchaku():
                self._build_nunchaku()
            elif self.strategy.is_bf16_pure():
                self._build_bf16()
            elif self.strategy.is_gguf():
                self._build_gguf()
            else:
                raise RuntimeError(f"未対応戦略: {self.strategy.kind.value}")

            # ─── 共通: I2I パイプライン構築 ───
            self._build_i2i()

            # ─── 共通: Redux Prior (画像参照) ───
            if self.sys_cfg.enable_redux:
                self._build_redux_prior()

            # ─── 共通: VAE 軽量化 ───
            self._enable_vae_optimizations()

            self._initialized = True
            _flush_vram()

            logger.info("=" * 60)
            logger.info(f"🎉 PipelineManager 構築完了 (VRAM 使用: {_vram_used_gb():.1f} GB)")
            logger.info("=" * 60)
            self.last_build_error_message = None
            self.last_build_traceback = None
            return True

        except Exception as e:
            self.last_build_error_message = f"{type(e).__name__}: {e}"
            import traceback
            tb = traceback.format_exc()
            self.last_build_traceback = tb
            logger.error(f"❌ [PipelineManager] 構築失敗: {e}")
            logger.error(tb)
            return False

    # ─────────────────────────────────────────────────
    # 4.1.B · 戦略別ビルダ
    # ─────────────────────────────────────────────────

    def _build_nunchaku(self):
        """A100 40GB · Nunchaku INT4 経路 (本命)"""
        logger.info("⚡ [Nunchaku 経路] 構築開始")
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
            torch.cuda.ipc_collect()

        from nunchaku import NunchakuFluxTransformer2dModel
        from diffusers import FluxPipeline

        # ─── 1. Nunchaku Transformer ロード ───
        flux_filename = self.sys_cfg.resolve_nunchaku_filename()
        flux_model_id = f"{self.sys_cfg.nunchaku_repo}/{flux_filename}"

        logger.info(f"  📥 [1/4] Nunchaku Transformer ロード: {flux_filename}")
        _c0_verify_hf_single("transformer", self.sys_cfg.nunchaku_repo, flux_filename)
        try:
            self._shared_transformer = NunchakuFluxTransformer2dModel.from_pretrained(
                flux_model_id,
                offload=True,  # 🥷 v7.2.1 Patch A.2: Nunchaku 内部 block-wise offload (DreamO 流)
            )
        except TypeError:
            # 古い Nunchaku は offload 非対応 → Patch A.1 相当で継続
            self._shared_transformer = NunchakuFluxTransformer2dModel.from_pretrained(
                flux_model_id,
            )

        # ─── Stage 3e: encoder_hid_proj ダミー追加 (Nunchaku 互換性) ──
        # 背景: Nunchaku PuLIDFluxPipeline は IP-Adapter コードパスで
        #       transformer.encoder_hid_proj.num_ip_adapters を参照する。
        #       AIBO は IP-Adapter 不使用だが、属性がないと AttributeError。
        if not hasattr(self._shared_transformer, "encoder_hid_proj") or self._shared_transformer.encoder_hid_proj is None:
            object.__setattr__(self._shared_transformer, "encoder_hid_proj", _DummyEncoderHidProj())
            logger.info("✅ [Stage 3e] encoder_hid_proj ダミー追加 (num_ip_adapters=0)")

        # FP16 Attention 有効化 (Flash-Attention2 比 1.2x 高速)
        if self.sys_cfg.enable_set_attention_impl:
            try:
                self._shared_transformer.set_attention_impl("nunchaku-fp16")
                logger.info("  ⚡ Attention impl: nunchaku-fp16 有効化 (1.2x 高速化)")
            except Exception as e:
                logger.info(f"  ℹ️ set_attention_impl スキップ: {e}")

        # ═══════════════════════════════════════════════════════════════════
        # 🥷 v7.2.1 Patch A: Hyper-FLUX 注入順序修正
        # ═══════════════════════════════════════════════════════════════════
        # 【経緯】PuLIDFluxPipeline.from_pretrained() は内部で transformer に
        #        pulid_ca 層を追加する。その「後」で update_lora_params()
        #        を呼ぶと LoRA state_dict に pulid_ca が無いため Missing keys
        #        エラーで失敗 → Hyper-FLUX 無効化 → 28 step 相当に降格。
        #
        # 【解決】Hyper-FLUX 注入を PuLIDFluxPipeline 構築「前」に移動。
        #        Nunchaku transformer に LoRA を先に焼き込んでから
        #        pulid_ca を後付けすれば、両者が共存できる。
        #
        # 【裏付け】V4 先生案 (前セッション) + Nunchaku 公式 strict=False
        #          修正方針と完全一致 (note.com/198619891990)。
        #          ComfyUI-nunchaku 公式実装も同じ流儀。
        # ═══════════════════════════════════════════════════════════════════

        # ─── 2. Hyper-FLUX LoRA を transformer 単体に先行注入 ───
        # ⚠️ 必ず PuLIDFluxPipeline 構築の「前」で実行
        if self.sys_cfg.enable_hyper_flux:
            self._inject_hyper_flux_nunchaku()
        else:
            logger.info("  ⏭ [2/5] Hyper-FLUX 無効 (enable_hyper_flux=False) · 28 steps デフォルト")

        # ─── 3. FluxPipeline 構築 (PuLIDFluxPipeline · 公式 PuLID 統合) ───
        # Nunchaku v1.2 では PuLIDFluxPipeline が公式提供されており、
        # __call__ で id_image 引数を受け取り内部で自動注入する。
        # transformer に pulid_ca が後付けされるが、Hyper-FLUX は既に焼き込み済み。
        #
        # 🥷 v7.2.1 Patch A.2: PuLIDFluxPipeline 構築前に明示的 VRAM クリーンアップ
        # Hyper-FLUX 注入で残った中間 tensor を解放しないと、
        # T5-XXL (9GB) + EVA-CLIP (3GB) のロードで OOM 発生する。
        skip_pipe_base_to_cuda = False  # enable_model_cpu_offload 成功時のみ True (④ と整合)
        _flush_vram()
        logger.info(f"  🧹 [VRAM] PuLIDFluxPipeline 構築前のクリーンアップ完了 (使用中: {_vram_used_gb():.1f} GB)")
        _c0_verify_hf_repo("base", self.sys_cfg.base_model_repo)

        if self.sys_cfg.enable_pulid:
            try:
                from nunchaku.pipeline.pipeline_flux_pulid import PuLIDFluxPipeline

                logger.info("  🚀 [3/5] PuLIDFluxPipeline 構築 (公式 PuLID 統合)")
                self.pipe_base = PuLIDFluxPipeline.from_pretrained(
                    self.sys_cfg.base_model_repo,
                    transformer=self._shared_transformer,
                    torch_dtype=self.dtype,
                    low_cpu_mem_usage=True,  # 🥷 v7.2.1: メモリ効率重視ロード
                )

                # 🥷 v7.2.1 Patch A.3: enable_model_cpu_offload を「条件付き」に
                # A100 40GB (実測 21GB ピーク) では offload は速度を犠牲にするだけ。
                # Nunchaku transformer offload=True (block-wise) で十分。
                # 環境変数 AIBO_FORCE_OFFLOAD=1 で従来動作にフォールバック可能。
                _force_offload = os.environ.get("AIBO_FORCE_OFFLOAD", "0") == "1"
                _gpu_total_gb = (
                    torch.cuda.get_device_properties(0).total_memory / 1e9
                    if torch.cuda.is_available()
                    else 0.0
                )
                _need_offload = _force_offload or _gpu_total_gb < 30.0

                if _need_offload:
                    try:
                        self.pipe_base.enable_model_cpu_offload()
                        if hasattr(self.pipe_base, "_exclude_from_cpu_offload"):
                            self.pipe_base._exclude_from_cpu_offload.append("pulid_model")
                        logger.info(f"  ⏬ [VRAM] enable_model_cpu_offload (GPU={_gpu_total_gb:.0f}GB)")
                        skip_pipe_base_to_cuda = True
                    except Exception as e:
                        logger.info(f"  ℹ️ enable_model_cpu_offload スキップ: {e}")
                else:
                    logger.info(f"  🚀 [SPEED] enable_model_cpu_offload SKIP (GPU={_gpu_total_gb:.0f}GB · 速度優先)")

                # 🥷 v7.2.1 Patch A.3: attention_slicing は A100 では速度ペナルティのため削除
                # (Patch A.2 で有効化していたが 26 秒 → 削除で 18 秒程度の見込み)
                # 環境変数 AIBO_FORCE_OFFLOAD=1 のときのみ復活
                if _need_offload:
                    try:
                        self.pipe_base.enable_attention_slicing()
                        logger.info("  ✂️ [VRAM] enable_attention_slicing 有効化 (offload mode)")
                    except Exception as e:
                        logger.info(f"  ℹ️ enable_attention_slicing スキップ: {e}")
                else:
                    logger.info("  🚀 [SPEED] attention_slicing SKIP (A100 速度優先)")

                # 🥷 v7.2.1 Patch A.3: pulid_model は GPU 常駐
                # A100 40GB なら EVA-CLIP (3GB) + InsightFace (~1GB) は誤差レベル
                # CPU↔GPU 転送が embedding 抽出のたびに発生するのを回避
                # 環境変数 AIBO_FORCE_OFFLOAD=1 のときのみ CPU 退避
                if _need_offload:
                    try:
                        if hasattr(self.pipe_base, "pulid_model"):
                            self.pipe_base.pulid_model.to(torch.device("cpu"))
                            logger.info("  💤 [VRAM] pulid_model CPU 退避 (offload mode)")
                    except Exception as e:
                        logger.info(f"  ℹ️ pulid_model CPU 退避スキップ: {e}")
                else:
                    logger.info("  🚀 [SPEED] pulid_model GPU 常駐 (A100 速度優先)")

                _flush_vram()
                logger.info(f"  ✅ PuLIDFluxPipeline 構築完了 (VRAM 使用: {_vram_used_gb():.1f} GB)")
            except Exception as e:
                logger.warning(f"  ⚠️ PuLIDFluxPipeline 構築失敗: {e}")
                logger.warning(f"     → 通常 FluxPipeline でフォールバック (PuLID 不使用)")
                from diffusers import FluxPipeline
                self.pipe_base = FluxPipeline.from_pretrained(
                    self.sys_cfg.base_model_repo,
                    transformer=self._shared_transformer,
                    torch_dtype=self.dtype,
                )
                logger.warning("[OBS-A] enable_pulid=True だが PuLIDFluxPipeline 構築失敗 -> 素 FluxPipeline に縮退した")
        else:
            logger.info("  🚀 [3/5] FluxPipeline 構築 (PuLID 無効)")
            self.pipe_base = FluxPipeline.from_pretrained(
                self.sys_cfg.base_model_repo,
                transformer=self._shared_transformer,
                torch_dtype=self.dtype,
            )

        # ─── Stage 3e: Nunchaku 互換性パッチ ──────────────────
        self._patch_pipe_base_remove_ip_adapter()

        # 🥷 v7.2.1 Patch A.2: enable_model_cpu_offload 成功時は to(cuda) しない
        # (offload 機構と競合してエラーになる)。PuLID 無効 / offload 失敗時は従来通り GPU へ。
        if not skip_pipe_base_to_cuda:
            try:
                self.pipe_base.to(self.device)
            except Exception as e:
                logger.info(f"  ℹ️ pipe_base.to(cuda) スキップ: {e}")

        self._shared_vae = self.pipe_base.vae
        logger.info(f"[OBS-A] pipe_base class = {type(self.pipe_base).__name__} / enable_pulid={self.sys_cfg.enable_pulid}")

        # ─── 4. FBCache 封印 (PuLID×CN 衝突防止) ───
        self._seal_fbcache()

        logger.info("✅ [Nunchaku 経路] 構築完了")

    def ensure_controlnet(self):
        """
        ControlNet (Shakker Union Pro 2.0) と FluxControlNetPipeline を lazy load。
        Stage 3: Multi-CN (Pose + Depth) 対応。

        設計参照: docs/Patch_C_Stage_3_Implementation_Design_v2.md セクション 8

        重要事項:
            - transformer は pipe_base と共有 (NunchakuPuLIDBinder の bind_forward を温存)
            - VAE / Text Encoder / Tokenizer / Scheduler も共有
            - pipe_cnet 構築直後に transformer.forward を id_embeddings 自動注入版にラップ
        """
        if self._controlnet_loaded:
            return

        try:
            from diffusers import FluxControlNetModel, FluxControlNetPipeline
            from diffusers.models import FluxMultiControlNetModel  # noqa: F401
        except ImportError as e:
            logger.error(f"❌ FluxControlNet 系 import 失敗: {e}")
            return

        if self.pipe_base is None or self._shared_transformer is None:
            logger.error("❌ Pipeline 未構築 · _build_nunchaku() を先行実行")
            return

        # ─── Stage 3e: 念のため再確認 (起動順序による属性消失対策) ──
        if not hasattr(self._shared_transformer, "encoder_hid_proj"):
            object.__setattr__(self._shared_transformer, "encoder_hid_proj", _DummyEncoderHidProj())
            logger.info("✅ [Stage 3e] encoder_hid_proj 再追加 (ensure_controlnet 内)")

        # ─── 1. Shakker Union Pro 2.0 を BF16 でロード ──────────
        cn_repo = "Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0"
        logger.info(f"🎛️ [Stage 3b] ControlNet Union Pro 2.0 ロード: {cn_repo}")
        _c0_verify_hf_repo("controlnet", cn_repo)

        self.controlnet_model = FluxControlNetModel.from_pretrained(
            cn_repo,
            torch_dtype=torch.bfloat16,
        ).to(self.device)

        # ─── 2. FluxControlNetPipeline 構築 (transformer 共有) ──
        logger.info("🚀 [Stage 3b] FluxControlNetPipeline 構築 (transformer 共有)")

        self.pipe_cnet = FluxControlNetPipeline.from_pretrained(
            self.sys_cfg.base_model_repo,
            controlnet=[self.controlnet_model],  # リスト渡しで auto-wrap
            transformer=self._shared_transformer,  # ★ 共有: AIBO Binder の pulid_forward 維持
            vae=self.pipe_base.vae,
            text_encoder=self.pipe_base.text_encoder,
            text_encoder_2=self.pipe_base.text_encoder_2,
            tokenizer=self.pipe_base.tokenizer,
            tokenizer_2=self.pipe_base.tokenizer_2,
            scheduler=self.pipe_base.scheduler,
            torch_dtype=self.dtype,
        )

        # ─── Stage 3e-4: pipe_cnet に components を pipe_base から借用 ──
        # 背景:
        #   FluxControlNetPipeline.from_pretrained() で pipe_cnet を構築すると
        #   tokenizer / text_encoder / scheduler などが None になる謎の挙動。
        #   これにより推論時に self.tokenizer(...) が NoneType callable エラー。
        #
        # 対処:
        #   pipe_base から失われた components を借用する。
        #   pipe_base と pipe_cnet は同じ FLUX ベースなので components は互換。
        #
        # 借用対象:
        #   - tokenizer (CLIPTokenizer)
        #   - tokenizer_2 (T5Tokenizer)
        #   - text_encoder (CLIPTextModel)
        #   - text_encoder_2 (T5EncoderModel)
        #   - scheduler (FlowMatchEulerDiscreteScheduler)
        attach_targets = [
            "tokenizer", "tokenizer_2",
            "text_encoder", "text_encoder_2",
            "scheduler",
        ]

        borrowed = []
        for name in attach_targets:
            base_obj = getattr(self.pipe_base, name, None)
            cnet_obj = getattr(self.pipe_cnet, name, None)

            if cnet_obj is None and base_obj is not None:
                setattr(self.pipe_cnet, name, base_obj)
                # components dict も更新 (diffusers 内部で参照される)
                if hasattr(self.pipe_cnet, "components"):
                    self.pipe_cnet.components[name] = base_obj
                borrowed.append(name)

        if borrowed:
            logger.info(
                f"🔧 [Stage 3e-4] pipe_cnet components を pipe_base から借用: {borrowed}"
            )
        else:
            logger.info("✅ [Stage 3e-4] pipe_cnet components 全て構築済 (借用不要)")

        # ─── 3. transformer.forward ラップ (id_embeddings 自動注入) ─
        self._wrap_transformer_forward_for_cn()

        self._controlnet_loaded = True
        logger.info("✅ [Stage 3b] ControlNet pipeline 構築完了 (Nunchaku 共有 · 公式 pulid_forward)")

    def offload_main_pipelines_to_cpu(self):
        """
        Phase 3b 実行前に pipe_base / pipe_cnet を CPU へ退避し VRAM を空ける。
        """
        if getattr(self, "_main_pipelines_offloaded", False):
            return

        vram_before = _vram_used_gb()

        if self.pipe_base is not None:
            self.pipe_base.to("cpu")
            logger.info("[PipelineManager] pipe_base を CPU 退避")

        if self.pipe_cnet is not None:
            self.pipe_cnet.to("cpu")
            logger.info("[PipelineManager] pipe_cnet を CPU 退避")

        _flush_vram()
        vram_after = _vram_used_gb()
        freed = vram_before - vram_after
        logger.info(
            f"[PipelineManager] CPU 退避完了: "
            f"{vram_before:.2f} GB → {vram_after:.2f} GB "
            f"(解放: {freed:.2f} GB)"
        )
        self._main_pipelines_offloaded = True

    def reload_main_pipelines_to_gpu(self):
        """Phase 3b 完了後に pipe_base / pipe_cnet を GPU へ戻す。"""
        if not getattr(self, "_main_pipelines_offloaded", False):
            return

        vram_before = _vram_used_gb()

        if self.pipe_base is not None:
            self.pipe_base.to(self.device)
            logger.info("[PipelineManager] pipe_base を GPU 復帰")

        if self.pipe_cnet is not None:
            self.pipe_cnet.to(self.device)
            logger.info("[PipelineManager] pipe_cnet を GPU 復帰")

        if torch.cuda.is_available():
            torch.cuda.synchronize()

        vram_after = _vram_used_gb()
        used = vram_after - vram_before
        logger.info(
            f"[PipelineManager] GPU 復帰完了: "
            f"{vram_before:.2f} GB → {vram_after:.2f} GB "
            f"(使用: {used:.2f} GB)"
        )
        self._main_pipelines_offloaded = False

    def restore_after_fill(self):
        """
        Phase 3b 終了時: メインパイプラインを GPU へ復帰。
        pipe_fill は保持 (次回 lazy 再利用)。
        """
        self.reload_main_pipelines_to_gpu()

    def ensure_fill_pipeline(self):
        """
        FLUX.1-Fill (Nunchaku INT4 可) を VRAM 戦略付きで lazy load。

        1. (config) メインパイプを CPU 退避
        2. Fill をロード
        3. (config) Sequential CPU offload または GPU 常駐
        """
        cfg = _cfg_mod

        if getattr(cfg, "MAIN_PIPELINE_CPU_DURING_FILL", True):
            self.offload_main_pipelines_to_cpu()

        if self.pipe_fill is not None:
            logger.info("[PipelineManager] Fill パイプライン既存 (再利用)")
            return self.pipe_fill

        logger.info("[PipelineManager] FLUX.1-Fill INT4 パイプライン構築中...")
        from diffusers import FluxFillPipeline

        vram_before_load = _vram_used_gb()

        try:
            if self.strategy.is_nunchaku():
                from nunchaku import NunchakuFluxTransformer2dModel

                fill_transformer = NunchakuFluxTransformer2dModel.from_pretrained(
                    "mit-han-lab/svdq-int4-flux.1-fill-dev",
                )
                self.pipe_fill = FluxFillPipeline.from_pretrained(
                    "black-forest-labs/FLUX.1-Fill-dev",
                    transformer=fill_transformer,
                    torch_dtype=self.dtype,
                )
            else:
                self.pipe_fill = FluxFillPipeline.from_pretrained(
                    "black-forest-labs/FLUX.1-Fill-dev",
                    torch_dtype=self.dtype,
                )

            if getattr(cfg, "FILL_USE_CPU_OFFLOAD", True):
                try:
                    self.pipe_fill.enable_sequential_cpu_offload()
                    logger.info("[PipelineManager] Fill に Sequential CPU offload 適用")
                except Exception as e_seq:
                    logger.warning(
                        f"[PipelineManager] Sequential CPU offload 非対応 ({e_seq}) · "
                        "enable_model_cpu_offload を試行"
                    )
                    try:
                        self.pipe_fill.enable_model_cpu_offload()
                        logger.info("[PipelineManager] Fill に model CPU offload 適用")
                    except Exception as e_model:
                        logger.warning(
                            f"[PipelineManager] model CPU offload も失敗 ({e_model}) · GPU 常駐にフォールバック"
                        )
                        self.pipe_fill = self.pipe_fill.to(self.device)
            else:
                self.pipe_fill = self.pipe_fill.to(self.device)
                logger.info("[PipelineManager] Fill を GPU に常駐")

            vram_after_load = _vram_used_gb()
            logger.info(
                f"[PipelineManager] Fill 構築完了: "
                f"{vram_before_load:.2f} GB → {vram_after_load:.2f} GB"
            )

        except Exception as e:
            logger.error(f"[PipelineManager] Fill 構築失敗: {e}")
            if getattr(cfg, "MAIN_PIPELINE_CPU_DURING_FILL", True):
                self.reload_main_pipelines_to_gpu()
            raise

        return self.pipe_fill

    def _wrap_transformer_forward_for_cn(self, force_reset: bool = False):
        """
        transformer.forward を `id_embeddings 自動注入 + Stage 4-B gating 対応版` にラップ。

        Stage 4-B 真実装 (v7.2.6 · 2026-05-05):
            - MethodType でバインド (binder.bind_forward と同じ流儀)
                旧 v7.2.5 の関数直接代入は Nunchaku から無視されていた
            - Nunchaku 公式の start_timestep / end_timestep を kwargs に注入
                自前 sigma gating 計算は不要 (pulid_forward 内蔵機能を活用)

        Stage 3b 設計:
            FluxControlNetPipeline.__call__ は transformer(...) 呼び出し時に
            id_embeddings を渡さないため、ここで自動注入する。

        timestep スケール:
            Hyper-FLUX 8 step: [1000, 955.7, 902.4, 837.1, 755.0, 649.0, 506.8, 305.7]
            Nunchaku の gating: end_timestep < timestep_float のとき OFF
            → end_timestep = 800 で構図決定期 (step 0-2) PuLID OFF · 詳細期 ON

        安全性:
            - 1 回のみ実行 (二重ラップ防止フラグ _cn_forward_wrapped)
            - tf._pulid_id_embeds が attach されてない時は何もしない (PORTRAIT 互換)
            - start_timestep / end_timestep が未設定なら gating なし (既存動作)
        """
        if getattr(self, "_cn_forward_wrapped", False) and not force_reset:
            logger.info("ℹ️ [Stage 3b] forward ラップ済み (skip)")
            return

        tf = self._shared_transformer
        if tf is None:
            logger.warning("⚠️ [Stage 3b] _shared_transformer が None · ラップ skip")
            return

        # binder.bind_forward 済 = pulid_forward が MethodType でバインドされてる
        original_pulid_forward = tf.forward

        def auto_pulid_forward(self_tf, *args, **kwargs):
            """
            id_embeddings 自動注入 + Stage 4-B gating ラッパー。

            ★ MethodType でバインドするため第一引数 self_tf が必要。
               (self_tf = transformer インスタンス = tf)

            Stage 3b: id_embeddings 自動注入 (V1)
            Stage 4-B 真実装: start_timestep / end_timestep 注入 (V3 · v7.2.6)
                - Nunchaku 公式 gating 機構を活用
                - 自前 sigma 計算は廃止
            """
            # ─── A3 動的 weight 制御(RECON-010/011/012 · 既定 OFF) ──────────
            # OFF 門(P5・退行ゼロ): _a3_enabled が False の間は A3 のコードに
            # 一切触れず現行どおり透過する(getattr→False で全 A3 文を skip)。
            # ★ 新規ラッパは被せない。auto_pulid_forward 本体に挿入する。
            if getattr(self_tf, "_a3_enabled", False):
                _a3_h = kwargs.get("hidden_states", args[0] if args else None)
                _a3_ts = kwargs.get("timestep")
                _a3_step = self_tf._a3_ctrl.on_forward(_a3_ts)               # timestep キーで step 同定
                self_tf._a3_ctrl.measure_tier0(
                    getattr(self_tf, "_a3_prev_h", None), _a3_h
                )                                                            # Tier0 ログのみ(補正なし)
                object.__setattr__(self_tf, "_a3_prev_h", _a3_h)
                object.__setattr__(
                    self_tf, "_a3_dyn_weight", self_tf._a3_ctrl.update_fixed(_a3_step)
                )                                                            # M2: 固定 bump
                # M0 probe: forward 呼び出し数 / step / timestep キーを毎回ログ
                _a3_n = getattr(self_tf, "_a3_fwd_count", 0) + 1
                object.__setattr__(self_tf, "_a3_fwd_count", _a3_n)
                logger.info(
                    f"[A3][M0] fwd#{_a3_n} step={_a3_step} "
                    f"ts={getattr(self_tf._a3_ctrl, '_last_ts', None)} "
                    f"w={getattr(self_tf, '_a3_dyn_weight', None)}"
                )

            # PORTRAIT 経路 (id_embeddings 既に渡されてる) → そのまま透過
            if "id_embeddings" in kwargs and kwargs["id_embeddings"] is not None:
                # A3 ON のみ: PORTRAIT の id_weight を動的値で「置換」(加算しない)。
                # OFF 残留の _a3_dyn_weight を漏らさないため _a3_enabled でも門を切る
                # (M1 のバイト一致を担保 · OFF 経路は一切不変)。
                if (getattr(self_tf, "_a3_enabled", False)
                        and getattr(self_tf, "_a3_dyn_weight", None) is not None):
                    kwargs["id_weight"] = self_tf._a3_dyn_weight
                try:
                    return original_pulid_forward(*args, **kwargs)
                except TypeError as _te:
                    if "id_embeddings" in str(_te):
                        logger.error(
                            "❌ [Stage 3b] pulid_forward バインド消失を検知 · "
                            "フォールバック: nc_pulid_forward を直接呼び出し"
                        )
                        from nunchaku.models.pulid.pulid_forward import (
                            pulid_forward as _fallback_fwd,
                        )
                        return _fallback_fwd(self_tf, *args, **kwargs)
                    raise

            # COORDINATE/SITUATION 経路 (CN pipeline 経由) → 自動注入
            if hasattr(self_tf, "_pulid_id_embeds") and self_tf._pulid_id_embeds is not None:
                kwargs["id_embeddings"] = self_tf._pulid_id_embeds
                kwargs.setdefault("id_weight", getattr(self_tf, "_pulid_weight", 1.0))

                # ─── Stage 4-B 真実装: Nunchaku 公式 gating 注入 ──
                if hasattr(self_tf, "_pulid_start_timestep"):
                    kwargs.setdefault("start_timestep", self_tf._pulid_start_timestep)
                if hasattr(self_tf, "_pulid_end_timestep"):
                    kwargs.setdefault("end_timestep", self_tf._pulid_end_timestep)

                # 初回のみログ
                _n_log = getattr(self_tf, "_auto_pulid_inject_count", 0)
                if _n_log < 1:
                    st = kwargs.get("start_timestep", None)
                    et = kwargs.get("end_timestep", None)
                    logger.info(
                        f"🎭 [Stage 3b/4-B] forward ラップ動作: "
                        f"id_embeddings 注入 weight={kwargs['id_weight']} "
                        f"start_timestep={st} end_timestep={et}"
                    )
                    object.__setattr__(self_tf, "_auto_pulid_inject_count", _n_log + 1)

            # ─── Stage 4-D-2 NEW: IP-Adapter Plus Face 注入 (2026-05-05 真実装) ──
            # joint_attention_kwargs に ip_adapter_image_embeds を list[tensor] 形式でラップ
            # → Nunchaku の pulid_forward.py L122 が encoder_hid_proj 経由で C++ カーネルに渡す
            #
            # 検証実績:
            #   - super_pulid_forward モンキーパッチで経路確立
            #   - list[tensor] 形式で Diffusers 警告解消
            #   - scale 1.0-2.5 で段階的に顔似度向上 (75% → 80-85%)
            ip_e = getattr(self_tf, "_pulid_ip_embeds", None)
            if ip_e is not None:
                jak = kwargs.get("joint_attention_kwargs", None)
                if jak is None:
                    jak = {}
                else:
                    jak = dict(jak) if jak else {}

                # ★ list[tensor] 形式で注入 (Diffusers 推奨形式)
                if isinstance(ip_e, torch.Tensor):
                    jak["ip_adapter_image_embeds"] = [ip_e]
                elif isinstance(ip_e, list):
                    jak["ip_adapter_image_embeds"] = ip_e

                kwargs["joint_attention_kwargs"] = jak

                # 初回のみログ
                _ip_n_log = getattr(self_tf, "_auto_ip_inject_count", 0)
                if _ip_n_log < 1:
                    shapes = [t.shape for t in jak["ip_adapter_image_embeds"]]
                    logger.info(
                        f"🚀 [Stage 4-D-2] IP-Adapter 注入: "
                        f"joint_attention_kwargs に ip_adapter_image_embeds 追加 "
                        f"shapes={shapes}"
                    )
                    object.__setattr__(self_tf, "_auto_ip_inject_count", _ip_n_log + 1)

            # original_pulid_forward は MethodType でバインド済 = self_tf 自動付与
            try:
                return original_pulid_forward(*args, **kwargs)
            except TypeError as _te:
                if "id_embeddings" in str(_te):
                    logger.error(
                        "❌ [Stage 3b] CN 経路: pulid_forward バインド消失 · "
                        "フォールバック: nc_pulid_forward 直接呼び出し"
                    )
                    from nunchaku.models.pulid.pulid_forward import (
                        pulid_forward as _fallback_fwd,
                    )
                    return _fallback_fwd(self_tf, *args, **kwargs)
                raise

        # ★ MethodType でバインド (binder.bind_forward と同じ流儀)
        tf.forward = MethodType(auto_pulid_forward, tf)

        # ─── Stage 4-B: gating デフォルト値設定 ──
        # 既に attribute が設定されてる場合は上書きしない (orchestrator から事前注入可能)
        # v7.2.6: timestep スケールは 0-1.0 (0-1000 ではない · 2026-05-05 実機検証済)
        # -0.5 で全 step PuLID ON (実質 gating なし · 量産安定性 5/5 確認済)
        if not hasattr(tf, "_pulid_start_timestep"):
            object.__setattr__(tf, "_pulid_start_timestep", None)
        if not hasattr(tf, "_pulid_end_timestep"):
            object.__setattr__(tf, "_pulid_end_timestep", -0.5)
        # ─── Stage 4-D-2 NEW: IP-Adapter attribute 初期化 ──
        if not hasattr(tf, "_pulid_ip_embeds"):
            object.__setattr__(tf, "_pulid_ip_embeds", None)
        self._cn_forward_wrapped = True
        logger.info(
            "✅ [Stage 3b/4-B] transformer.forward ラップ完了 "
            "(MethodType バインド · Nunchaku 公式 timestep gating 対応)"
        )

    def _patch_pipe_base_remove_ip_adapter(self):
        """
        pipe_base.__call__ から ip_adapter 関連 kwargs を除去するモンキーパッチ。

        背景:
            Nunchaku PuLIDFluxPipeline は AIBO が ip_adapter_image=None で渡しても
            内部で prepare_ip_adapter_image_embeds を踏んで ValueError を出す。
            AIBO は IP-Adapter 不使用なので、これらの kwargs を渡さない仕様にする。

        対象 kwargs:
            - ip_adapter_image
            - ip_adapter_image_embeds
            - negative_ip_adapter_image
            - negative_ip_adapter_image_embeds

        安全性:
            - クラスレベルパッチ (1 回のみ実行 · 二重ラップ防止)
            - AIBO の他の経路は影響なし (元の __call__ を保持)

        TODO:
            将来 IP-Adapter 機能を復活させる場合はこのパッチを skip する
            設定オプションを追加する。
        """
        if getattr(self, "_pipe_base_ip_patched", False):
            logger.info("ℹ️ [Stage 3e] pipe_base ip_adapter 除去パッチ済み (skip)")
            return

        if self.pipe_base is None:
            logger.warning("⚠️ [Stage 3e] pipe_base 未構築 · パッチ skip")
            return

        import functools

        pipe_class = self.pipe_base.__class__
        original_call = pipe_class.__call__

        @functools.wraps(original_call)
        def patched_call(pipe_self, *args, **kwargs):
            """ip_adapter 関連 kwargs を全削除して元の __call__ に渡す"""
            removed = []
            for k in list(kwargs.keys()):
                if "ip_adapter" in k.lower():
                    kwargs.pop(k, None)
                    removed.append(k)

            # 初回のみログ
            if removed and not getattr(pipe_self, "_ip_strip_logged", False):
                logger.info(f"🔧 [Stage 3e] pipe_base から ip_adapter kwargs 除去: {removed}")
                pipe_self._ip_strip_logged = True

            return original_call(pipe_self, *args, **kwargs)

        pipe_class.__call__ = patched_call
        self._pipe_base_ip_patched = True
        logger.info("✅ [Stage 3e] pipe_base.__class__.__call__ パッチ適用")

    def _build_bf16(self):
        """A100 80GB · bf16 純正経路 (理想)"""
        logger.info("💎 [bf16 純正経路] 構築開始")

        from diffusers import FluxPipeline

        logger.info(f"  📥 [1/3] FluxPipeline ロード: {self.sys_cfg.base_model_repo}")
        self.pipe_base = FluxPipeline.from_pretrained(
            self.sys_cfg.base_model_repo,
            torch_dtype=self.dtype,
        ).to(self.device)

        self._shared_transformer = self.pipe_base.transformer
        self._shared_vae = self.pipe_base.vae

        # ─── 2. regional_compile (Megatron 二次調査の最適解) ───
        if self.sys_cfg.enable_regional_compile:
            try:
                logger.info("  🔥 [2/3] regional_compile 適用中... (~10 秒)")
                self._shared_transformer.compile_repeated_blocks(
                    fullgraph=True,
                    dynamic=True,
                )
                logger.info("  ✅ regional_compile 完了 (32% 高速化)")
            except Exception as e:
                logger.warning(f"  ⚠️ regional_compile 失敗: {e}")

        # ─── 3. Hyper-FLUX LoRA (Diffusers 標準 API) ───
        if self.sys_cfg.enable_hyper_flux:
            self._inject_hyper_flux_diffusers()
        else:
            logger.info("  ⏭ [3/3] Hyper-FLUX 無効")

        logger.info("✅ [bf16 純正経路] 構築完了")

    def _build_gguf(self):
        """A100 40GB GGUF / T4 16GB GGUF 経路"""
        logger.info("📦 [GGUF 経路] 構築開始")

        from diffusers import FluxPipeline, FluxTransformer2DModel
        from huggingface_hub import HfApi, hf_hub_download

        repo_id = _GGUF_CITY96_REPO
        api = HfApi()
        try:
            remote = set(api.list_repo_files(repo_id, repo_type="model"))
        except Exception as e:
            logger.error(f"❌ HF list_repo_files 失敗 ({repo_id}): {e}")
            raise

        try:
            gguf_name, used_preferred = _resolve_city96_gguf_filename(
                self.sys_cfg.gguf_filename,
                remote,
            )
        except FileNotFoundError as e:
            logger.error(f"❌ {e}")
            raise

        if not used_preferred:
            logger.warning(
                f"  ⚠️ gguf_filename 不在 «{self.sys_cfg.gguf_filename}» → «{gguf_name}» を使用"
            )
        else:
            logger.info(f"  ✅ GGUF 実在確認: {gguf_name}")

        gguf_path = hf_hub_download(repo_id=repo_id, filename=gguf_name)

        try:
            from diffusers import GGUFQuantizationConfig
            quant_cfg = GGUFQuantizationConfig(compute_dtype=self.dtype)
            self._shared_transformer = FluxTransformer2DModel.from_single_file(
                gguf_path,
                quantization_config=quant_cfg,
                torch_dtype=self.dtype,
            )
        except Exception as e:
            logger.error(f"❌ GGUF ロード失敗: {e}")
            raise

        self.pipe_base = FluxPipeline.from_pretrained(
            self.sys_cfg.base_model_repo,
            transformer=self._shared_transformer,
            torch_dtype=self.dtype,
        )

        # CPU offload (T4 や 40GB GGUF で必須)
        if self.strategy.needs_cpu_offload():
            self.pipe_base.enable_model_cpu_offload()
            logger.info("  ⏬ CPU offload 有効化 (VRAM 節約モード)")
        else:
            self.pipe_base.to(self.device)

        self._shared_vae = self.pipe_base.vae

        if self.sys_cfg.enable_hyper_flux:
            self._inject_hyper_flux_diffusers()

        logger.info("✅ [GGUF 経路] 構築完了")

    # ─────────────────────────────────────────────────
    # 4.1.C · Hyper-FLUX LoRA 注入 (環境別)
    # ─────────────────────────────────────────────────

    def _inject_hyper_flux_nunchaku(self):
        """Nunchaku 環境専用 · transformer.update_lora_params() で注入"""
        logger.info(f"  ⚡ [3/4] Hyper-FLUX 8-step LoRA (Nunchaku 専用 API)")

        from huggingface_hub import hf_hub_download

        try:
            hyper_path = hf_hub_download(
                repo_id=self.sys_cfg.hyper_flux_repo,
                filename=self.sys_cfg.hyper_flux_filename,
            )
            _c0_verify_file("hyper_flux", hyper_path)
            self._shared_transformer.update_lora_params(hyper_path)

            # Hyper-FLUX の strength を確実に適用 (ACE++ 撤去後の最終値)
            # Nunchaku の set_lora_strength はグローバル multiplier として全 LoRA に効くため、
            # Hyper のみ load の状態でこの値が effective strength となる
            hyper_strength = float(self.sys_cfg.hyper_flux_weight) if hasattr(self.sys_cfg, 'hyper_flux_weight') and self.sys_cfg.hyper_flux_weight else 1.0
            self._shared_transformer.set_lora_strength(hyper_strength)
            self._hyper_flux_loaded = True
            logger.info(f"✅ Hyper-FLUX loaded · strength={hyper_strength}")
        except C0VerificationError:
            raise
        except Exception as e:
            logger.warning(f"  ⚠️ Hyper-FLUX 注入失敗: {e}")
            logger.warning("     → LoRA なしで続行 · 28 steps 相当に降格")

    # ─────────────────────────────────────────────────
    # 4.1.C-2 · ACE++ LoRA 動的 scale 切替 (v7.4.0 Phase 2 v2 NEW)
    # ─────────────────────────────────────────────────

    def switch_ace_plus_lora_for_stage(
        self,
        stage_mode: str,
        portrait_weight: float = 0.6,
        subject_weight: float = 0.6,
    ) -> None:
        """
        ACE++ Stage 切替 (現在は no-op)

        Nunchaku の update_lora_params() が PuLID 注入後に
        load_state_dict(strict=True) で pulid_ca 不整合により失敗する仕様により、
        ACE++ の動的切替は実装不可能。互換性のためメソッドは残すが実体は何もしない。
        顔似度は PuLID + IP-Adapter (scale=0.6) で担保される。
        """
        logger.debug(
            f"⏭️ switch_ace_plus_lora_for_stage(stage_mode={stage_mode!r}) · "
            f"ACE++ 撤去のため no-op"
        )
        return

    def _inject_hyper_flux_diffusers(self):
        """Diffusers 標準 API · pipe.load_lora_weights()"""
        logger.info(f"  ⚡ Hyper-FLUX 8-step LoRA (Diffusers 標準 API)")

        try:
            self.pipe_base.load_lora_weights(
                self.sys_cfg.hyper_flux_repo,
                weight_name=self.sys_cfg.hyper_flux_filename,
                adapter_name="hyper_flux",
            )
            self.pipe_base.set_adapters(["hyper_flux"], adapter_weights=[self.sys_cfg.hyper_flux_weight])
            self._hyper_flux_loaded = True
            logger.info(f"  ✅ Hyper-FLUX 注入完了 (weight={self.sys_cfg.hyper_flux_weight})")
        except Exception as e:
            logger.warning(f"  ⚠️ Hyper-FLUX 注入失敗: {e}")

    # ─────────────────────────────────────────────────
    # 4.1.D · FBCache 封印 (Nunchaku 環境のみ)
    # ─────────────────────────────────────────────────

    def _seal_fbcache(self):
        """
        FBCache を threshold=0.0 で完全封印。
        PuLID × ControlNet 環境で「のっぺらぼう化」を防ぐ。
        """
        try:
            import nunchaku.caching as nc_caching
            if hasattr(nc_caching, "apply_cache_on_transformer"):
                nc_caching.apply_cache_on_transformer(
                    self._shared_transformer,
                    residual_diff_threshold=self.sys_cfg.fbcache_threshold,  # 0.0
                )
                logger.info(
                    f"  🛡 [4/4] FBCache 封印 (threshold={self.sys_cfg.fbcache_threshold}) "
                    f"- 品質死守モード"
                )
            else:
                logger.info("  ℹ️ FBCache API 利用不可 (バージョン違い) · skip")
        except ImportError:
            logger.info("  ℹ️ nunchaku.caching 未インストール · FBCache スキップ")
        except Exception as e:
            logger.info(f"  ℹ️ FBCache 適用スキップ: {e}")

    # ─────────────────────────────────────────────────
    # 4.1.E · I2I パイプライン構築 (transformer 共有)
    # ─────────────────────────────────────────────────

    def _build_i2i(self):
        """Pass 2 顔リファイン用の Img2Img パイプラインを構築 (transformer を共有)"""
        try:
            from diffusers import FluxImg2ImgPipeline

            self.pipe_i2i = FluxImg2ImgPipeline(
                transformer=self._shared_transformer,
                scheduler=self.pipe_base.scheduler,
                vae=self._shared_vae,
                text_encoder=getattr(self.pipe_base, "text_encoder", None),
                text_encoder_2=getattr(self.pipe_base, "text_encoder_2", None),
                tokenizer=getattr(self.pipe_base, "tokenizer", None),
                tokenizer_2=getattr(self.pipe_base, "tokenizer_2", None),
            )
            logger.info("  ✅ FluxImg2ImgPipeline 構築完了 (transformer 共有)")
        except Exception as e:
            logger.warning(f"  ⚠️ I2I 構築失敗: {e}")
            self.pipe_i2i = None

    # ─────────────────────────────────────────────────
    # 4.1.F · Redux Prior (画像参照)
    # ─────────────────────────────────────────────────

    def _build_redux_prior(self):
        """Redux Prior (画像 → embedding) パイプラインを構築 (オプション)"""
        try:
            from diffusers import FluxPriorReduxPipeline
            from transformers import CLIPTokenizer, T5TokenizerFast

            tokenizer = CLIPTokenizer.from_pretrained(self.sys_cfg.base_model_repo, subfolder="tokenizer")
            tokenizer_2 = T5TokenizerFast.from_pretrained(self.sys_cfg.base_model_repo, subfolder="tokenizer_2")

            self.pipe_prior = FluxPriorReduxPipeline.from_pretrained(
                self.sys_cfg.redux_repo,
                text_encoder=None,
                text_encoder_2=None,
                tokenizer=tokenizer,
                tokenizer_2=tokenizer_2,
                torch_dtype=self.dtype,
            )

            # VRAM 余裕に応じて配置
            if self.strategy.vram_gb >= 22.0:
                self.pipe_prior.to(self.device)
            else:
                self.pipe_prior.enable_model_cpu_offload()

            logger.info("  ✅ Redux Prior 構築完了")
        except Exception as e:
            logger.warning(f"  ⚠️ Redux Prior 構築失敗 (画像参照なしで続行): {e}")
            self.pipe_prior = None

    # ─────────────────────────────────────────────────
    # 4.1.G · VAE 最適化
    # ─────────────────────────────────────────────────

    def _enable_vae_optimizations(self):
        """VAE slicing/tiling で高解像度時の OOM 回避"""
        try:
            self.pipe_base.vae.enable_slicing()
            # ⚠️ tiling は 1024 以下では不要 (オーバーヘッド)
            # 1536+ の高解像度時のみ有効化することを推奨
            # ここでは安全のため有効化 (高解像度生成時に効く)
            self.pipe_base.vae.enable_tiling()
            logger.info("  ✅ VAE slicing/tiling 有効化")
        except Exception as e:
            logger.info(f"  ℹ️ VAE 最適化スキップ: {e}")

    # ─────────────────────────────────────────────────
    # 4.1.H · 公開アクセサ
    # ─────────────────────────────────────────────────

    @property
    def transformer(self):
        return self._shared_transformer

    @property
    def vae(self):
        return self._shared_vae

    def is_ready(self) -> bool:
        return self._initialized and self.pipe_base is not None

    def status(self) -> dict:
        return {
            "initialized": self._initialized,
            "strategy": self.strategy.kind.value,
            "pipe_base": self.pipe_base is not None,
            "pipe_i2i": self.pipe_i2i is not None,
            "pipe_fill": self.pipe_fill is not None,
            "pipe_prior": self.pipe_prior is not None,
            "hyper_flux_loaded": self._hyper_flux_loaded,
            "pipe_base_class": type(self.pipe_base).__name__ if self.pipe_base is not None else None,
            "vram_used_gb": _vram_used_gb(),
        }


# ============================================================================
# 🎨 Section 4.2 · MultiLoRAStack
# ============================================================================

class MultiLoRAStack:
    """
    複数 LoRA の同時保持 + 動的ウェイト調整。

    環境別 API 分岐:
        Nunchaku  → transformer.update_lora_params() (1 個ずつ上書き)
                    ⚠️ 複数同時保持には限界あり (Nunchaku v1.2 でも単一推奨)
        Diffusers → pipe.load_lora_weights(adapter_name="...") + set_adapters()
                    ✅ 複数 LoRA 同時 + 個別 weight 制御可能

    内部状態:
        _entries: list[LoRAEntry]  · ユーザが追加した LoRA の登録簿
        _loaded:  set[str]         · 実際に pipeline にロード済の adapter_name
    """

    def __init__(self, sys_cfg: SystemConfig, pipeline_manager: FluxA100PipelineManager):
        self.sys_cfg = sys_cfg
        self.pm = pipeline_manager
        self.strategy = sys_cfg.strategy

        self._entries: list[LoRAEntry] = []
        self._loaded: set[str] = set()

        # Hyper-FLUX が起動時にロードされていれば登録簿に反映
        if self.pm._hyper_flux_loaded:
            self._loaded.add("hyper_flux")

    # ─────────────────────────────────────────────────
    # 公開 API
    # ─────────────────────────────────────────────────

    def add(self, entry: LoRAEntry) -> bool:
        """LoRA エントリを追加してロード"""
        if len(self._entries) >= self.sys_cfg.max_lora_count:
            logger.warning(f"⚠️ [MultiLoRAStack] 最大数 {self.sys_cfg.max_lora_count} 到達 · 追加不可")
            return False

        if self.strategy.is_nunchaku():
            return self._add_nunchaku(entry)
        else:
            return self._add_diffusers(entry)

    def remove(self, name: str) -> bool:
        """LoRA を削除"""
        if self.strategy.is_nunchaku():
            logger.warning("⚠️ [MultiLoRAStack] Nunchaku 環境では LoRA の個別削除はサポート外")
            logger.warning("   → 全 LoRA を物理 unload する場合は clear() を使用")
            return False
        else:
            return self._remove_diffusers(name)

    def set_weight(self, name: str, weight: float):
        """LoRA の重みを動的変更"""
        for e in self._entries:
            if e.name == name:
                e.weight = weight

        if self.strategy.is_nunchaku():
            try:
                self.pm.transformer.set_lora_strength(weight)
                logger.info(f"  ⚖️ [Nunchaku] {name} weight={weight}")
            except Exception as e:
                logger.warning(f"⚠️ set_lora_strength 失敗: {e}")
        else:
            self._refresh_diffusers_adapters()

    def list_loaded(self) -> list[str]:
        return list(self._loaded)

    def clear(self):
        """全 LoRA を解除"""
        if self.strategy.is_nunchaku():
            try:
                # Nunchaku は update_lora_params(None) で解除可能 (バージョン依存)
                self.pm.transformer.update_lora_params(None)
                logger.info("🧹 [Nunchaku] 全 LoRA 解除")
            except Exception as e:
                logger.warning(f"⚠️ Nunchaku LoRA 解除失敗: {e}")
        else:
            try:
                self.pm.pipe_base.unload_lora_weights()
                logger.info("🧹 [Diffusers] 全 LoRA 解除")
            except Exception as e:
                logger.warning(f"⚠️ Diffusers LoRA 解除失敗: {e}")

        self._entries.clear()
        self._loaded.clear()

    # ─────────────────────────────────────────────────
    # 内部実装: Nunchaku
    # ─────────────────────────────────────────────────

    def _add_nunchaku(self, entry: LoRAEntry) -> bool:
        """Nunchaku 環境では update_lora_params で 1 個ずつ上書き"""
        try:
            from huggingface_hub import hf_hub_download

            if entry.path.startswith("/") or entry.path.startswith("./"):
                # ローカルパス
                path = entry.path
            else:
                # HF Hub repo_id
                path = hf_hub_download(
                    repo_id=entry.path,
                    filename=entry.hf_filename or entry.name,
                )

            self.pm.transformer.update_lora_params(path)
            try:
                self.pm.transformer.set_lora_strength(entry.weight)
            except Exception:
                pass

            self._entries.append(entry)
            self._loaded.add(entry.name)
            logger.info(f"✅ [Nunchaku] LoRA 追加: {entry.name} (weight={entry.weight})")
            logger.warning(
                "⚠️ Nunchaku 環境では複数 LoRA は前のものを上書き · "
                "Hyper-FLUX を再注入したい場合は build() からやり直してください"
            )
            return True
        except Exception as e:
            logger.error(f"❌ [Nunchaku] LoRA 追加失敗: {e}")
            return False

    # ─────────────────────────────────────────────────
    # 内部実装: Diffusers
    # ─────────────────────────────────────────────────

    def _add_diffusers(self, entry: LoRAEntry) -> bool:
        """Diffusers 標準 API · pipe.load_lora_weights(adapter_name=...)"""
        try:
            kwargs = {"adapter_name": entry.name}
            if entry.hf_filename:
                kwargs["weight_name"] = entry.hf_filename

            self.pm.pipe_base.load_lora_weights(entry.path, **kwargs)
            self._entries.append(entry)
            self._loaded.add(entry.name)
            self._refresh_diffusers_adapters()
            logger.info(f"✅ [Diffusers] LoRA 追加: {entry.name} (weight={entry.weight})")
            return True
        except Exception as e:
            logger.error(f"❌ [Diffusers] LoRA 追加失敗: {e}")
            return False

    def _remove_diffusers(self, name: str) -> bool:
        try:
            self.pm.pipe_base.delete_adapters([name])
            self._entries = [e for e in self._entries if e.name != name]
            self._loaded.discard(name)
            self._refresh_diffusers_adapters()
            logger.info(f"🗑 [Diffusers] LoRA 削除: {name}")
            return True
        except Exception as e:
            logger.warning(f"⚠️ [Diffusers] LoRA 削除失敗: {e}")
            return False

    def _refresh_diffusers_adapters(self):
        """有効な adapter のリストと weights を再設定"""
        active = [e for e in self._entries if e.enabled]
        if not active:
            return
        try:
            self.pm.pipe_base.set_adapters(
                [e.name for e in active],
                adapter_weights=[e.weight for e in active],
            )
        except Exception as e:
            logger.warning(f"⚠️ set_adapters 失敗: {e}")


# ============================================================================
# 🚀 Section 4.3 · UpscalerHub
# ============================================================================

class UpscalerHub:
    """
    SUPIR / Real-ESRGAN / ESRGAN 切替型アップスケーラ。

    lazy_init で初回使用時のみモデル DL。
    """

    SUPPORTED_METHODS = ["real-esrgan", "real-esrgan-anime", "esrgan", "supir"]

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self._models: dict[str, Any] = {}

    def upscale(self, image: Image.Image, method: str = "real-esrgan", scale: int = 2) -> Image.Image:
        """画像をアップスケール"""
        if method not in self.SUPPORTED_METHODS:
            logger.warning(f"⚠️ [UpscalerHub] 未対応 method: {method} · そのまま返却")
            return image

        try:
            if method.startswith("real-esrgan"):
                return self._upscale_realesrgan(image, scale, anime=method.endswith("anime"))
            elif method == "esrgan":
                return self._upscale_esrgan(image, scale)
            elif method == "supir":
                return self._upscale_supir(image, scale)
        except Exception as e:
            logger.warning(f"⚠️ [UpscalerHub] {method} 失敗 (元画像を返却): {e}")
            return image

        return image

    # ─── Real-ESRGAN (高速 · 汎用) ───

    def _upscale_realesrgan(self, image: Image.Image, scale: int, anime: bool = False) -> Image.Image:
        key = f"realesrgan_{'anime' if anime else 'photo'}_{scale}x"

        if key not in self._models:
            from realesrgan import RealESRGANer
            from basicsr.archs.rrdbnet_arch import RRDBNet

            if anime:
                model_name = "RealESRGAN_x4plus_anime_6B"
                model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=6, num_grow_ch=32, scale=4)
            else:
                model_name = "RealESRGAN_x4plus"
                model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64, num_block=23, num_grow_ch=32, scale=4)

            self._models[key] = RealESRGANer(
                scale=4,
                model_path=f"https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/{model_name}.pth",
                model=model,
                half=True,
            )
            logger.info(f"✅ [UpscalerHub] Real-ESRGAN ({model_name}) ロード完了")

        import numpy as np
        img_np = np.array(image)
        out, _ = self._models[key].enhance(img_np, outscale=scale)
        return Image.fromarray(out)

    # ─── ESRGAN (古典 · 安定) ───

    def _upscale_esrgan(self, image: Image.Image, scale: int) -> Image.Image:
        # ESRGAN は Real-ESRGAN と同じインターフェースを使う
        return self._upscale_realesrgan(image, scale, anime=False)

    # ─── SUPIR (商用化品質 · 重い) ───

    def _upscale_supir(self, image: Image.Image, scale: int) -> Image.Image:
        # SUPIR は Diffusers 経由で実装 (将来対応 · 現状は Real-ESRGAN にフォールバック)
        logger.warning("⚠️ [UpscalerHub] SUPIR は v7.2 では Real-ESRGAN にフォールバック (将来対応)")
        return self._upscale_realesrgan(image, scale, anime=False)


# ============================================================================
# 📚 Section 4.4 · ReferenceImageDB
# ============================================================================

class ReferenceImageDB:
    """
    参照画像 + メタデータ管理 (キャラ単位)。

    ストレージ:
        outputs_dir / references / <char_name> / *.png
        outputs_dir / references / <char_name> / meta.json
    """

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self.root = sys_cfg.output_dir / "references"
        self.root.mkdir(parents=True, exist_ok=True)

    def list_characters(self) -> list[str]:
        """登録済キャラ一覧"""
        return sorted([p.name for p in self.root.iterdir() if p.is_dir()])

    def add_image(self, char_name: str, image: Image.Image, label: str = "ref") -> Path:
        """参照画像を追加"""
        char_dir = self.root / char_name
        char_dir.mkdir(parents=True, exist_ok=True)

        # 既存ファイル数を見て連番命名
        existing = list(char_dir.glob(f"{label}_*.png"))
        idx = len(existing) + 1
        path = char_dir / f"{label}_{idx:03d}.png"
        image.save(path)
        logger.info(f"📚 [ReferenceImageDB] 追加: {path}")
        return path

    def list_images(self, char_name: str) -> list[Path]:
        char_dir = self.root / char_name
        if not char_dir.exists():
            return []
        return sorted(char_dir.glob("*.png"))

    def load_images(self, char_name: str) -> list[Image.Image]:
        return [Image.open(p) for p in self.list_images(char_name)]


# ============================================================================
# 🧰 Section 4.5 · AssetManager (統合管理)
# ============================================================================

class AssetManager:
    """
    LoRA + Upscaler + Reference の統合管理。
    Section 5 (Orchestrator) と Section 6 (UI) はこのクラスのみ参照すれば良い。
    """

    def __init__(self, sys_cfg: SystemConfig, pipeline_manager: FluxA100PipelineManager):
        self.sys_cfg = sys_cfg
        self.pm = pipeline_manager

        self.lora_stack = MultiLoRAStack(sys_cfg, pipeline_manager)
        self.upscaler = UpscalerHub(sys_cfg)
        self.references = ReferenceImageDB(sys_cfg)

        logger.info("📦 AssetManager 初期化完了 (lora + upscaler + references)")


# ============================================================================
# 🔧 Section 4.6 · スタンドアロン動作確認
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🌌 AIBO v7.2 · Section 4 (Pipeline Manager) 動作確認")
    print("=" * 60)

    sys_cfg = SystemConfig()
    sys_cfg.resolve_strategy()

    print()
    print(f"🔍 戦略: {sys_cfg.strategy.kind.value}")
    print(f"🔍 Hyper-FLUX 有効: {sys_cfg.enable_hyper_flux}")
    print(f"🔍 FBCache threshold: {sys_cfg.fbcache_threshold}")

    # ─── 1. クラス定義確認 (重い初期化はしない) ───
    print()
    print("🧪 クラス定義確認:")
    print(f"  FluxA100PipelineManager: {FluxA100PipelineManager.__name__}")
    print(f"  MultiLoRAStack:          {MultiLoRAStack.__name__}")
    print(f"  UpscalerHub:             {UpscalerHub.__name__}")
    print(f"  ReferenceImageDB:        {ReferenceImageDB.__name__}")
    print(f"  AssetManager:            {AssetManager.__name__}")

    # ─── 2. PipelineManager 初期化 (build() は呼ばない) ───
    print()
    print("🧪 PipelineManager 初期化 (build() は呼ばない):")
    pm = FluxA100PipelineManager(sys_cfg)
    print(f"  is_ready (build前): {pm.is_ready()}")
    print(f"  strategy:           {pm.strategy.kind.value}")
    print(f"  device:             {pm.device}")
    print(f"  dtype:              {pm.dtype}")

    # ─── 3. ReferenceImageDB スタンドアロン確認 ───
    print()
    print("🧪 ReferenceImageDB:")
    refs = ReferenceImageDB(sys_cfg)
    print(f"  root: {refs.root}")
    print(f"  characters: {refs.list_characters()}")

    # ─── 4. UpscalerHub クラス情報 (init は副作用なし) ───
    print()
    print("🧪 UpscalerHub:")
    up = UpscalerHub(sys_cfg)
    print(f"  supported: {up.SUPPORTED_METHODS}")

    print()
    print("⚠️ pm.build() は実行しません (FLUX モデル DL で 5-10 分かかる)")
    print("   実際の動作は Section 7 (main) または手動で:")
    print("     pm.build()")
    print("     status = pm.status()")

    print()
    print("✅ Section 4 動作確認完了")
