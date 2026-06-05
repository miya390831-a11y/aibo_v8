"""
================================================================================
🌌 AIBO CYBER STUDIO v7.2 · Section 3 · Identity Engine (PuLID Heart)
================================================================================

📌 このファイルの責務:
    1. PuLIDExtractor: 顔特徴抽出 (InsightFace + EVA-CLIP + BiSeNet)
       - MockDiT 略奪パターンで ToTheBeginning/PuLID 公式リポを再利用
       - bypass_pre_crop 対応 (LATE SNIPER)
       - Face ID Averaging (ノルム復元型 Mean)
    2. PerceiverAttentionCA: bf16 環境用 dim 橋渡し (3072 ↔ 2048)
    3. AIBOPuLIDAttnProcessor: bf16 環境用注入 Processor
       - FluxAttnProcessor2_0 継承 · double-stream タプル分岐
       - sigma 範囲チェック · block_idx 間引き · Late Activation
    4. NunchakuPuLIDBinder: ⭐ Nunchaku 環境用の本命 ⭐
       - pulid_forward を MethodType でバインド
       - CHRONO SINGULARITY 永続ラッパー (DTGI 動的ガイダンス変調)
       - R14 CA アタッチ (transformer.pulid_ca 設定)
    5. IPAdapterEngine: IP-Adapter Plus (Face) 統合
    6. ControlNetEngine: ControlNet Union Pro 2.0 (controlnet_mode=None)
    7. IdentityEngine: 戦略別の三位一体オーケストラ

依存:
    - 01_config.py (SystemConfig, IdentityConfig, RuntimeStrategy)
    - 02_colab_setup.py (PuLIDOfficialFetcher で sys.path 設定済)
    - torch / diffusers / transformers / huggingface_hub
    - cv2 / numpy / PIL

戦略別動作:
    a100_80gb_bf16   → AIBOPuLIDAttnProcessor + PerceiverAttentionCA
    a100_40gb_nunchaku → NunchakuPuLIDBinder (pulid_forward MethodType)
    a100_40gb_gguf   → AIBOPuLIDAttnProcessor (bf16 と同じ経路)
    t4_gguf_q5       → AIBOPuLIDAttnProcessor + CPU offload

Author: 🥷 CTO くろうど
Date:   2026-05-03
Version: v7.2
================================================================================
"""

from __future__ import annotations

import logging
import os
import sys
from importlib import import_module
from pathlib import Path
from types import MethodType
from typing import Any, Optional

import cv2
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image

# ─── 01_config から型を import ───
_cfg_mod = import_module("01_config")
SystemConfig    = _cfg_mod.SystemConfig
IdentityConfig  = _cfg_mod.IdentityConfig
RuntimeStrategy = _cfg_mod.RuntimeStrategy
StrategyKind    = _cfg_mod.StrategyKind
logger          = _cfg_mod.logger


# ============================================================================
# 🔯 Section 3.1 · PuLIDExtractor (顔特徴抽出 · MockDiT 略奪パターン)
# ============================================================================

class PuLIDExtractor:
    """
    PuLID 顔特徴抽出器。

    MockDiT 略奪パターン:
        ToTheBeginning/PuLID 公式リポを git clone (Section 2 で済) し、
        DummyTransformer を渡すことで「顔抽出機能と pulid_ca モジュール」だけを
        略奪する。これにより InsightFace + EVA-CLIP + BiSeNet の依存パイプライン
        全体を自動セットアップできる。

    出力 shape:
        id_embeds: (1, 32, 2048) (bfloat16)
        uncond_id_embeds: (1, 32, 2048) (bfloat16)

    使い方:
        extractor = PuLIDExtractor(sys_cfg)
        id_emb, uncond_emb = extractor.extract(face_image)
    """

    PULID_DIR = "/content/PuLID"  # Section 2 PuLIDOfficialFetcher の clone 先

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self.device = sys_cfg.strategy.gpu_name and "cuda" or "cpu"
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        self.dtype = torch.bfloat16

        self.pulid_pipeline = None      # 公式 PuLIDPipeline インスタンス
        self.dummy_transformer = None
        self._initialized = False
        self._last_init_error: Optional[str] = None
        # IMPL-005 (RECON-006c 案1): 観測属性を __init__ で初期化。
        # 実行時にしか作られないと未定義参照や前回痕跡残りで観測が汚染されるため。
        self._last_extract_error: Optional[str] = None
        self._last_face_count: Optional[int] = None
        self._init_fail_time: Optional[float] = None
        self._INIT_RETRY_COOLDOWN = 30  # seconds

    # ─── 遅延初期化 ───

    def lazy_init(self) -> bool:
        """初回使用時にロード (起動時間短縮)"""
        if self._initialized:
            return True

        import time as _time
        if self._init_fail_time is not None:
            elapsed = _time.time() - self._init_fail_time
            if elapsed < self._INIT_RETRY_COOLDOWN:
                logger.warning(
                    f"⏳ [PuLIDExtractor] lazy_init cooldown 中 "
                    f"({elapsed:.0f}s/{self._INIT_RETRY_COOLDOWN}s) · "
                    f"前回エラー: {self._last_init_error}"
                )
                return False

        # PuLID 公式リポを sys.path に
        if self.PULID_DIR not in sys.path:
            sys.path.insert(0, self.PULID_DIR)

        # 公式の PuLIDPipeline を import
        try:
            from pulid.pipeline_flux import PuLIDPipeline
        except (ImportError, AttributeError) as e:
            self._last_init_error = f"PuLIDPipeline import 失敗: {e}"
            self._init_fail_time = _time.time()
            logger.error(
                f"❌ [PuLIDExtractor] {self._last_init_error}\n"
                f"   原因候補:\n"
                f"     - numpy 2.x と scipy/insightface の互換性\n"
                f"     - facexlib のバージョン不一致\n"
                f"   解決: Section 2 ColabBootstrap を再実行してください"
            )
            return False

        # MockDiT (公式 PuLIDPipeline を騙すためのダミー)
        class _DummyBlock:
            pass

        class _DummyTransformer:
            """FLUX のブロック数 (double=19, single=38) を偽装"""
            def __init__(self):
                self.transformer_blocks = [_DummyBlock() for _ in range(19)]
                self.single_transformer_blocks = [_DummyBlock() for _ in range(38)]

        self.dummy_transformer = _DummyTransformer()

        logger.info("🚀 [PuLIDExtractor] PuLID 公式パイプライン初期化中 (InsightFace + EVA-CLIP + BiSeNet 自動 DL)...")

        try:
            self.pulid_pipeline = PuLIDPipeline(
                self.dummy_transformer,
                device=self.device,
                weight_dtype=self.dtype,
            )
        except Exception as e:
            self._last_init_error = f"PuLIDPipeline インスタンス化失敗: {e}"
            self._init_fail_time = _time.time()
            logger.error(f"❌ [PuLIDExtractor] {self._last_init_error}")
            return False

        # PuLID v0.9.0 (Identity 優先版) の重みをロード
        logger.info(f"📥 [PuLIDExtractor] PuLID 重みダウンロード: {self.sys_cfg.pulid_repo}/{self.sys_cfg.pulid_filename}")

        try:
            from huggingface_hub import hf_hub_download
            ckpt_path = hf_hub_download(
                repo_id=self.sys_cfg.pulid_repo,
                filename=self.sys_cfg.pulid_filename,
            )
            self.pulid_pipeline.load_pretrain(ckpt_path)
        except Exception as e:
            self._last_init_error = f"重みロード失敗: {e}"
            self._init_fail_time = _time.time()
            logger.error(f"❌ [PuLIDExtractor] {self._last_init_error}")
            return False

        logger.info("✅ [PuLIDExtractor] PuLID v0.9.0 (Identity 優先) 初期化完了")
        self._initialized = True
        return True

    # ─── ID 抽出 (単一 or 複数対応) ───

    @torch.no_grad()
    def extract(
        self,
        face_image,
        bypass_pre_crop: bool = False,
    ) -> tuple[Optional[torch.Tensor], Optional[torch.Tensor]]:
        """単一 or 複数画像から PuLID embedding を抽出。

        複数画像の場合: quality-weighted mean 集約 (Phase A)
        単一画像の場合: 従来動作 (後方互換)

        Args:
            face_image: PIL Image (RGB) or list[PIL Image]
            bypass_pre_crop: 既にクロップ済なら True

        Returns:
            (id_embeds, uncond_id_embeds) · 共に (1, 32, 2048) bfloat16
            失敗時は (None, None)
        """
        if isinstance(face_image, list):
            if len(face_image) == 0:
                return None, None
            if len(face_image) == 1:
                return self._extract_single(face_image[0], bypass_pre_crop=bypass_pre_crop)
            return self._extract_quality_weighted(face_image, bypass_pre_crop=bypass_pre_crop)
        return self._extract_single(face_image, bypass_pre_crop=bypass_pre_crop)

    def _pil_to_bgr(self, pil_img: Image.Image) -> np.ndarray:
        return cv2.cvtColor(np.array(pil_img.convert("RGB")), cv2.COLOR_RGB2BGR)

    @torch.no_grad()
    def _extract_single(
        self,
        face_image: Image.Image,
        bypass_pre_crop: bool = False,
    ) -> tuple[Optional[torch.Tensor], Optional[torch.Tensor]]:
        """
        顔画像から ID Embedding と uncond Embedding を抽出 (単一画像)。
        1st attempt 失敗時に 768px リサイズでリトライする。

        Args:
            face_image: PIL Image (RGB) または np.ndarray (BGR)
            bypass_pre_crop: 既にクロップ済の純度 100% 入力なら True

        Returns:
            (id_embeds, uncond_id_embeds) · 共に (1, 32, 2048) bfloat16
            失敗時は (None, None)
        """
        self._last_extract_error = None

        if not self.lazy_init():
            reason = self._last_init_error or "不明"
            self._last_extract_error = f"PuLID pipeline lazy_init 失敗: {reason}"
            return None, None

        original_pil = face_image if hasattr(face_image, "convert") else None

        try:
            if hasattr(face_image, "convert"):
                face_image = face_image.convert("RGB")
                if not bypass_pre_crop:
                    logger.info("ℹ️ [PuLIDExtractor] pre_crop は v7.2 では非実装 · そのまま PuLID 内部処理に委譲")
                image_bgr = cv2.cvtColor(np.array(face_image), cv2.COLOR_RGB2BGR)
            else:
                image_bgr = face_image

            id_embeds, uncond_embeds = self.pulid_pipeline.get_id_embedding(
                image_bgr,
                cal_uncond=True,
            )

            # RECON-005 FIX-3: None を「✅ 抽出完了 shape=?」と誤報せず正直に警告。
            # 失敗理由を _last_extract_error に残し OBS サマリ(IMPL-004)へ伝える。
            if id_embeds is None:
                self._last_extract_error = "get_id_embedding が None (顔未検出の可能性)"
                logger.warning(f"⚠️ [PuLIDExtractor] {self._last_extract_error}")
            else:
                logger.info(f"✅ [PuLIDExtractor] ID embedding 抽出完了: shape={tuple(id_embeds.shape)}")
            return id_embeds, uncond_embeds

        except Exception as e1:
            logger.warning(f"⚠️ [PuLIDExtractor] 1st attempt 失敗: {e1}")

            if original_pil is not None:
                _RETRY_SIZE = 768
                try:
                    resized = original_pil.copy()
                    resized.thumbnail((_RETRY_SIZE, _RETRY_SIZE), Image.LANCZOS)
                    logger.info(f"🔄 [PuLIDExtractor] リサイズ {original_pil.size}→{resized.size} でリトライ")
                    image_bgr = self._pil_to_bgr(resized)

                    id_embeds, uncond_embeds = self.pulid_pipeline.get_id_embedding(
                        image_bgr,
                        cal_uncond=True,
                    )

                    # RECON-005 FIX-3 (retry path): None を成功と誤報しない
                    if id_embeds is None:
                        self._last_extract_error = "get_id_embedding が None (リサイズ後も顔未検出の可能性)"
                        logger.warning(f"⚠️ [PuLIDExtractor] {self._last_extract_error}")
                    else:
                        logger.info(f"✅ [PuLIDExtractor] リサイズ後リトライ成功: shape={tuple(id_embeds.shape)}")
                    return id_embeds, uncond_embeds

                except Exception as e2:
                    self._last_extract_error = f"1st: {e1} / resize-retry: {e2}"
                    logger.error(f"❌ [PuLIDExtractor] リサイズ後リトライも失敗: {e2}")
                    return None, None

            self._last_extract_error = str(e1)
            logger.error(f"❌ [PuLIDExtractor] 抽出失敗 (ndarray入力 · リトライ不可): {e1}")
            return None, None

    # ─── Quality-Weighted Mean 集約 (Phase A · burstiness 緩和) ───

    def _compute_quality_score(self, image: Image.Image) -> float:
        """参照画像の品質スコア (0-1) · InsightFace ベース"""
        if self.pulid_pipeline is None:
            return 0.5

        face_app = getattr(self.pulid_pipeline, "app", None)
        if face_app is None:
            return 0.5

        img_array = np.array(image.convert("RGB"))
        img_bgr = cv2.cvtColor(img_array, cv2.COLOR_RGB2BGR)

        try:
            faces = face_app.get(img_bgr)
            self._last_face_count = len(faces) if faces else 0
        except Exception as e:
            logger.warning(f"⚠️ [QualityScore] InsightFace 検出失敗: {e}")
            return 0.3

        if not faces:
            return 0.1

        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        x1, y1, x2, y2 = map(int, face.bbox)
        face_crop = img_bgr[max(0, y1):y2, max(0, x1):x2]

        face_area = (x2 - x1) * (y2 - y1)
        image_area = img_array.shape[0] * img_array.shape[1]
        size_score = min(face_area / max(image_area, 1) * 5.0, 1.0)

        sharpness_score = 0.0
        if face_crop.size > 0:
            gray = cv2.cvtColor(face_crop, cv2.COLOR_BGR2GRAY)
            sharpness = cv2.Laplacian(gray, cv2.CV_64F).var()
            sharpness_score = min(sharpness / 200.0, 1.0)

        det_score = float(face.det_score)
        return 0.40 * size_score + 0.35 * sharpness_score + 0.25 * det_score

    @torch.no_grad()
    def _extract_quality_weighted(
        self,
        face_images: list[Image.Image],
        bypass_pre_crop: bool = False,
    ) -> tuple[Optional[torch.Tensor], Optional[torch.Tensor]]:
        """Quality-weighted mean 集約 (Phase A · burstiness 緩和)

        1. 各画像の ID embedding を抽出
        2. InsightFace ベースの品質スコアを計算
        3. softmax(quality / temperature) で重み付き平均
        4. ノルム復元 (v6 SOUL SYNERGY)
        """
        import math

        logger.info(f"🎭 [PuLIDExtractor] {len(face_images)} 枚から Quality-Weighted Mean 集約開始")

        scored: list[dict] = []
        per_image_errors: list[str] = []
        for i, img in enumerate(face_images):
            _id, _u = self._extract_single(img, bypass_pre_crop=bypass_pre_crop)
            if _id is None:
                err_detail = getattr(self, "_last_extract_error", None) or "unknown"
                per_image_errors.append(f"[{i+1}] {err_detail}")
                logger.warning(f"  ⚠️ [{i+1}/{len(face_images)}] 抽出失敗 · スキップ (reason: {err_detail})")
                continue
            quality = self._compute_quality_score(img)
            scored.append({"id": _id, "uncond": _u, "quality": quality})
            logger.info(f"  [{i+1}/{len(face_images)}] quality={quality:.3f}")

        if not scored:
            detail = " / ".join(per_image_errors)
            logger.error(f"❌ [PuLIDExtractor] 有効な参照画像が 0 枚 · 集約不可 (details: {detail})")
            raise RuntimeError(f"有効な参照画像が 0 枚 (quality-weighted 集約) — per-image: {detail}")

        if len(scored) == 1:
            return scored[0]["id"], scored[0]["uncond"]

        qualities = [s["quality"] for s in scored]
        temperature = 0.5
        exp_q = [math.exp(q / temperature) for q in qualities]
        total_exp = sum(exp_q)
        weights = [e / total_exp for e in exp_q]

        final_id = torch.zeros_like(scored[0]["id"])
        for w, s in zip(weights, scored):
            final_id += w * s["id"]

        stacked_id = torch.stack([s["id"] for s in scored], dim=0)
        id_norms = torch.norm(stacked_id, p=2, dim=-1, keepdim=True)
        mean_id_norm = torch.mean(id_norms, dim=0)
        current_id_norm = torch.norm(final_id, p=2, dim=-1, keepdim=True) + 1e-6
        final_id = (final_id / current_id_norm) * mean_id_norm

        uncond_list = [s["uncond"] for s in scored if s["uncond"] is not None]
        final_uncond = None
        if uncond_list:
            final_uncond = torch.zeros_like(uncond_list[0])
            for w, u in zip(weights, uncond_list):
                final_uncond += w * u
            stacked_u = torch.stack(uncond_list, dim=0)
            u_norms = torch.norm(stacked_u, p=2, dim=-1, keepdim=True)
            mean_u_norm = torch.mean(u_norms, dim=0)
            current_u_norm = torch.norm(final_uncond, p=2, dim=-1, keepdim=True) + 1e-6
            final_uncond = (final_uncond / current_u_norm) * mean_u_norm

        logger.info(
            f"🏆 [PuLIDExtractor] Quality-Weighted Mean 集約完了: "
            f"{len(scored)} 枚 (weights={[f'{w:.2f}' for w in weights]})"
        )
        return final_id.to(dtype=self.dtype), final_uncond.to(dtype=self.dtype) if final_uncond is not None else None

    # ─── 複数画像合成 (Norm-Preserved Mean · v6 SOUL SYNERGY · 後方互換) ───

    @torch.no_grad()
    def extract_multi(
        self,
        face_images: list[Image.Image],
        bypass_pre_crop: bool = False,
    ) -> tuple[Optional[torch.Tensor], Optional[torch.Tensor]]:
        """
        複数顔画像から ID embedding を抽出してノルム復元型 Mean で合成。

        v6 SOUL SYNERGY 知見:
            単純 mean では異なる角度のベクトルが相殺してノルムが縮小
            → 「のっぺらぼう化」現象が発生。

            解決策:
                Step 1: mean で方向 (顔形状) を抽出
                Step 2: 各入力のノルム平均を計算
                Step 3: 平均ベクトルを単位化 → 平均ノルムにスケール
            → 32 トークン維持 + Attention 分散ゼロ + 強度 100% 維持

        Args:
            face_images: 1〜3 枚の顔画像リスト

        Returns:
            (averaged_id_embeds, averaged_uncond_embeds)
        """
        valid = [img for img in face_images if img is not None]
        if not valid:
            return None, None

        if len(valid) == 1:
            return self._extract_single(valid[0], bypass_pre_crop=bypass_pre_crop)

        logger.info(f"🎭 [PuLIDExtractor] {len(valid)} 枚から Norm-Preserved Mean 合成開始")

        id_list, uncond_list = [], []
        for i, img in enumerate(valid):
            try:
                _id, _u = self._extract_single(img, bypass_pre_crop=bypass_pre_crop)
                if _id is not None:
                    id_list.append(_id)
                if _u is not None:
                    uncond_list.append(_u)
            except Exception as e:
                logger.warning(f"   ⚠️ [{i+1}/{len(valid)}] 抽出失敗: {e}")

        if not id_list:
            return None, None

        if len(id_list) == 1:
            _u = uncond_list[0] if uncond_list else None
            return id_list[0], _u

        # ─── Norm-Preserved Mean ───
        id_avg     = self._norm_preserved_mean(id_list).to(dtype=self.dtype)
        uncond_avg = self._norm_preserved_mean(uncond_list).to(dtype=self.dtype) if uncond_list else None

        logger.info(
            f"🏆 [PuLIDExtractor] SOUL SYNERGY 合成完了: "
            f"{len(id_list)} 枚 (shape={tuple(id_avg.shape)})"
        )
        return id_avg, uncond_avg

    @staticmethod
    def _norm_preserved_mean(tensors: list[torch.Tensor]) -> torch.Tensor:
        """ノルム復元型 Mean (v6 数学的最適解)"""
        stacked = torch.stack(tensors, dim=0)        # (N, 1, 32, 2048)

        # Step 1: 単純平均で方向抽出
        mean_vec = torch.mean(stacked, dim=0)         # (1, 32, 2048)

        # Step 2: 元のノルム平均
        norms = torch.norm(stacked, p=2, dim=-1, keepdim=True)  # (N, 1, 32, 1)
        mean_norm = torch.mean(norms, dim=0)           # (1, 32, 1)

        # Step 3: 単位化 → 平均ノルムにスケール
        current_norm = torch.norm(mean_vec, p=2, dim=-1, keepdim=True) + 1e-6
        return (mean_vec / current_norm) * mean_norm

    # ─── pulid_ca モジュール群を取得 (注入用) ───

    def get_pulid_ca_modules(self) -> Optional[Any]:
        """transformer.pulid_ca にアタッチする CA モジュール群を返す"""
        if not self._initialized or self.pulid_pipeline is None:
            return None
        return getattr(self.pulid_pipeline, "pulid_ca", None)


# ============================================================================
# 🔧 Section 3.2 · PerceiverAttentionCA (bf16 環境用 dim 橋渡し)
# ============================================================================

class PerceiverAttentionCA(nn.Module):
    """
    PuLID-FLUX 用 Perceiver Cross-Attention モジュール (Diffusers 用)。

    FLUX transformer の hidden_dim (3072) を Q 側に、
    PuLID ID-Encoder の出力 dim (2048) を KV 側に受け、
    顔 ID 情報を latent に注入する。

    ⚠️ Nunchaku 環境では使用しない。
       PuLIDExtractor.get_pulid_ca_modules() で公式 PuLIDPipeline の
       pulid_ca をそのまま使うため、このクラスは bf16 純粋環境専用。

    Reference: balazik/ComfyUI-PuLID-Flux/encoders_flux.py + Megatron 二次調査
    """

    def __init__(
        self,
        *,
        dim: int = 3072,
        kv_dim: int = 2048,
        heads: int = 24,
        dim_head: int = 128,
    ):
        super().__init__()
        self.heads = heads
        self.dim_head = dim_head
        inner_dim = heads * dim_head  # 3072

        self.norm1 = nn.LayerNorm(dim)
        self.norm2 = nn.LayerNorm(kv_dim)

        self.to_q = nn.Linear(dim, inner_dim, bias=False)
        self.to_k = nn.Linear(kv_dim, inner_dim, bias=False)
        self.to_v = nn.Linear(kv_dim, inner_dim, bias=False)
        self.to_out = nn.Linear(inner_dim, dim, bias=False)

    def forward(self, x: torch.Tensor, context: torch.Tensor) -> torch.Tensor:
        """
        Args:
            x: FLUX 画像トークン [B, N, dim=3072]
            context: PuLID ID 埋め込み [B, M, kv_dim=2048] (M=32 or 5)
        Returns:
            残差加算用 [B, N, dim=3072]
        """
        x_norm = self.norm1(x)
        ctx_norm = self.norm2(context)

        q = self.to_q(x_norm)
        k = self.to_k(ctx_norm)
        v = self.to_v(ctx_norm)

        B, N, _ = q.shape
        _, M, _ = k.shape

        q = q.view(B, N, self.heads, self.dim_head).transpose(1, 2)
        k = k.view(B, M, self.heads, self.dim_head).transpose(1, 2)
        v = v.view(B, M, self.heads, self.dim_head).transpose(1, 2)

        # PyTorch 2.0+ Flash Attention
        out = F.scaled_dot_product_attention(q, k, v)
        out = out.transpose(1, 2).reshape(B, N, -1)
        return self.to_out(out)


# ============================================================================
# 🎯 Section 3.3 · AIBOPuLIDAttnProcessor (bf16 環境用)
# ============================================================================

class AIBOPuLIDAttnProcessor:
    """
    Diffusers FluxPipeline 用の PuLID Cross-Attention 注入 Processor。

    bf16 純正環境 (a100_80gb_bf16) のみで使用。
    Nunchaku 環境では NunchakuPuLIDBinder を代わりに使う。

    動作:
        1. 通常の attention (FluxAttnProcessor2_0 相当) を呼ぶ
        2. cross_attention_kwargs に pulid_embeds があれば PuLID CA で残差加算
        3. sigma_start <= sigma <= sigma_end の範囲外ならスキップ
        4. block_idx % interval != 0 ならスキップ
        5. (img_out, txt_out) のうち img 側のみに残差加算

    ⚠️ 実装ノート:
       - FluxAttnProcessor2_0 を継承するのが理想だが Diffusers バージョンに
         よってシグネチャが変わるため、ここでは __call__ を独自実装し
         attn.to_q / to_k / to_v を直接呼ぶ。
       - block_idx は init で受け取り、self に保持する。
    """

    def __init__(
        self,
        pulid_ca: nn.Module,
        block_idx: int,
        is_single: bool = False,
    ):
        self.pulid_ca = pulid_ca
        self.block_idx = block_idx
        self.is_single = is_single

    def __call__(
        self,
        attn,
        hidden_states: torch.Tensor,
        encoder_hidden_states: Optional[torch.Tensor] = None,
        attention_mask: Optional[torch.Tensor] = None,
        image_rotary_emb: Optional[torch.Tensor] = None,
        **kwargs,
    ):
        # ── 1. 通常の Flux attention (FluxAttnProcessor2_0 互換) ──
        # Diffusers の FluxAttnProcessor2_0 が import 可能ならそれを呼ぶ
        try:
            from diffusers.models.attention_processor import FluxAttnProcessor2_0
            base_processor = FluxAttnProcessor2_0()
            res = base_processor(
                attn, hidden_states,
                encoder_hidden_states=encoder_hidden_states,
                attention_mask=attention_mask,
                image_rotary_emb=image_rotary_emb,
            )
        except (ImportError, AttributeError):
            # フォールバック: 古い Diffusers では呼び出し不可 → そのまま hidden_states を返す
            logger.warning("⚠️ [AIBOPuLIDAttnProcessor] FluxAttnProcessor2_0 が見つからない · pulid 未注入")
            return hidden_states

        # ── 2. cross_attention_kwargs から PuLID パラメータ取得 ──
        cak = kwargs.get("cross_attention_kwargs", {}) or {}
        pulid_embeds = cak.get("pulid_embeds", None)
        if pulid_embeds is None or self.pulid_ca is None:
            return res

        # ── 3. sigma 範囲チェック ──
        sigma = cak.get("sigma", 1.0)
        sigma_start = cak.get("pulid_sigma_start", 1.0)
        sigma_end   = cak.get("pulid_sigma_end", 0.0)
        # FLUX 内部の sigma スケール (1.0 → 0.0 で進行) を考慮
        # sigma_start (例 1.0) >= sigma >= sigma_end (例 0.0) の範囲で発火
        if not (sigma_end <= sigma <= sigma_start):
            return res

        # ── 4. block_idx 間引き ──
        interval = cak.get(
            "pulid_double_interval" if not self.is_single else "pulid_single_interval",
            2 if not self.is_single else 4,
        )
        if self.block_idx % interval != 0:
            return res

        # ── 5. 残差加算 ──
        weight = cak.get("pulid_weight", 1.0)

        # FluxAttnProcessor2_0 は (img_out, txt_out) タプルを返す場合と
        # img_out 単体を返す場合がある (single block 等)
        if isinstance(res, tuple) and len(res) == 2:
            img_out, txt_out = res
            try:
                pulid_residual = self.pulid_ca(
                    img_out,
                    pulid_embeds.to(img_out.dtype),
                )
                img_out = img_out + weight * pulid_residual
                return (img_out, txt_out)
            except Exception as e:
                logger.warning(f"⚠️ [AIBOPuLIDAttnProcessor#{self.block_idx}] CA 加算失敗: {e}")
                return res
        else:
            # single block 等の場合
            try:
                img_out = res
                pulid_residual = self.pulid_ca(
                    img_out,
                    pulid_embeds.to(img_out.dtype),
                )
                return img_out + weight * pulid_residual
            except Exception as e:
                logger.warning(f"⚠️ [AIBOPuLIDAttnProcessor#{self.block_idx}] CA 加算失敗: {e}")
                return res



# ============================================================================
# ⚡ Section 3.4 · NunchakuPuLIDBinder (Nunchaku 環境用 · 本命)
# ============================================================================

class NunchakuPuLIDBinder:
    """
    Nunchaku 量子化 transformer に PuLID を注入する本命クラス。

    v6 知見:
        - nunchaku.models.pulid.pulid_forward を MethodType でバインド
        - transformer に pulid_ca / id_embeds / weight 等を直接アタッチ
        - CHRONO SINGULARITY 永続ラッパーで DTGI 動的ガイダンス変調

    使い方:
        binder = NunchakuPuLIDBinder(sys_cfg)
        binder.bind_forward(transformer)
        binder.install_chrono_singularity_wrapper(transformer)
        binder.inject(transformer, id_embeds, uncond_embeds, pulid_ca, weight=0.85)
        try:
            image = pipe(...).images[0]
        finally:
            binder.clear(transformer)
    """

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self._forward_bound = False
        self._wrapper_installed = False
        self._original_time_text_embed_forward = None

    # ─── pulid_forward をバインド ───

    def bind_forward(self, transformer) -> bool:
        """
        nunchaku.models.pulid.pulid_forward を transformer.forward に MethodType でバインド。
        毎回再バインドして wrapper チェーン蓄積・参照消失を防止する。
        """
        try:
            from nunchaku.models.pulid.pulid_forward import pulid_forward as nc_pulid_forward
        except ImportError as e:
            logger.error(f"❌ [NunchakuPuLIDBinder] pulid_forward import 失敗: {e}")
            logger.error(f"   → Nunchaku v0.3.0+ が必要")
            return False

        try:
            transformer.forward = MethodType(nc_pulid_forward, transformer)
            rebind = self._forward_bound
            self._forward_bound = True
            if rebind:
                logger.info("🔄 [NunchakuPuLIDBinder] pulid_forward を再バインド (チェーンリセット)")
            else:
                logger.info("✅ [NunchakuPuLIDBinder] pulid_forward を transformer にバインド完了")
            return True
        except Exception as e:
            logger.error(f"❌ [NunchakuPuLIDBinder] バインド失敗: {e}")
            return False

    # ─── CHRONO SINGULARITY 永続ラッパー (DTGI) ───

    def install_chrono_singularity_wrapper(self, transformer) -> bool:
        """
        time_text_embed.forward を恒久パッチして DTGI 動的ガイダンス変調を有効化。

        v6 R12 知見:
            try-finally で動的着脱は Race Condition リスク
            → 永続ラッパー方式が正解 (一度入れたら解除不要)

        効果:
            後半 50% の denoise で guidance を最大 30% 減衰
            → 「ベレー帽の幻覚」等の hallucination を抑止
            → PuLID (画像 ID) が主導権を握る
        """
        if self._wrapper_installed:
            return True

        if not hasattr(transformer, "time_text_embed"):
            logger.error("❌ [CHRONO SINGULARITY] time_text_embed が存在しない")
            return False

        self._original_time_text_embed_forward = transformer.time_text_embed.forward

        decay_max   = self.sys_cfg.dtgi_decay_max     # 0.30
        decay_start = self.sys_cfg.dtgi_decay_start   # 0.5
        original_fn = self._original_time_text_embed_forward

        def chrono_singularity_wrapper(time_text_embed_self, *args, **kwargs):
            """
            v3 修正版: 位置引数 + キーワード引数 両対応
                Nunchaku pulid_forward は位置引数で呼ぶ:
                    self.time_text_embed(timestep, guidance, pooled_projections)
                Diffusers 内部はキーワード引数で来る場合もある。
            """
            # 引数名変換 (pooled_projections → pooled_projection)
            if "pooled_projections" in kwargs:
                kwargs["pooled_projection"] = kwargs.pop("pooled_projections")

            timestep_val = None
            guidance_val = None

            if len(args) >= 1:
                timestep_val = args[0]
            elif "timestep" in kwargs:
                timestep_val = kwargs["timestep"]

            if len(args) >= 2:
                guidance_val = args[1]
            elif "guidance" in kwargs:
                guidance_val = kwargs["guidance"]

            # DTGI 変調
            if guidance_val is not None and timestep_val is not None:
                try:
                    current_t = (
                        timestep_val.item()
                        if torch.is_tensor(timestep_val)
                        else float(timestep_val)
                    )
                    progress = max(0.0, min(1.0, (1000.0 - current_t) / 1000.0))

                    if progress > decay_start:
                        decay_factor = 1.0 - decay_max * ((progress - decay_start) * 2.0)
                        decay_factor = max(0.5, decay_factor)
                        guidance_modulated = guidance_val * decay_factor

                        if len(args) >= 2:
                            args = (args[0], guidance_modulated) + args[2:]
                        else:
                            kwargs["guidance"] = guidance_modulated
                except Exception:
                    pass

            return original_fn(*args, **kwargs)

        transformer.time_text_embed.forward = MethodType(
            chrono_singularity_wrapper, transformer.time_text_embed
        )

        self._wrapper_installed = True
        logger.info(
            f"✅ [CHRONO SINGULARITY] 永続ラッパー適用完了 "
            f"(DTGI: max_decay={decay_max:.2f}, start={decay_start:.2f})"
        )
        return True

    # ─── PuLID 属性 + CA を transformer にアタッチ (R14) ───

    def inject(
        self,
        transformer,
        id_embeds: torch.Tensor,
        uncond_embeds: Optional[torch.Tensor],
        pulid_ca,
        weight: float = 0.85,
    ) -> bool:
        """
        R14: transformer.pulid_ca + 各種属性をアタッチ。
        pulid_forward が self.pulid_ca[idx] でアクセスするため必須。

        Args:
            transformer: Nunchaku 量子化済 transformer
            id_embeds: PuLIDExtractor で抽出した ID embedding (1, 32, 2048)
            uncond_embeds: uncond embedding
            pulid_ca: PuLIDExtractor.get_pulid_ca_modules() の戻り値
            weight: PuLID 強度 (Nunchaku 環境では 0.85 推奨)
        """
        # 念のため事前 clear
        self.clear(transformer)

        # ─── Step 0: PuLID 属性 ───
        transformer._pulid_id_embeds = id_embeds
        transformer._pulid_uncond_embeds = uncond_embeds
        transformer._pulid_weight = weight
        transformer._pulid_txt_len = 512  # Diffusers FLUX のデフォルト
        transformer._pulid_debug_count = 0
        transformer._pulid_force_trace_count = 0

        # ─── R14: pulid_ca アタッチ ───
        if pulid_ca is None:
            logger.error("❌ [NunchakuPuLIDBinder] pulid_ca が None · 注入は 0 回のまま")
            return False

        # device / dtype を transformer に合わせる
        try:
            target_device = next(transformer.parameters()).device
            target_dtype  = next(transformer.parameters()).dtype
            for ca in pulid_ca:
                ca.to(device=target_device, dtype=target_dtype)
        except Exception as e:
            logger.warning(f"⚠️ [NunchakuPuLIDBinder] CA device/dtype 変換失敗: {e}")

        transformer.pulid_ca = pulid_ca

        # ─── 注入 interval (Nunchaku v0.3.0+ デフォルト) ───
        if not hasattr(transformer, "pulid_double_interval"):
            transformer.pulid_double_interval = 2
        if not hasattr(transformer, "pulid_single_interval"):
            transformer.pulid_single_interval = 4

        ca_count = len(pulid_ca) if hasattr(pulid_ca, "__len__") else 0
        logger.info(
            f"💉 [NunchakuPuLIDBinder] 注入完了 "
            f"(CA={ca_count} 個 · weight={weight} · double_int={transformer.pulid_double_interval})"
        )
        return True

    # ─── クリーンアップ ───

    def clear(self, transformer):
        """推論完了後、PuLID 属性 + CA を完全解放 (心霊現象防止)"""
        for attr in (
            "_pulid_id_embeds",
            "_pulid_uncond_embeds",
            "_pulid_weight",
            "_pulid_txt_len",
            "_pulid_debug_count",
            "_pulid_force_trace_count",
            "pulid_ca",
            "pulid_double_interval",
            "pulid_single_interval",
        ):
            if hasattr(transformer, attr):
                try:
                    delattr(transformer, attr)
                except Exception:
                    try:
                        setattr(transformer, attr, None)
                    except Exception:
                        pass

        if torch.cuda.is_available():
            torch.cuda.empty_cache()


# ============================================================================
# 🎨 Section 3.5 · IPAdapterEngine
# ============================================================================

class IPAdapterEngine:
    """
    IP-Adapter Plus (Face) — Nunchaku pulid_forward と並列動作。

    完全分離アーキテクチャ (Stage 4-D-1 · 2026-05-05):
        - CLIP image_encoder を内部で独立保持
        - Diffusers の load_ip_adapter は image_encoder_folder=None で
          重みのみ注入 (Diffusers がフォルダ検索を諦める)
        - encoder_hid_proj が _DummyEncoderHidProj から
          MultiIPAdapterImageProjection に自動上書きされる (Diffusers の挙動)
        - Stage 3e パッチは触らない (互換性維持)

    Hit & Run 戦略:
        encode_face で抽出した後、image_encoder を CPU 退避することで
        生成中の VRAM 増加を最小化 (~300 MB のみ)

    PuLID と協調動作:
        PuLID = transformer 内 CA で注入 (顔の幾何学的構造)
        IP-Adapter = encoder_hid_proj 経由 (肌質感・実写感)
        両者は直交的に協調 (V4/シンク先生監修)
    """

    DEFAULT_IMAGE_ENCODER = "openai/clip-vit-large-patch14"

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self._loaded = False
        self._image_encoder = None
        self._feature_extractor = None

    def lazy_init(self, pipeline) -> bool:
        """
        初回使用時に image_encoder + IP-Adapter 重みをロード。

        手順:
            1. CLIPVisionModelWithProjection を独立ロード (1.7 GB)
            2. CLIPImageProcessor をロード
            3. pipeline.image_encoder / feature_extractor にセット
               (Diffusers の load_ip_adapter が参照するため)
            4. pipeline.load_ip_adapter で重みのみ注入
               (image_encoder_folder=None で Diffusers のフォルダ検索を回避)

        Returns:
            True: ロード成功
            False: ロード失敗 (warning のみ · raise しない)
        """
        if self._loaded:
            return True

        if not self.sys_cfg.enable_ip_adapter:
            logger.info("ℹ️ [IPAdapterEngine] enable_ip_adapter=False · skip")
            return False

        try:
            from transformers import CLIPVisionModelWithProjection, CLIPImageProcessor

            # ─── Step 1: CLIP image_encoder 独立ロード ──
            logger.info(f"🔄 [IPAdapterEngine] {self.DEFAULT_IMAGE_ENCODER} ロード中...")
            self._image_encoder = CLIPVisionModelWithProjection.from_pretrained(
                self.DEFAULT_IMAGE_ENCODER,
                torch_dtype=torch.bfloat16,
            ).to("cuda")

            self._feature_extractor = CLIPImageProcessor.from_pretrained(
                self.DEFAULT_IMAGE_ENCODER,
            )

            # ─── Step 2: pipeline に一時セット (Diffusers が要求) ──
            # 注: load_ip_adapter 中のみ参照される · 後で Hit & Run で CPU 退避
            pipeline.image_encoder = self._image_encoder
            pipeline.feature_extractor = self._feature_extractor

            # ─── Step 3: IP-Adapter 重みのみ注入 ──
            # image_encoder_folder=None で Diffusers のフォルダ検索を諦めさせる
            logger.info(f"🔄 [IPAdapterEngine] IP-Adapter 重みロード中...")
            pipeline.load_ip_adapter(
                self.sys_cfg.ip_adapter_repo,
                weight_name="ip_adapter.safetensors",
                image_encoder_folder=None,
            )

            # ─── Step 4: 注入結果の検証 ──
            transformer = getattr(pipeline, "transformer", None)
            hid_proj = getattr(transformer, "encoder_hid_proj", None) if transformer else None
            num_adapters = getattr(hid_proj, "num_ip_adapters", 0) if hid_proj else 0

            if num_adapters > 0:
                logger.info(
                    f"✅ [IPAdapterEngine] 注入完了 "
                    f"(repo={self.sys_cfg.ip_adapter_repo} · "
                    f"num_ip_adapters={num_adapters} · "
                    f"hid_proj={type(hid_proj).__name__})"
                )
                self._loaded = True
                return True
            else:
                logger.warning(
                    f"⚠️ [IPAdapterEngine] load_ip_adapter は実行したが "
                    f"num_ip_adapters=0 のまま · 反映失敗"
                )
                return False

        except Exception as e:
            logger.warning(f"⚠️ [IPAdapterEngine] ロード失敗 (IP-Adapter なしで続行): {e}")
            return False

    def initialize(self, pipeline) -> bool:
        """
        lazy_init のエイリアス (後方互換性 · AIBO の暗黙的呼び出し対応).

        AIBO 内部で engine.initialize() を呼んでいる箇所がある
        (grep で見つからないが実機警告で確認済)。
        このエイリアスでサイレントクラッシュを防ぐ.
        """
        return self.lazy_init(pipeline)

    def set_scale(self, pipeline, scale: float):
        """IP-Adapter scale を動的設定"""
        if not self._loaded:
            return
        try:
            pipeline.set_ip_adapter_scale(scale)
            logger.info(f"⚖️ [IPAdapterEngine] scale={scale}")
        except Exception as e:
            logger.warning(f"⚠️ [IPAdapterEngine] scale 設定失敗: {e}")

    def encode_face(self, face_ref) -> Optional[torch.Tensor]:
        """
        顔参照画像 → CLIP image_embeds (事前エンコード).

        Stage 4-D-2 で IdentityEngine.prepare から呼ばれる予定。
        Stage 4-D-1 では未使用 (動作確認用のみ).

        Args:
            face_ref: PIL.Image.Image (顔参照画像)

        Returns:
            torch.Tensor of shape [1, 1, 768] dtype=bfloat16 device=cuda
            または None (未初期化時)

        Hit & Run 戦略:
            抽出後 image_encoder を CPU 退避するオプション (Stage 4-D-2 で実装)
        """
        if not self._loaded or self._image_encoder is None:
            logger.warning("⚠️ [IPAdapterEngine] encode_face: 未初期化 · None を返す")
            return None

        try:
            # CPU に退避してたら GPU に戻す
            if self._image_encoder.device.type == "cpu":
                self._image_encoder.to("cuda")

            inputs = self._feature_extractor(
                images=face_ref,
                return_tensors="pt",
            ).to("cuda")

            with torch.no_grad():
                image_embeds = self._image_encoder(
                    inputs.pixel_values.to(torch.bfloat16)
                ).image_embeds

            if image_embeds.ndim == 2:
                image_embeds = image_embeds.unsqueeze(0)

            logger.debug(f"🖼️ [IPAdapterEngine] encode_face: {image_embeds.shape}")
            return image_embeds

        except Exception as e:
            logger.warning(f"⚠️ [IPAdapterEngine] encode_face 失敗: {e}")
            return None

    def offload_image_encoder(self):
        """
        Hit & Run 戦略: image_encoder を CPU に退避してメモリ解放.

        Stage 4-D-2 で生成パス完了後に呼ぶ予定。
        VRAM 600 MB 程度の解放が期待できる。
        """
        if self._image_encoder is None:
            return
        try:
            self._image_encoder.to("cpu")
            torch.cuda.empty_cache()
            logger.debug("🏃 [IPAdapterEngine] image_encoder CPU 退避完了")
        except Exception as e:
            logger.warning(f"⚠️ [IPAdapterEngine] CPU 退避失敗: {e}")

    @property
    def is_loaded(self) -> bool:
        """IP-Adapter ロード済みかどうか"""
        return self._loaded


# ============================================================================
# 🎯 Section 3.6 · ControlNetEngine
# ============================================================================

class ControlNetEngine:
    """
    ControlNet Union Pro 2.0 統合。

    ⚠️ Pro 2.0 の重要変更:
        - mode embedding が削除されている
        - 推論時は controlnet_mode=None で呼ぶ
        - tile / blur / low_quality モードは削除済
        - 代わりに soft_edge (HED) が追加

    対応モード:
        canny / depth / pose / soft_edge / gray
    """

    SUPPORTED_TYPES = ["pose", "canny", "depth", "soft_edge", "gray"]

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self.controlnet = None
        self._initialized = False

    def lazy_init(self) -> bool:
        if self._initialized:
            return True

        if not self.sys_cfg.enable_controlnet:
            logger.info("ℹ️ [ControlNetEngine] enable_controlnet=False · skip")
            return False

        try:
            from diffusers import FluxControlNetModel
            self.controlnet = FluxControlNetModel.from_pretrained(
                self.sys_cfg.controlnet_repo,
                torch_dtype=torch.bfloat16,
            ).to("cuda" if torch.cuda.is_available() else "cpu")
            logger.info(f"✅ [ControlNetEngine] {self.sys_cfg.controlnet_repo} ロード完了")
            self._initialized = True
            return True
        except Exception as e:
            logger.error(f"❌ [ControlNetEngine] ロード失敗: {e}")
            return False

    def preprocess(self, image: Image.Image, ctrl_type: str) -> Image.Image:
        """ControlNet 入力前処理 (controlnet-aux 使用)"""
        if ctrl_type not in self.SUPPORTED_TYPES:
            raise ValueError(f"Unsupported controlnet type: {ctrl_type}")

        try:
            if ctrl_type == "pose":
                from controlnet_aux import OpenposeDetector
                detector = OpenposeDetector.from_pretrained("lllyasviel/Annotators")
                processed = detector(image)
            elif ctrl_type == "canny":
                from controlnet_aux import CannyDetector
                detector = CannyDetector()
                processed = detector(image)
            elif ctrl_type == "depth":
                from controlnet_aux import MidasDetector
                detector = MidasDetector.from_pretrained("lllyasviel/Annotators")
                processed = detector(image)
            elif ctrl_type == "soft_edge":
                from controlnet_aux import HEDdetector
                detector = HEDdetector.from_pretrained("lllyasviel/Annotators")
                processed = detector(image)
            elif ctrl_type == "gray":
                processed = image.convert("L").convert("RGB")
            else:
                processed = image

            logger.info(f"🎯 [ControlNetEngine] {ctrl_type} 前処理完了")
            return processed
        except Exception as e:
            logger.warning(f"⚠️ [ControlNetEngine] {ctrl_type} 前処理失敗 (元画像で続行): {e}")
            return image


# ============================================================================
# 🎭 Section 3.7 · PoseExtractor / DepthExtractor (Stage 3a)
# ============================================================================

class PoseExtractor:
    """
    OpenposeDetector で骨格抽出 (controlnet_aux 経由)。

    ⚠️ ライセンス戦略 (docs/Patch_C_Stage_3_Implementation_Design_v2.md セクション 15 参照):
        - 開発期 (現状): OpenposeDetector (lllyasviel/Annotators · CMU 非商用)
        - 商用化前: DWPose 再検証
            - easy-dwpose は依存衝突 (numpy<2.0, onnxruntime-gpu==1.16.2 固定) で install 不可
            - controlnet_aux の DWPose 実装は MMLab (mmcv/mmpose/mmdet) 必須で重すぎる
            - 商用化前に easy-dwpose --no-deps での検証 or 自前 ONNX 実装を検討

    使用パターン:
        from controlnet_aux import OpenposeDetector
        detector = OpenposeDetector.from_pretrained("lllyasviel/Annotators")
        skeleton = detector(
            image,
            detect_resolution=512,
            include_body=True,
            include_hand=True,
            include_face=True,
        )
    """

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self.detector = None  # lazy_init
        self._initialized = False
        # ── Stage 4-A: Face KP マスク制御 ──
        self.mask_face_keypoints = True   # デフォルト ON
        self._face_app = None             # InsightFace FaceAnalysis 参照 (PuLID pipeline から借用)

    def lazy_init(self) -> bool:
        """初回呼び出し時に OpenposeDetector をロード"""
        if self._initialized:
            return True

        try:
            from controlnet_aux import OpenposeDetector
            logger.info("🦴 [PoseExtractor] OpenposeDetector ロード中...")
            self.detector = OpenposeDetector.from_pretrained("lllyasviel/Annotators")
            self._initialized = True
            logger.info("✅ [PoseExtractor] OpenposeDetector 初期化完了 (lllyasviel/Annotators)")
            return True
        except ImportError as e:
            logger.error(
                f"❌ [PoseExtractor] controlnet_aux 未インストール: {e}\n"
                f"   解決: !pip install controlnet_aux (通常は AIBO に既存)"
            )
            return False
        except Exception as e:
            logger.error(f"❌ [PoseExtractor] 初期化失敗: {e}")
            return False

    def set_face_app(self, face_app):
        """
        InsightFace FaceAnalysis インスタンスを注入。
        通常は IdentityEngine.prepare() 内で
        PuLIDExtractor の pulid_pipeline.app を渡される。
        VRAM 共有のため独自の InsightFace は持たない設計。
        """
        self._face_app = face_app

    def _mask_face_keypoints(
        self,
        skeleton: Image.Image,
        original_image: Image.Image,
    ) -> Image.Image:
        """
        Stage 4-A: InsightFace bbox + 楕円マスクで顔 KP を除去。

        効果:
        - skeleton 画像から顔エリア (目・鼻・耳・輪郭の 70+ 点) を一括黒塗り
        - 体・腕・脚の骨格線は維持
        - CN-Pose は「首から下の体構造」だけを拘束、顔向きは PuLID + プロンプトに委ねる

        Args:
            skeleton: OpenposeDetector が出力した骨格画像 (RGB PIL)
            original_image: 顔検出のための元画像 (RGB PIL)

        Returns:
            楕円マスク済み skeleton (失敗時はそのまま返す)

        注:
            self._face_app が None の場合 (set_face_app 未呼び出し) は
            マスクをスキップして元の skeleton を返す (後方互換)。
        """
        if self._face_app is None:
            logger.debug("  [Face KP Mask] face_app 未注入 · マスクスキップ")
            return skeleton

        try:
            img_np = np.array(original_image.convert("RGB"))
            img_bgr = cv2.cvtColor(img_np, cv2.COLOR_RGB2BGR)

            faces = self._face_app.get(img_bgr)
            if not faces:
                logger.info("  [Face KP Mask] 顔検出なし · マスクスキップ")
                return skeleton

            # 最大の顔を採用 (複数検出時)
            largest = max(
                faces,
                key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])
            )
            x1, y1, x2, y2 = largest.bbox.astype(int)

            # skeleton 画像 numpy
            skel_np = np.array(skeleton)
            h, w = skel_np.shape[:2]
            orig_w, orig_h = original_image.size
            scale_x = w / orig_w
            scale_y = h / orig_h

            # 楕円マスク (1.15x で耳まで含む余裕を確保)
            cx = int((x1 + x2) / 2 * scale_x)
            cy = int((y1 + y2) / 2 * scale_y)
            rx = int((x2 - x1) / 2 * scale_x * 1.15)
            ry = int((y2 - y1) / 2 * scale_y * 1.15)

            cv2.ellipse(skel_np, (cx, cy), (rx, ry), 0, 0, 360, (0, 0, 0), -1)

            logger.info(
                f"  ✅ [Face KP Mask] 楕円マスク適用 "
                f"center=({cx},{cy}) radius=({rx},{ry}) "
                f"face_count={len(faces)}"
            )
            return Image.fromarray(skel_np)

        except Exception as e:
            logger.warning(f"  ⚠️ [Face KP Mask] エラー · マスクスキップ: {e}")
            return skeleton

    def extract(self, image):
        """
        参照画像から骨格スケルトン画像を抽出。

        Args:
            image: 参照画像 (PIL RGB · 全身が写ってると最適)

        Returns:
            PIL skeleton image (失敗時 None)
        """
        if not self.lazy_init():
            return None

        try:
            skeleton = self.detector(
                image,
                detect_resolution=512,
                include_body=True,
                include_hand=True,
                include_face=True,
            )
            # ─── Stage 3e: 強制 RGB 化 (3 channel 化) ──────────────────
            # 背景: FluxControlNetPipeline の VAE エンコードは 3ch 必須
            # OpenposeDetector は通常 RGB だが念のため
            if skeleton is not None and getattr(skeleton, "mode", None) != "RGB":
                original_mode = getattr(skeleton, "mode", "unknown")
                skeleton = skeleton.convert("RGB")
                logger.debug(f"  [PoseExtractor] mode → RGB 変換 (元 mode={original_mode})")

            # ─── Stage 4-A: Face KP 楕円マスク (skeleton から顔エリア除去) ─
            if self.mask_face_keypoints and skeleton is not None:
                skeleton = self._mask_face_keypoints(skeleton, image)

            return skeleton
        except Exception as e:
            logger.error(f"❌ [PoseExtractor] 抽出失敗: {e}")
            return None


class DepthExtractor:
    """
    Depth-Anything-V2 で深度抽出。

    ⚠️ ライセンス戦略 (docs/Patch_C_Stage_3_Implementation_Design.md セクション 15 参照):
        - 'large' (CC-BY-NC): 開発期のみ・商用化前に切替必須
        - 'small' (Apache 2.0): 商用化後の本番運用
        - 'base' (CC-BY-NC): 使わない (Small と Large の中間で半端)

    Transformers pipeline 経由で実装 (追加 install ゼロ)。
    """

    def __init__(self, sys_cfg: SystemConfig, model_size: str = "large"):
        self.sys_cfg = sys_cfg
        self.model_size = model_size  # 'small' / 'base' / 'large'
        self.pipe = None  # lazy_init
        self._initialized = False

        # ライセンス警告
        if model_size in ("base", "large"):
            logger.warning(
                f"⚠️ [DepthExtractor] {model_size} は CC-BY-NC ライセンス · "
                f"商用化前に 'small' (Apache 2.0) に切替必須"
            )

    def lazy_init(self) -> bool:
        """初回呼び出し時に Depth-Anything-V2 pipeline をロード"""
        if self._initialized:
            return True

        try:
            from transformers import pipeline as hf_pipeline

            model_id = (
                f"depth-anything/Depth-Anything-V2-"
                f"{self.model_size.capitalize()}-hf"
            )
            logger.info(f"🌊 [DepthExtractor] {model_id} をロード中...")

            self.pipe = hf_pipeline(
                task="depth-estimation",
                model=model_id,
                device="cuda",
            )
            self._initialized = True
            logger.info(f"✅ [DepthExtractor] {model_id} 初期化完了")
            return True
        except Exception as e:
            logger.error(f"❌ [DepthExtractor] 初期化失敗: {e}")
            return False

    def extract(self, image):
        """
        参照画像から深度マップを抽出。

        Args:
            image: 参照画像 (PIL RGB)

        Returns:
            PIL grayscale depth map (失敗時 None)
        """
        if not self.lazy_init():
            return None

        try:
            result = self.pipe(image)
            depth = result["depth"]  # PIL grayscale Image
            # ─── Stage 3e: 強制 RGB 化 (3 channel 化) ──────────────────
            # 背景: Depth-Anything-V2 はデフォルト grayscale (mode='L')
            # FluxControlNetPipeline の VAE エンコードは 3ch 必須
            if depth is not None and getattr(depth, "mode", None) != "RGB":
                original_mode = getattr(depth, "mode", "unknown")
                depth = depth.convert("RGB")
                logger.debug(f"  [DepthExtractor] mode → RGB 変換 (元 mode={original_mode})")
            return depth
        except Exception as e:
            logger.error(f"❌ [DepthExtractor] 抽出失敗: {e}")
            return None


# ============================================================================
# 🌌 Section 3.7 · IdentityEngine (三位一体オーケストラ)
# ============================================================================

class IdentityEngine:
    """
    PuLID + IP-Adapter + ControlNet の三位一体オーケストラ。

    戦略別の注入経路を一本化:
        a100_80gb_bf16   → AIBOPuLIDAttnProcessor (set_attn_processor で適用)
        a100_40gb_nunchaku → NunchakuPuLIDBinder.bind_forward + inject
        a100_40gb_gguf   → AIBOPuLIDAttnProcessor (bf16 と同じ)
        t4_gguf_q5       → AIBOPuLIDAttnProcessor (CPU offload 環境でも動く)
    """

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self.strategy = sys_cfg.resolve_strategy()
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

        # 必須: PuLID 抽出器 (戦略問わず共通)
        self.pulid_extractor: Optional[PuLIDExtractor] = (
            PuLIDExtractor(sys_cfg) if sys_cfg.enable_pulid else None
        )

        # 戦略別: 注入器
        self.nunchaku_binder: Optional[NunchakuPuLIDBinder] = None
        if self.strategy.is_nunchaku() and sys_cfg.enable_pulid:
            self.nunchaku_binder = NunchakuPuLIDBinder(sys_cfg)

        # IP-Adapter / ControlNet
        self.ip_adapter: Optional[IPAdapterEngine] = (
            IPAdapterEngine(sys_cfg) if sys_cfg.enable_ip_adapter else None
        )
        self.controlnet: Optional[ControlNetEngine] = (
            ControlNetEngine(sys_cfg) if sys_cfg.enable_controlnet else None
        )

        # ★ Patch C Stage 3a NEW: Multi-CN 抽出器 (lazy_init)
        # 詳細: docs/Patch_C_Stage_3_Implementation_Design.md セクション 5
        self.pose_extractor = None    # type: PoseExtractor | None
        self.depth_extractor = None   # type: DepthExtractor | None

        logger.info("=" * 60)
        logger.info(f"🌌 IdentityEngine 初期化完了 (strategy={self.strategy.kind.value})")
        logger.info(f"   PuLID:      {'✅' if self.pulid_extractor else '❌'}")
        logger.info(f"   IPAdapter:  {'✅' if self.ip_adapter else '❌'}")
        logger.info(f"   ControlNet: {'✅' if self.controlnet else '❌'}")
        logger.info(f"   注入方式:   {self.strategy.pulid_injection_method()}")
        logger.info("=" * 60)

    # ─── Identity 抽出 (生成前の準備) ───

    def prepare(self, identity_config: IdentityConfig) -> dict:
        """
        IdentityConfig から Identity データを抽出。

        Returns:
            {
                "id_embeds": ...,
                "uncond_embeds": ...,
                "pulid_ca": ...,
                "pulid_weight": ...,
                "ip_image": ...,
                "ip_weight": ...,
                "controlnet_image": ...,
                "controlnet_type": ...,
                "controlnet_weight": ...,
            }
        """
        prepared: dict = {}

        ref_images = identity_config.get_reference_images()
        if not ref_images:
            return prepared
        primary_ref = ref_images[0]

        # ─── PuLID ──
        # multi-ref: quality-weighted mean 集約 (Phase A)
        # single-ref: 従来動作 (後方互換)
        if self.pulid_extractor:
            extract_input = ref_images if len(ref_images) > 1 else primary_ref
            id_emb, uncond_emb = self.pulid_extractor.extract(
                extract_input,
                bypass_pre_crop=False,
            )
            if id_emb is not None:
                prepared["id_embeds"]      = id_emb
                prepared["uncond_embeds"]  = uncond_emb
                prepared["pulid_ca"]       = self.pulid_extractor.get_pulid_ca_modules()
                prepared["pulid_weight"]   = identity_config.resolved_pulid_weight(self.strategy)
                prepared["pulid_sigma_start"] = identity_config.pulid_sigma_start
                prepared["pulid_sigma_end"]   = identity_config.pulid_sigma_end
                prepared["pulid_double_interval"] = identity_config.pulid_double_interval
                prepared["reference_image"] = primary_ref

        # ─── IP-Adapter Plus Face (Stage 4-D-2 真実装 · 2026-05-05) ──
        if self.ip_adapter and self.ip_adapter.is_loaded:
            ip_embeds = self.ip_adapter.encode_face(primary_ref)
            if ip_embeds is not None:
                prepared["ip_image_embeds"] = ip_embeds
                prepared["ip_image"]        = primary_ref
                prepared["ip_weight"]       = identity_config.ip_adapter_weight
                logger.info(
                    f"  🚀 [Stage 4-D-2] IP-Adapter encode_face 完了 "
                    f"(shape={ip_embeds.shape}, weight={identity_config.ip_adapter_weight})"
                )
            else:
                logger.warning("⚠️ [Stage 4-D-2] encode_face が None · IP-Adapter スキップ")
                prepared["ip_image"]  = primary_ref
                prepared["ip_weight"] = identity_config.ip_adapter_weight
        elif self.ip_adapter:
            prepared["ip_image"]  = primary_ref
            prepared["ip_weight"] = identity_config.ip_adapter_weight

        # ─── ControlNet ──
        if self.controlnet:
            prepared["controlnet_image"]  = self.controlnet.preprocess(
                primary_ref,
                identity_config.controlnet_type,
            )
            prepared["controlnet_type"]   = identity_config.controlnet_type
            prepared["controlnet_weight"] = identity_config.controlnet_weight

        # ─── ★ Patch C Stage 3c NEW: Pose 抽出 (アプローチ X) ──
        if identity_config.enable_multi_cn and identity_config.cn_use_pose:
            pose_source = identity_config.pose_reference_image or primary_ref

            if pose_source is not None:
                if self.pose_extractor is None:
                    self.pose_extractor = PoseExtractor(self.sys_cfg)

                # ─── Stage 4-A: PoseExtractor に InsightFace を注入 ──
                # PuLID pipeline の app を借用することで VRAM 共有
                # (独自の InsightFace ロードを避ける)
                if (
                    self.pose_extractor._face_app is None
                    and self.pulid_extractor is not None
                    and self.pulid_extractor.pulid_pipeline is not None
                ):
                    pp_app = getattr(self.pulid_extractor.pulid_pipeline, "app", None)
                    if pp_app is not None:
                        self.pose_extractor.set_face_app(pp_app)
                        logger.debug(
                            "  [Stage 4-A] PoseExtractor に face_app 注入 "
                            "(PuLID pipeline から借用)"
                        )

                pose_img = self.pose_extractor.extract(pose_source)
                if pose_img is not None:
                    prepared["pose_image"] = pose_img
                    source_name = (
                        "pose_reference_image"
                        if identity_config.pose_reference_image is not None
                        else "reference_image"
                    )
                    logger.info(
                        f"  🦴 [Stage 3c] Pose 抽出完了 "
                        f"(from {source_name}, size={pose_img.size})"
                    )
                else:
                    logger.warning("⚠️ [Stage 3c] Pose 抽出失敗 · CN-Pose 無効化")
            else:
                logger.warning(
                    "⚠️ [Stage 3c] Pose 抽出ソースなし "
                    "(reference_image も pose_reference_image も None)"
                )

        # ─── ★ Patch C Stage 3c NEW: Depth 抽出 (アプローチ X) ─
        # 優先順位: depth_reference_image > pose_reference_image > reference_image
        if identity_config.enable_multi_cn and identity_config.cn_use_depth:
            depth_source = (
                identity_config.depth_reference_image
                or identity_config.pose_reference_image
                or primary_ref
            )

            if depth_source is not None:
                if self.depth_extractor is None:
                    self.depth_extractor = DepthExtractor(
                        self.sys_cfg,
                        model_size=identity_config.cn_depth_model_size,
                    )

                depth_img = self.depth_extractor.extract(depth_source)
                if depth_img is not None:
                    prepared["depth_image"] = depth_img
                    if identity_config.depth_reference_image is not None:
                        source_name = "depth_reference_image"
                    elif identity_config.pose_reference_image is not None:
                        source_name = "pose_reference_image"
                    else:
                        source_name = "reference_image"
                    logger.info(
                        f"  🌊 [Stage 3c] Depth 抽出完了 "
                        f"(from {source_name}, size={depth_img.size})"
                    )
                else:
                    logger.warning("⚠️ [Stage 3c] Depth 抽出失敗 · CN-Depth 無効化")

        return prepared

    # ─── 戦略別: pipeline への注入 ───

    def attach_to_pipeline(self, pipe_base, identity_data: dict) -> bool:
        """
        生成直前に pipeline (またはその transformer) へ Identity を注入。

        戦略ごとに動作が異なる:
            Nunchaku + PuLIDFluxPipeline → bind_forward + inject (★ v7.2.1 hotfix)
            Nunchaku + 通常 FluxPipeline → bind_forward + inject
            bf16/GGUF                    → set_attn_processor で AIBOPuLIDAttnProcessor
        """
        if "id_embeds" not in identity_data:
            return False  # PuLID 注入なし · 通常推論

        if self.strategy.is_nunchaku() and self.nunchaku_binder:
            # ─── Nunchaku 経路 (PuLIDFluxPipeline / FluxPipeline 共通) ──
            transformer = pipe_base.transformer
            _obs_bind_ok = self.nunchaku_binder.bind_forward(transformer)
            logger.info(f"[OBS-C] bind_forward returned = {_obs_bind_ok}")
            self.nunchaku_binder.install_chrono_singularity_wrapper(transformer)

            inject_result = self.nunchaku_binder.inject(
                transformer,
                identity_data["id_embeds"],
                identity_data.get("uncond_embeds"),
                identity_data["pulid_ca"],
                weight=identity_data["pulid_weight"],
            )

            # ─── Stage 4-D-2 NEW: IP-Adapter Plus Face 自動 attribute セット (2026-05-06) ──
            # auto_pulid_forward が読む transformer attribute をセット
            # これにより orchestrator.generate() だけで Stage 4-D-2 が踏まれる
            #
            # 検証実績:
            #   - 5 seed 安定性 5/5
            #   - 注入カウンタ 1/1 (PuLID + IP-Adapter 両方)
            #   - 顔似度 75% → 80% (+5%)

            # IP-Adapter 注入用 attribute (Stage 4-D-2)
            if "ip_image_embeds" in identity_data and identity_data["ip_image_embeds"] is not None:
                object.__setattr__(transformer, "_pulid_ip_embeds", identity_data["ip_image_embeds"])
                logger.info(
                    f"  🚀 [Stage 4-D-2] _pulid_ip_embeds attribute セット完了 "
                    f"(shape={identity_data['ip_image_embeds'].shape})"
                )
            else:
                # IP-Adapter 無効時はクリア (前回の値が残らないように)
                object.__setattr__(transformer, "_pulid_ip_embeds", None)

            # PuLID 注入用 attribute (Stage 4-B 互換 · auto_pulid_forward が CN 経路で読む)
            object.__setattr__(transformer, "_pulid_id_embeds", identity_data["id_embeds"])
            object.__setattr__(transformer, "_pulid_weight", identity_data.get("pulid_weight", 1.0))

            # ─── Phase 1 動作確認ログ (v7.4.0 NEW · 2026-05-13) ──
            # ACE++ は LoRA で transformer に Fuse 済 (attribute 不要)
            # PuLID + IP-Adapter + ACE++ の 3 段並列構成
            _phase1_log = getattr(transformer, "_phase1_inject_count", 0)
            if _phase1_log < 1:
                logger.info(
                    f"🚀 [v7.4.0 Phase 1] 3 段並列構成動作中: "
                    f"PuLID weight={identity_data.get('pulid_weight', 1.0)}, "
                    f"IP-Adapter weight={identity_data.get('ip_weight', 0.6)}, "
                    f"ACE++ LoRA scale=0.6 (transformer に Fuse 済)"
                )
                object.__setattr__(transformer, "_phase1_inject_count", _phase1_log + 1)

            return inject_result
        else:
            # ─── bf16 / GGUF 経路 (自前 Processor) ──
            return self._attach_aibo_processor(pipe_base, identity_data)

    def _attach_aibo_processor(self, pipe_base, identity_data: dict) -> bool:
        """bf16 環境用: AIBOPuLIDAttnProcessor を全 attention に差し込み"""
        try:
            transformer = pipe_base.transformer
            pulid_ca = identity_data["pulid_ca"]
            if pulid_ca is None:
                logger.error("❌ [IdentityEngine] pulid_ca が None")
                return False

            attn_processors = {}

            # double blocks
            for i, block in enumerate(transformer.transformer_blocks):
                ca_idx = i % len(pulid_ca) if hasattr(pulid_ca, "__len__") else 0
                proc = AIBOPuLIDAttnProcessor(
                    pulid_ca=pulid_ca[ca_idx] if hasattr(pulid_ca, "__getitem__") else None,
                    block_idx=i,
                    is_single=False,
                )
                attn_processors[f"transformer_blocks.{i}.attn"] = proc

            # single blocks
            for i, block in enumerate(transformer.single_transformer_blocks):
                ca_idx = i % len(pulid_ca) if hasattr(pulid_ca, "__len__") else 0
                proc = AIBOPuLIDAttnProcessor(
                    pulid_ca=pulid_ca[ca_idx] if hasattr(pulid_ca, "__getitem__") else None,
                    block_idx=i,
                    is_single=True,
                )
                attn_processors[f"single_transformer_blocks.{i}.attn"] = proc

            transformer.set_attn_processor(attn_processors)
            logger.info(
                f"✅ [IdentityEngine] AIBOPuLIDAttnProcessor 差し込み完了 "
                f"(double={len(transformer.transformer_blocks)}, "
                f"single={len(transformer.single_transformer_blocks)})"
            )
            return True
        except Exception as e:
            logger.error(f"❌ [IdentityEngine] AIBOPuLIDAttnProcessor 差し込み失敗: {e}")
            return False

    # ─── 推論後のクリーンアップ ───

    def detach_from_pipeline(self, pipe_base):
        """推論完了後の後始末"""
        if self.strategy.is_nunchaku() and self.nunchaku_binder:
            self.nunchaku_binder.clear(pipe_base.transformer)


# ============================================================================
# 🔧 Section 3.8 · スタンドアロン動作確認
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🌌 AIBO v7.2 · Section 3 (Identity Engine) 動作確認")
    print("=" * 60)

    sys_cfg = SystemConfig()
    sys_cfg.resolve_strategy()

    print()
    print(f"🔍 戦略: {sys_cfg.strategy.kind.value}")
    print(f"🔍 PuLID 注入方式: {sys_cfg.strategy.pulid_injection_method()}")

    # ─── 1. クラスのインポート確認のみ (初期化はしない · 重い) ───
    print()
    print("🧪 クラス定義確認:")
    print(f"  PuLIDExtractor:       {PuLIDExtractor.__name__}")
    print(f"  PerceiverAttentionCA: {PerceiverAttentionCA.__name__}")
    print(f"  AIBOPuLIDAttnProcessor: {AIBOPuLIDAttnProcessor.__name__}")
    print(f"  NunchakuPuLIDBinder:  {NunchakuPuLIDBinder.__name__}")
    print(f"  IPAdapterEngine:      {IPAdapterEngine.__name__}")
    print(f"  ControlNetEngine:     {ControlNetEngine.__name__}")
    print(f"  IdentityEngine:       {IdentityEngine.__name__}")

    # ─── 2. PerceiverAttentionCA 形状検証 (軽量) ───
    print()
    print("🧪 PerceiverAttentionCA 形状テスト:")
    ca = PerceiverAttentionCA(dim=3072, kv_dim=2048).to(dtype=torch.bfloat16)
    if torch.cuda.is_available():
        ca = ca.cuda()
        x = torch.randn(1, 256, 3072, dtype=torch.bfloat16, device="cuda")
        ctx = torch.randn(1, 32, 2048, dtype=torch.bfloat16, device="cuda")
    else:
        x = torch.randn(1, 256, 3072, dtype=torch.bfloat16)
        ctx = torch.randn(1, 32, 2048, dtype=torch.bfloat16)
    out = ca(x, ctx)
    expected = (1, 256, 3072)
    print(f"  入力 latent:    {tuple(x.shape)} dtype={x.dtype}")
    print(f"  入力 ID embed:  {tuple(ctx.shape)} dtype={ctx.dtype}")
    print(f"  出力:           {tuple(out.shape)} dtype={out.dtype}")
    print(f"  期待:           {expected}")
    print(f"  ✅ 一致" if tuple(out.shape) == expected else f"  ❌ 不一致")

    # ─── 3. IdentityEngine 初期化 (lazy_init は呼ばない) ───
    print()
    print("🧪 IdentityEngine 初期化:")
    engine = IdentityEngine(sys_cfg)
    print(f"  pulid_extractor: {engine.pulid_extractor is not None}")
    print(f"  nunchaku_binder: {engine.nunchaku_binder is not None}")
    print(f"  ip_adapter:      {engine.ip_adapter is not None}")
    print(f"  controlnet:      {engine.controlnet is not None}")

    print()
    print("⚠️ 完全な動作確認は Section 4 (Pipeline Manager) と組み合わせて行います")
    print("✅ Section 3 動作確認完了")
