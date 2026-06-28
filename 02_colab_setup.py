"""
================================================================================
🌌 AIBO CYBER STUDIO v7.2 · Section 2 · Colab Setup & GDrive Sync
================================================================================

📌 このファイルの責務:
    1. NunchakuInstaller: GitHub Releases Wheel から正規 Nunchaku を install
       (PyPI の偽 nunchaku を排除)
    2. DependencyInstaller: Diffusers / Transformers / 周辺ライブラリ一括 install
    3. PuLIDOfficialFetcher: ToTheBeginning/PuLID 公式リポジトリを git clone
    4. GDriveCheckpointer: 5 分間隔で outputs/ を Drive に rsync 同期
    5. ColabBootstrap: 起動時の一括セットアップ (Drive マウント → DL → 依存 → 確認)

依存:
    - 01_config.py (RuntimeStrategy, SystemConfig)
    - subprocess, threading, importlib.util (標準ライブラリ)

使い方 (Colab セル):
    from importlib import import_module
    cfg_mod = import_module("01_config")
    setup_mod = import_module("02_colab_setup")

    sys_cfg = cfg_mod.SystemConfig()
    bootstrap = setup_mod.ColabBootstrap(sys_cfg)
    bootstrap.run()  # 全自動セットアップ

Author: 🥷 CTO くろうど
Date:   2026-05-03
Version: v7.2
================================================================================
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import threading
import time
from importlib import import_module
from pathlib import Path
from typing import Optional

# 01_config から型 / 設定を import (importlib 経由 = 数字始まりファイル名対応)
_cfg_mod = import_module("01_config")
SystemConfig    = _cfg_mod.SystemConfig
RuntimeStrategy = _cfg_mod.RuntimeStrategy
StrategyKind    = _cfg_mod.StrategyKind
logger          = _cfg_mod.logger


# ============================================================================
# 📦 Section 2.1 · Nunchaku 偽物排除 + 公式 Wheel Install
# ============================================================================

class NunchakuInstaller:
    """
    PyPI の偽 nunchaku を物理削除し、GitHub Releases から正規 Wheel を install。

    Wheel 命名規則 (v6 で実証済):
        v1.2.1: nunchaku-1.2.1+cu{CUDA}torch{TORCH}-{PY}-{PY}-linux_x86_64.whl
                例: nunchaku-1.2.1+cu12.8torch2.10-cp312-cp312-linux_x86_64.whl

        v1.1.0: nunchaku-1.1.0+torch{TORCH}-{PY}-{PY}-linux_x86_64.whl
                (CUDA タグなし · 旧命名規則)

    検証:
        NunchakuFluxTransformer2dModel が import できることを確認。
    """

    NUNCHAKU_ORG = "nunchaku-ai"  # GitHub org (nunchaku-tech はリダイレクトで 404 リスク)
    VERSIONS_TO_TRY = ["1.2.1", "1.1.0"]

    def __init__(self):
        self._py_tag: Optional[str]      = None
        self._torch_mm: Optional[str]    = None  # "2.10"
        self._cuda_dotted: Optional[str] = None  # "12.8"

    # ─── 環境検出 ───

    def _detect_env(self) -> dict:
        py_tag = f"cp{sys.version_info.major}{sys.version_info.minor}"

        try:
            import torch
            torch_full = torch.__version__              # "2.10.0+cu128"
            torch_base = torch_full.split("+")[0]       # "2.10.0"
            torch_mm = ".".join(torch_base.split(".")[:2])  # "2.10"

            cuda_dotted = None
            m = re.search(r"\+cu(\d+)", torch_full)
            if m:
                raw = m.group(1)
                cuda_dotted = f"{raw[:2]}.{raw[2:]}" if len(raw) >= 3 else raw
        except Exception:
            torch_mm = "2.10"
            cuda_dotted = "12.8"

        self._py_tag = py_tag
        self._torch_mm = torch_mm
        self._cuda_dotted = cuda_dotted

        return {"py_tag": py_tag, "torch_mm": torch_mm, "cuda_dotted": cuda_dotted}

    # ─── Wheel URL 候補生成 ───

    def _build_wheel_candidates(self) -> list[str]:
        py = self._py_tag
        tm = self._torch_mm
        cu = self._cuda_dotted or "12.8"

        candidates: list[str] = []

        # v1.2.1: 検出 CUDA + 検出 torch
        v12_base = f"https://github.com/{self.NUNCHAKU_ORG}/nunchaku/releases/download/v1.2.1"
        candidates.append(
            f"{v12_base}/nunchaku-1.2.1+cu{cu}torch{tm}-{py}-{py}-linux_x86_64.whl"
        )

        # v1.2.1: cu12.8 fallback (検出 CUDA が他バージョンの場合)
        if cu != "12.8":
            candidates.append(
                f"{v12_base}/nunchaku-1.2.1+cu12.8torch{tm}-{py}-{py}-linux_x86_64.whl"
            )

        # v1.2.1: torch2.11 fallback (torch2.10 環境でも 2.11 wheel が動く場合)
        if tm == "2.10":
            candidates.append(
                f"{v12_base}/nunchaku-1.2.1+cu12.8torch2.11-{py}-{py}-linux_x86_64.whl"
            )

        # v1.1.0: 旧命名規則 (CUDA タグなし)
        v11_base = f"https://github.com/{self.NUNCHAKU_ORG}/nunchaku/releases/download/v1.1.0"
        candidates.append(
            f"{v11_base}/nunchaku-1.1.0+torch{tm}-{py}-{py}-linux_x86_64.whl"
        )

        # 重複排除 (順序維持)
        return list(dict.fromkeys(candidates))

    # ─── 既存 nunchaku の物理削除 ───

    def _purge_existing(self):
        logger.info("🧹 [Nunchaku] 既存パッケージを削除 (PyPI 偽物 / 旧 ABI 対策)")
        for _ in range(2):  # 2 回叩く (依存関係で残ることがあるため)
            subprocess.run(
                [sys.executable, "-m", "pip", "uninstall", "-y", "nunchaku"],
                capture_output=True, text=True,
            )

    # ─── 検証 ───

    def _verify_install(self) -> tuple[bool, str]:
        """NunchakuFluxTransformer2dModel が import できるか確認"""
        result = subprocess.run(
            [sys.executable, "-c",
             "import nunchaku; "
             "from nunchaku import NunchakuFluxTransformer2dModel; "
             "v = getattr(nunchaku, '__version__', 'unknown'); "
             "print('OK', v, nunchaku.__file__)"],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, (result.stderr or "")[-500:]

    # ─── 前提ツール ───

    def _ensure_build_tools(self):
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q",
             "--upgrade", "numpy>=2", "ninja", "wheel", "setuptools", "packaging"],
            capture_output=True, text=True,
        )

    # ─── メイン処理 ───

    def install(self, *, force: bool = False) -> bool:
        """Nunchaku を install · 既に正規版が入っていれば skip"""

        # 既存検証
        if not force:
            ok, info = self._verify_install()
            if ok:
                logger.info(f"✅ [Nunchaku] 既に正規版 install 済: {info}")
                return True

        # 環境検出
        env = self._detect_env()
        logger.info(f"🔎 [Nunchaku] 環境: Python {env['py_tag']} / Torch {env['torch_mm']} / CUDA {env['cuda_dotted']}")

        # 偽物排除
        self._purge_existing()

        # build tools
        self._ensure_build_tools()

        # Wheel 候補を試す
        candidates = self._build_wheel_candidates()
        logger.info(f"🎯 [Nunchaku] Wheel 候補 {len(candidates)} 個を試行")

        last_err = "(no attempts)"
        for url in candidates:
            wheel_name = url.split("/")[-1]
            logger.info(f"   📥 試行: {wheel_name}")

            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", url],
                capture_output=True, text=True,
            )

            if r.returncode != 0:
                err_tail = (r.stderr or "")[-300:]
                if "404" in err_tail or "Could not find" in err_tail:
                    logger.info(f"   ℹ️ 404 (この Wheel は未提供)")
                else:
                    logger.warning(f"   ⚠️ pip install 失敗: {err_tail.strip()}")
                last_err = err_tail
                continue

            # 検証
            ok, info = self._verify_install()
            if ok:
                logger.info(f"   ✅ Install + 検証 OK: {info}")
                return True

            logger.warning(f"   ⚠️ Install 成功するも import 失敗: {info[-200:]}")
            self._purge_existing()
            last_err = info

        logger.error(f"❌ [Nunchaku] 全 Wheel 候補失敗")
        logger.error(f"   最終エラー: {last_err}")
        logger.error(f"   💡 手動で確認: https://github.com/nunchaku-tech/nunchaku/releases")
        return False


# ============================================================================
# 📦 Section 2.2 · Diffusers + 周辺ライブラリ Install
# ============================================================================

class DependencyInstaller:
    """
    AIBO v7.2 が必要とする全ライブラリを install。
    Colab 環境では多くが pre-installed なので、不足分のみ補う設計。
    """

    # ─── 必須パッケージ (バージョン下限) ───
    # numpy/scipy/sklearn は順序が重要 (numpy を最初に強制更新)
    CORE_PACKAGES = [
        ("numpy",            ">=2.1.0"),  # ⚠️ scipy/insightface 互換 (_center, _blas_supports_fpe)
        ("scipy",            ">=1.13.0"), # ⚠️ numpy 2.x 対応
        ("scikit-learn",     ">=1.5.0"),  # ⚠️ scipy/numpy 連動
        ("diffusers",        ">=0.32"),
        ("transformers",     ">=4.45,<5.0"),  # ⚠️ 5.0+ は diffusers 0.37.x / peft 0.19.x と非互換
        ("accelerate",       ">=1.0"),
        ("peft",             ">=0.13"),
        ("safetensors",      ">=0.4"),
        ("sentencepiece",    None),
        ("gradio",           ">=5.0"),
        ("huggingface_hub",  ">=0.26"),
        ("controlnet-aux",   None),       # ControlNet 前処理
        ("opencv-python-headless", None), # 顔検出用
        ("pillow",            None),
        ("einops",            None),       # PuLID 内部で使用
    ]

    # ─── PuLID 関連 ───
    PULID_PACKAGES = [
        ("insightface",      None),
        ("facexlib",         None),
        ("timm",             None),
        # ★CPU 版固定(2026-06-28): onnxruntime-gpu は環境により libcudart.so.13(CUDA13)要求で
        #   import 不可→FATAL。かつ install_all は非保護パッケージを毎ビルド無条件 pip install するため、
        #   gpu を指定すると [Cell-deps] で入れた CPU 版を毎回上書きして再発させる(GATE① 系の沈黙再発)。
        #   CPU 版を指定 → Cell-deps 導入済なら「already satisfied」で no-op・gpu を一切入れない。
        #   insightface 顔検出は CPU で十分(実証済・944a9b8)。gpu-first は禁止。
        ("onnxruntime",      None),
        ("ftfy",             None),       # ⚠️ PuLIDPipeline 内部で使用 (テキスト正規化)
        ("ultralytics",      None),       # ⚠️ Phase0Sniper の YOLO で使用
    ]

    # ─── アップスケール関連 (オプション) ───
    UPSCALE_PACKAGES = [
        ("realesrgan",       None),
        ("basicsr",          None),
    ]

    # numpy はバージョン不足時のみ install (Colab デフォルトが既に 2.1+ なら触らない)
    # これによって ABI 不整合 → 自動再起動の発火を回避し、1 押下完走を実現
    FORCE_REINSTALL_FIRST = ["scipy", "scikit-learn"]

    # transformers 5.0+ は diffusers 0.37.x / peft 0.19.x と非互換のため pin
    PINNED_VERSIONS = {
        "transformers": ">=4.45,<5.0",
    }

    # ABI 互換性を保護するパッケージ
    # 既存バージョンが要求を満たすなら pip install 自体を skip し、
    # C 拡張 ABI 不整合 → 自動再起動ループを回避する
    PROTECT_IF_SATISFIED = {"numpy", "scipy", "scikit-learn"}

    @staticmethod
    def _get_installed_version(name: str) -> Optional[str]:
        """現在 install 済みのバージョンを返す (未 install なら None)"""
        try:
            import importlib.metadata
            return importlib.metadata.version(name)
        except Exception:
            return None

    @classmethod
    def _version_satisfies(cls, name: str, version_spec: Optional[str]) -> bool:
        """install 済みバージョンが version_spec を満たすか判定"""
        current = cls._get_installed_version(name)
        if current is None:
            return False
        if version_spec is None:
            return True
        try:
            from packaging.specifiers import SpecifierSet
            return SpecifierSet(version_spec).contains(current)
        except Exception:
            return False

    @classmethod
    def _ensure_pinned_versions(cls) -> None:
        """PINNED_VERSIONS を満たさない場合は先に force-reinstall"""
        import importlib.metadata
        from packaging.specifiers import SpecifierSet

        for pkg, version_spec in cls.PINNED_VERSIONS.items():
            try:
                current = importlib.metadata.version(pkg)
                if SpecifierSet(version_spec).contains(current):
                    logger.info(f"✅ {pkg} {current} は範囲内 ({version_spec})")
                    continue
                logger.info(f"📦 {pkg} {current} は範囲外 ({version_spec}) · 再 install")
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", "-q",
                    f"{pkg}{version_spec}",
                    "--force-reinstall", "--no-deps",
                ])
                logger.info(f"✅ {pkg} を {version_spec} に pin 完了")
            except importlib.metadata.PackageNotFoundError:
                logger.info(f"📦 {pkg} 未 install · {version_spec} で install")
                subprocess.check_call([
                    sys.executable, "-m", "pip", "install", "-q",
                    f"{pkg}{version_spec}",
                ])
            except Exception as e:
                logger.warning(f"⚠️ {pkg} pin チェック失敗: {e}")

    @classmethod
    def install_all(cls, *, include_upscale: bool = True) -> dict[str, bool]:
        results = {}
        cls._ensure_pinned_versions()
        all_pkgs = list(cls.CORE_PACKAGES) + list(cls.PULID_PACKAGES)
        if include_upscale:
            all_pkgs += list(cls.UPSCALE_PACKAGES)

        logger.info(f"📦 [Deps] {len(all_pkgs)} パッケージを install 開始")

        # numpy バージョンを事前記録 (他パッケージによる間接変更の検知用)
        _numpy_ver_before = cls._get_installed_version("numpy")

        for name, version_spec in all_pkgs:
            # 保護対象: 既存バージョンが適合なら skip (ABI 不整合回避)
            if name in cls.PROTECT_IF_SATISFIED and cls._version_satisfies(name, version_spec):
                current = cls._get_installed_version(name)
                logger.info(f"   ✅ {name} {current} (既存適合 · skip)")
                results[name] = True
                continue

            spec = f"{name}{version_spec}" if version_spec else name

            extra_flags = []
            if name in cls.FORCE_REINSTALL_FIRST:
                extra_flags = ["--force-reinstall", "--no-deps"]

            r = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q", *extra_flags, spec],
                capture_output=True, text=True,
            )
            success = r.returncode == 0
            results[name] = success
            mark = "✅" if success else "⚠️"
            extra_label = " [force-reinstall]" if extra_flags else ""
            logger.info(f"   {mark} {spec}{extra_label}")
            if not success:
                logger.warning(f"      → {(r.stderr or '')[-150:].strip()}")

        ok_count = sum(1 for v in results.values() if v)
        logger.info(f"📦 [Deps] 完了: {ok_count}/{len(results)} success")

        # numpy 変更検知 (os.kill 自動再起動は廃止 · 警告のみ)
        # PROTECT_IF_SATISFIED により通常は numpy は変更されないが、
        # 他パッケージの依存で間接的に変更される可能性への安全網
        _numpy_ver_after = cls._get_installed_version("numpy")
        if _numpy_ver_before != _numpy_ver_after:
            logger.warning(
                f"⚠️ [Deps] numpy バージョン変更: {_numpy_ver_before} → {_numpy_ver_after}\n"
                f"   C 拡張 ABI 不整合の可能性があります。"
            )
            print("\n" + "=" * 60)
            print(f"⚠️ numpy {_numpy_ver_before} → {_numpy_ver_after}")
            print("   C 拡張 ABI 不整合の可能性があります。")
            print("   問題が発生した場合: ランタイム → ランタイムを再起動")
            print("=" * 60)

        return results


# ============================================================================
# 🔯 Section 2.3 · PuLID 公式リポジトリ Clone
# ============================================================================

class PuLIDOfficialFetcher:
    """
    ToTheBeginning/PuLID 公式リポジトリを git clone し、
    sys.path に追加することで MockDiT 略奪パターンを可能にする。

    v6 知見:
        - 公式リポを丸ごと使うことで InsightFace + EVA-CLIP + BiSeNet の
          依存パイプライン全体を自動セットアップできる
        - DummyTransformer を渡せば「顔抽出機能だけ」を略奪可能
    """

    GIT_URL = "https://github.com/ToTheBeginning/PuLID.git"

    def __init__(self, install_dir: str = "/content/PuLID"):
        self.install_dir = Path(install_dir)

    def fetch(self) -> bool:
        """git clone + sys.path 追加"""

        if self.install_dir.exists() and (self.install_dir / "pulid").exists():
            logger.info(f"✅ [PuLID Fetcher] 既に clone 済: {self.install_dir}")
            self._add_to_syspath()
            return True

        logger.info(f"📦 [PuLID Fetcher] git clone 開始: {self.GIT_URL}")
        try:
            self.install_dir.parent.mkdir(parents=True, exist_ok=True)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", self.GIT_URL, str(self.install_dir)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                logger.error(f"❌ [PuLID Fetcher] clone 失敗: {result.stderr[-300:]}")
                return False
        except Exception as e:
            logger.error(f"❌ [PuLID Fetcher] 例外: {e}")
            return False

        self._add_to_syspath()

        # import テスト (clone 自体は成功扱い · import 失敗は warning に降格)
        try:
            from pulid.pipeline_flux import PuLIDPipeline  # noqa: F401
            logger.info("✅ [PuLID Fetcher] pulid.pipeline_flux import OK")
            return True
        except (ImportError, AttributeError) as e:
            # よくある原因:
            #   - numpy 2.x と scipy/insightface の互換性問題 (_center 等)
            #   - facexlib の version mismatch
            # → clone は成功しているので、ここは warning として継続。
            #   実際の使用時 (Section 3 lazy_init) に再 import を試みる。
            logger.warning(
                f"⚠️ [PuLID Fetcher] import テスト失敗 (clone 自体は成功): {e}\n"
                f"   → Section 3 (Identity Engine) の lazy_init で再試行されます。\n"
                f"   → numpy 互換性が原因の場合は `pip install 'numpy>=2.1.0'` で解決の可能性"
            )
            return True  # ← clone 自体は成功なので True を返す

    def _add_to_syspath(self):
        path_str = str(self.install_dir)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)
            logger.info(f"   ✅ sys.path に追加: {path_str}")


# ============================================================================
# 🔄 Section 2.3b · Drive ↔ NVMe 二段キャッシュ同期
# ============================================================================

class DriveNvmeCacheSync:
    """
    Drive (永続 40-100 MB/s) ↔ /content NVMe (高速 1-2 GB/s) の二段キャッシュ同期。

    rsync は Drive FUSE でハングすることがあるため廃止。
    代替:
        1. tar pipe (timeout 付き)
        2. symlink fallback (コピー不要 · Drive 帯域で妥協)
    """

    def __init__(
        self,
        drive_cache: str,
        nvme_cache: str,
        timeout_sec: int = 180,
    ):
        self.drive_cache = Path(drive_cache)
        self.nvme_cache = Path(nvme_cache)
        self.timeout_sec = timeout_sec

    @staticmethod
    def _du_bytes(path: str) -> int:
        try:
            return int(subprocess.check_output(
                ["du", "-sb", path], stderr=subprocess.DEVNULL
            ).split()[0])
        except Exception:
            return 0

    def needs_sync(self, threshold: float = 0.95) -> bool:
        """NVMe cache が Drive の threshold 未満なら True"""
        drive_size = self._du_bytes(str(self.drive_cache))
        nvme_size = self._du_bytes(str(self.nvme_cache))
        if drive_size == 0:
            return False
        logger.info(
            f"📦 [CacheSync] Drive: {drive_size / 1e9:.1f}GB · "
            f"NVMe: {nvme_size / 1e9:.1f}GB "
            f"({nvme_size / max(drive_size, 1) * 100:.0f}%)"
        )
        return nvme_size < drive_size * threshold

    def sync_to_nvme(self) -> str:
        """Drive → NVMe 同期 (起動時)

        Returns: "tar" | "symlink" | "skip"
        """
        self.drive_cache.mkdir(parents=True, exist_ok=True)
        self.nvme_cache.mkdir(parents=True, exist_ok=True)

        if not self.needs_sync():
            logger.info("✅ [CacheSync] NVMe cache 十分 · sync スキップ")
            return "skip"

        drive_gb = self._du_bytes(str(self.drive_cache)) / 1e9
        logger.info(f"⏳ [CacheSync] Drive → NVMe 同期中 ({drive_gb:.1f}GB, timeout={self.timeout_sec}s)...")
        t0 = time.time()

        # Method 1: tar pipe (timeout 付き)
        try:
            cmd = f'tar cf - -C "{self.drive_cache}" . | tar xf - -C "{self.nvme_cache}"'
            r = subprocess.run(
                ["bash", "-c", cmd],
                capture_output=True, text=True,
                timeout=self.timeout_sec,
            )
            if r.returncode == 0:
                logger.info(f"✅ [CacheSync] tar pipe 完了 ({time.time() - t0:.1f}s)")
                return "tar"
            logger.warning(f"⚠️ [CacheSync] tar pipe 失敗: {(r.stderr or '')[-200:]}")
        except subprocess.TimeoutExpired:
            logger.warning(f"⚠️ [CacheSync] tar pipe timeout ({self.timeout_sec}s)")
        except Exception as e:
            logger.warning(f"⚠️ [CacheSync] tar pipe 例外: {e}")

        # Method 2: symlink fallback (Drive 帯域で妥協)
        logger.info("🔗 [CacheSync] symlink fallback (Drive 直結 · NVMe 高速化なし)")
        try:
            if self.nvme_cache.is_symlink():
                self.nvme_cache.unlink()
            elif self.nvme_cache.exists():
                shutil.rmtree(self.nvme_cache)
            os.symlink(str(self.drive_cache), str(self.nvme_cache))
            logger.info(f"✅ [CacheSync] symlink: {self.nvme_cache} → {self.drive_cache}")
            return "symlink"
        except Exception as e:
            logger.error(f"❌ [CacheSync] symlink fallback も失敗: {e}")
            raise

    def sync_to_drive(self) -> bool:
        """NVMe → Drive 同期 (新規 DL の永続化)"""
        if self.nvme_cache.is_symlink():
            logger.info("ℹ️ [CacheSync] symlink モード · Drive 直結のため sync 不要")
            return True

        logger.info("⏳ [CacheSync] NVMe → Drive 書き戻し中...")
        t0 = time.time()
        try:
            cmd = f'tar cf - -C "{self.nvme_cache}" . | tar xf - -C "{self.drive_cache}"'
            r = subprocess.run(
                ["bash", "-c", cmd],
                capture_output=True, text=True,
                timeout=self.timeout_sec * 2,
            )
            if r.returncode == 0:
                logger.info(f"✅ [CacheSync] Drive 書き戻し完了 ({time.time() - t0:.1f}s)")
                return True
            logger.warning(f"⚠️ [CacheSync] 書き戻し tar 失敗: {(r.stderr or '')[-200:]}")
        except subprocess.TimeoutExpired:
            logger.warning(f"⚠️ [CacheSync] 書き戻し timeout ({self.timeout_sec * 2}s)")
        except Exception as e:
            logger.warning(f"⚠️ [CacheSync] 書き戻し例外: {e}")
        return False


# ============================================================================
# 💾 Section 2.4 · GDrive Checkpointer (5 分間隔同期)
# ============================================================================

class GDriveCheckpointer:
    """
    Colab セッション kill 対策。
    /content/aibo_v7_outputs/ を 5 分間隔で /content/drive/MyDrive/aibo_v7/outputs/ に rsync。

    バックグラウンドスレッドで動作し、停止には .stop() を呼ぶ。
    """

    def __init__(
        self,
        local_dir: Path,
        drive_dir: Path,
        interval_sec: int = 300,
    ):
        self.local_dir = Path(local_dir)
        self.drive_dir = Path(drive_dir)
        self.interval_sec = interval_sec

        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._sync_count = 0
        self._last_sync_at: Optional[float] = None
        self._last_sync_ok: bool = False

    SYNC_TIMEOUT_SEC: int = 120

    # ─── 単発同期 ───

    def sync_once(self) -> bool:
        """1 回の同期を実行 (tar pipe · timeout 付き · rsync 廃止)"""

        if not self.local_dir.exists():
            self.local_dir.mkdir(parents=True, exist_ok=True)

        if not self.drive_dir.exists():
            try:
                self.drive_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                logger.warning(f"⚠️ [GDriveCheckpointer] drive_dir 作成失敗: {e}")
                return False

        ok = False

        # Method 1: tar pipe (rsync 代替 · Drive FUSE ハング回避)
        try:
            cmd = f'tar cf - -C "{self.local_dir}" . | tar xf - -C "{self.drive_dir}"'
            r = subprocess.run(
                ["bash", "-c", cmd],
                capture_output=True, text=True,
                timeout=self.SYNC_TIMEOUT_SEC,
            )
            ok = r.returncode == 0
            if not ok:
                logger.warning(f"⚠️ [GDriveCheckpointer] tar pipe 失敗: {(r.stderr or '')[-200:]}")
        except subprocess.TimeoutExpired:
            logger.warning(
                f"⚠️ [GDriveCheckpointer] tar pipe timeout ({self.SYNC_TIMEOUT_SEC}s) · shutil fallback"
            )
        except Exception as e:
            logger.warning(f"⚠️ [GDriveCheckpointer] tar pipe 例外: {e}")

        # Method 2: shutil fallback
        if not ok:
            try:
                shutil.copytree(self.local_dir, self.drive_dir, dirs_exist_ok=True)
                ok = True
            except Exception as e:
                logger.warning(f"⚠️ [GDriveCheckpointer] shutil fallback 失敗: {e}")
                ok = False

        self._sync_count += 1
        self._last_sync_at = time.time()
        self._last_sync_ok = ok
        if ok:
            logger.info(f"💾 [GDriveCheckpointer] sync #{self._sync_count} 完了")
        return ok

    # ─── バックグラウンド ループ ───

    def _loop(self):
        logger.info(f"🔄 [GDriveCheckpointer] バックグラウンド起動 (間隔 {self.interval_sec}s)")
        while not self._stop_event.is_set():
            try:
                self.sync_once()
            except Exception as e:
                logger.error(f"❌ [GDriveCheckpointer] 同期中に例外: {e}")
            # interval_sec の間 sleep だが、stop 要求があれば早期離脱
            self._stop_event.wait(timeout=self.interval_sec)
        logger.info("🛑 [GDriveCheckpointer] バックグラウンド停止")

    def start(self):
        if self._thread is not None and self._thread.is_alive():
            logger.info("⏭ [GDriveCheckpointer] 既に起動済 · skip")
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        if self._thread is None:
            return
        self._stop_event.set()
        self._thread.join(timeout=5)
        self._thread = None

    # ─── 状態 ───

    def status(self) -> dict:
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "sync_count": self._sync_count,
            "last_sync_at": self._last_sync_at,
            "last_sync_ok": self._last_sync_ok,
            "interval_sec": self.interval_sec,
        }


# ============================================================================
# 🚀 Section 2.5 · Colab Bootstrap (一括セットアップ)
# ============================================================================

class ColabBootstrap:
    """
    Colab 起動時の全自動セットアップ。

    実行ステップ:
        1. Drive マウント (Colab 環境のみ)
        2. SystemConfig.ensure_dirs() で必要ディレクトリ作成
        3. RuntimeStrategy.detect() で環境検出
        4. DependencyInstaller で Diffusers + 周辺 install
        5. NunchakuInstaller (Nunchaku 戦略の場合のみ)
        6. PuLIDOfficialFetcher で公式リポ clone
        7. GDriveCheckpointer 起動
    """

    def __init__(self, sys_cfg: SystemConfig):
        self.sys_cfg = sys_cfg
        self.checkpointer: Optional[GDriveCheckpointer] = None

    def _verify_and_repair_scipy(self):
        """
        scipy の Cython 拡張 (_cyutility) の健全性を確認し、
        破損時は force reinstall + ランタイム再起動を行う (Stage 4 取り込み)。

        背景:
            新 Colab セッションでは稀に scipy._cyutility が
            'does not export expected C function __Pyx__Import'
            エラーで PuLIDFluxPipeline 構築を阻害する。
            scipy.spatial.distance.cdist は Cython 拡張を実際に踏むので、
            これを健全性プローブとして使う。

        動作:
            - 健全 -> 即座に return (1 秒未満)
            - 破損 -> force reinstall + os.kill で自己再起動
                     再起動後、ColabBootstrap が再実行されると
                     今度は健全になっているので通過する。
        """
        import logging

        logger = logging.getLogger("AIBO_v7")

        scipy_broken = False
        try:
            import scipy
            from scipy.spatial.distance import cdist
            import numpy as np
            _ = cdist(np.zeros((2, 2)), np.zeros((2, 2)))
            logger.info(f"[ColabBootstrap] scipy {scipy.__version__} 健全 (cdist プローブ通過)")
        except Exception as e:
            err_str = str(e)
            if "_cyutility" in err_str or "__Pyx__Import" in err_str:
                scipy_broken = True
                logger.warning(f"[ColabBootstrap] 🚨 scipy 破損検出: {err_str[:120]}")
            else:
                # 別系統のエラー (健全とみなして続行)
                logger.warning(f"[ColabBootstrap] scipy 別エラー (続行): {err_str[:120]}")

        if scipy_broken:
            import subprocess, sys, time, os
            logger.warning("[ColabBootstrap] 🔧 scipy force reinstall 実行中...")
            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-q",
                 "--force-reinstall", "--no-deps", "scipy"],
                check=False, capture_output=True, text=True
            )
            if result.returncode != 0:
                logger.error(f"[ColabBootstrap] ❌ scipy reinstall 失敗:\n{result.stderr}")
                raise RuntimeError(
                    "scipy reinstall に失敗しました。手動で対処してください:\n"
                    "  !pip install --force-reinstall --no-deps scipy"
                )
            logger.warning("[ColabBootstrap] ✅ scipy reinstall 完了")
            logger.warning("[ColabBootstrap] 🔄 3 秒後にランタイム再起動します")
            logger.warning("[ColabBootstrap] 再起動後、起動セルを再度実行してください")
            time.sleep(3)
            os.kill(os.getpid(), 9)

    # ─── 1. Drive マウント ───

    def _mount_drive(self) -> bool:
        """Colab 環境なら Drive をマウント"""
        try:
            from google.colab import drive  # type: ignore
        except ImportError:
            logger.info("ℹ️ [Bootstrap] 非 Colab 環境 · Drive マウント skip")
            return False

        if Path("/content/drive/MyDrive").exists():
            logger.info("✅ [Bootstrap] Drive 既にマウント済")
            return True

        logger.info("🔗 [Bootstrap] Drive マウント中...")
        try:
            drive.mount("/content/drive")
            logger.info("✅ [Bootstrap] Drive マウント完了")
            return True
        except Exception as e:
            logger.error(f"❌ [Bootstrap] Drive マウント失敗: {e}")
            return False

    # ─── メイン処理 ───

    def run(
        self,
        *,
        skip_deps: bool = False,
        skip_nunchaku: bool = False,
        skip_pulid_clone: bool = False,
        skip_checkpointer: bool = False,
    ) -> dict:
        """
        全自動セットアップを実行。

        Args:
            skip_*: 各ステップをスキップする (再起動時のショートカット用)

        Returns:
            各ステップの結果辞書
        """
        # ★ Stage 4: scipy 健全性チェック (破損時は自動修復 + 再起動)
        self._verify_and_repair_scipy()

        logger.info("=" * 60)
        logger.info("🚀 AIBO v7.2 ColabBootstrap 起動")
        logger.info("=" * 60)

        results: dict = {}

        # 1. Drive マウント
        results["drive_mounted"] = self._mount_drive()

        # 2. ディレクトリ準備
        self.sys_cfg.ensure_dirs()
        results["dirs_ready"] = True

        # 3. 戦略検出
        strategy = self.sys_cfg.resolve_strategy()
        results["strategy"] = strategy.kind.value

        # 4. 依存ライブラリ
        if not skip_deps:
            dep_results = DependencyInstaller.install_all(include_upscale=self.sys_cfg.enable_upscaler)
            results["deps_installed"] = sum(1 for v in dep_results.values() if v)
            results["deps_total"] = len(dep_results)
        else:
            results["deps_installed"] = "(skipped)"

        # 5. Nunchaku (戦略が要求する場合のみ)
        if not skip_nunchaku and strategy.kind == StrategyKind.A100_40GB_NUNCHAKU:
            ok = NunchakuInstaller().install()
            results["nunchaku_installed"] = ok
            if not ok:
                # フォールバック: GGUF 戦略に降格
                logger.warning("⚠️ [Bootstrap] Nunchaku install 失敗 → GGUF フォールバックに降格")
                self.sys_cfg.strategy = None  # 再検出を強制
                self.sys_cfg.resolve_strategy()
                results["strategy_fallback"] = self.sys_cfg.strategy.kind.value
        else:
            results["nunchaku_installed"] = "(not needed)" if not skip_nunchaku else "(skipped)"

        # 6. PuLID 公式リポ
        if not skip_pulid_clone and self.sys_cfg.enable_pulid:
            pulid_ok = PuLIDOfficialFetcher().fetch()
            results["pulid_official_fetched"] = pulid_ok
        else:
            results["pulid_official_fetched"] = "(skipped)"

        # 7. GDrive Checkpointer
        if not skip_checkpointer and self.sys_cfg.enable_gdrive_sync:
            self.checkpointer = GDriveCheckpointer(
                local_dir=self.sys_cfg.output_dir,
                drive_dir=self.sys_cfg.drive_root / "outputs",
                interval_sec=self.sys_cfg.gdrive_sync_interval_sec,
            )
            self.checkpointer.start()
            results["checkpointer_started"] = True
        else:
            results["checkpointer_started"] = "(skipped)"

        logger.info("=" * 60)
        logger.info("🎉 ColabBootstrap 完了")
        logger.info("=" * 60)
        for k, v in results.items():
            logger.info(f"  {k}: {v}")
        logger.info("=" * 60)

        return results

    def shutdown(self):
        """終了時のクリーンアップ"""
        if self.checkpointer is not None:
            # 最後の同期を必ず実行
            self.checkpointer.sync_once()
            self.checkpointer.stop()


# ============================================================================
# 🔧 Section 2.6 · スタンドアロン動作確認
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("🌌 AIBO v7.2 · Section 2 (Colab Setup) 動作確認")
    print("=" * 60)

    # SystemConfig を起動
    sys_cfg = SystemConfig()
    sys_cfg.resolve_strategy()

    print()
    print(f"🔍 検出戦略: {sys_cfg.strategy.kind.value}")
    print()

    # 各クラスのスタンドアロンテスト (副作用なしのもののみ)
    print("🧪 NunchakuInstaller env 検出:")
    inst = NunchakuInstaller()
    env = inst._detect_env()
    print(f"  Python: {env['py_tag']}")
    print(f"  Torch:  {env['torch_mm']}")
    print(f"  CUDA:   {env['cuda_dotted']}")

    print()
    print("🧪 NunchakuInstaller Wheel 候補生成:")
    candidates = inst._build_wheel_candidates()
    for i, url in enumerate(candidates, 1):
        print(f"  {i}. {url.split('/')[-1]}")

    print()
    print("🧪 GDriveCheckpointer status (停止状態):")
    ckpt = GDriveCheckpointer(
        local_dir=Path("/tmp/aibo_test_local"),
        drive_dir=Path("/tmp/aibo_test_drive"),
        interval_sec=60,
    )
    print(f"  status: {ckpt.status()}")

    print()
    print("⚠️ 完全な run() 確認は Colab 上でのみ可能です:")
    print("  bootstrap = ColabBootstrap(sys_cfg)")
    print("  bootstrap.run()")

    print()
    print("✅ Section 2 動作確認完了")
