#!/usr/bin/env python
# ============================================================
#  実験くろうど 第1号案件 — 構成B: FLUX.2 Klein ネイティブ multi-reference
#  identity 検証ハーネス（チェックポイント付き / diffusers / PuLID 不使用）
#  2026-06-08 統括実装。指示: impl_colab_agent_bootstrap_and_configB_20260607
# ============================================================
#  ★ このハーネスは「証拠を組む」だけ。合格(GO/NO-GO)は宣言しない（判定は司令部/PO）。
#
#  やること:
#   - 構成B = Flux2KleinPipeline に顔 ref を list で渡して生成（multi-reference）
#     diffusers>=0.38 公式 API: __call__(image=[ref1, ref2, ...], prompt=..., ...)
#   - 各生成を **本番と同じ識別器(antelopev2 / ArcFace normed_embedding)** で
#     キャラ ref と cosine 比較 → 構成ごとの分布。別人率 = cos < 0.5。
#   - 比較グリッド: キャラ ref | baseline(基準バー) | 構成B(seed 毎) を並べる。
#   - 機械チェック: 成功率 / VRAM ピーク / 時間。自動修正は全部ログ。
#   - **チェックポイント**: 1ジョブ完了ごとに画像 + results.jsonl を逐次保存。
#     セッションが落ちても再実行で「未完ジョブだけ」継続。
#
#  厳守（指示§3）:
#   - 本番 Drive(aibo_v7 本番フォルダ/リポ)に書かない。ref 読み取りは可。
#   - 機械的/β エラー(OOM/dtype/暗い等) → 自動修正して完走（全部ログ）。
#   - 「実験が指定通り成立しない」(Klein が import/load できない・アーキ不整合) →
#     黙って別モデルに差し替えない。findings.md に正直に書いて STOP。
#   - 知覚(本人に見えるか) → グリッドに「👁 PO 目視」とだけ。自分で合格と言わない。
# ============================================================

import argparse
import json
import os
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# torch は遅延 import（--self-check の軽量分岐で GPU 不在でも回せるように）


# ------------------------------------------------------------
# ゼロ手動化の既定（指示 2026-06-07）: 既存資産を read-only 参照し、司令部の手配置を消す。
#   --face-refs / --prompts で上書き可。書き込みは scratch のみ（本番 Drive 非書込）。
# ------------------------------------------------------------
# 既定 face-refs = 既存の実験 face-ref 置き場（RECON-015 が antelopev2 で使った実 ref 群: easy/hard）。
#   ※ 本番 config に「顔 id-ref の固定ディレクトリ定数」は無い（face_ref は実行時パス渡し設計）。
#     これは現存する最有力の実 ref 資産＝統括の提案既定。正規の本人セットが別なら司令部が --face-refs で指定。
#     第1走行の狙いは「Klein がそもそも顔を保てるか」を安く問うこと（同一人物 ref かは self-check が点検）。
DEFAULT_FACE_REFS = "/content/drive/MyDrive/aibo_v7/recon015_refs"  # read-only

# 既定プロンプト = プロジェクトの PORTRAIT/COORDINATE/SITUATION プリセット由来（01_config.py _MODE_PRESETS）。
DEFAULT_PROMPTS = [
    # PORTRAIT（全身・スタジオ）
    "full body shot, standing pose, head to toe, entire body visible including feet, "
    "soft key light, 50mm lens, professional fashion photography, clean studio background, "
    "cinematic, sharp focus",
    # COORDINATE（全身ファッション）
    "full body fashion shot, standing pose, fitted white top, slim skinny jeans, white sneakers, "
    "neutral studio background, soft fashion lighting, natural pose, photographic, cinematic",
    # SITUATION（環境光・lifestyle）
    "walking through a park at golden hour, warm sunlight, 35mm handheld, lifestyle",
    # 顔寄り（identity を素で見る近接ショット）
    "upper body portrait, looking at camera, natural soft light, 85mm lens, sharp focus on face",
]


# ------------------------------------------------------------
# パス/境界ガード — 本番フォルダへの書き込みを物理的に拒否
# ------------------------------------------------------------
PRODUCTION_MARKERS = ("aibo_v7", "AIBOV7")  # 本番リポ/Drive フォルダ名


def assert_not_production(path: str, label: str):
    """scratch/出力先が本番フォルダ配下なら即停止（ref 読取りには使わない）。"""
    norm = os.path.normpath(os.path.abspath(path)).replace("\\", "/").lower()
    for m in PRODUCTION_MARKERS:
        if f"/{m.lower()}/" in norm + "/" or norm.endswith(f"/{m.lower()}"):
            raise RuntimeError(
                f"[境界違反] {label} が本番フォルダ配下です: {path}\n"
                f"  → 実験出力は本番(aibo_v7)に書かない。例: /content/drive/MyDrive/aibo_lab/... を使う。"
            )


# ------------------------------------------------------------
# ログ（autofix / 進捗）— silent fail 禁止。全部ファイルに残す。
# ------------------------------------------------------------
class JsonlLog:
    def __init__(self, path):
        self.path = path
        os.makedirs(os.path.dirname(path), exist_ok=True)

    def append(self, record: dict):
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def log(msg):
    print(f"[configB] {msg}", flush=True)


# ============================================================
# スコアラー — 本番(08_face_refiner.py)と同一の識別器・前処理
#   FaceAnalysis(name="antelopev2", root=HF_HOME/insightface), det_size=(640,640)
#   RGB→BGR, 最大顔, normed_embedding(ArcFace, 単位ノルム) → cosine=dot
# ============================================================
class ArcFaceScorer:
    def __init__(self, model_name="antelopev2"):
        self.model_name = model_name
        self._app = None
        self.provider = None  # 実効 provider（CUDA か CPU か）

    def _active_providers(self):
        """ロード済みモデルの session から実際に効いている provider を取り出す（沈黙フォールバック検出用）。"""
        try:
            for m in (self._app.models or {}).values():
                sess = getattr(m, "session", None)
                if sess is not None:
                    return sess.get_providers()
        except Exception as e:
            return f"<unknown: {repr(e)}>"
        return "<no session>"

    def _inspect_and_flatten_models(self, model_dir, autofix=None):
        """
        antelopev2 の .onnx 実体を点検し、二重ネストなら flatten（機械的 autofix）。
        既知バグ: antelopev2.zip が <model_dir>/antelopev2/*.onnx に二重展開されるが、
                  FaceAnalysis は <model_dir>/*.onnx 直下を見るため 'detection' in self.models が落ちる。
        実体を必ずログに出す（見える化）。flatten したら True。
        """
        import glob
        import shutil

        if not os.path.isdir(model_dir):
            log(f"  [model 点検] ディレクトリ無し: {model_dir}（DL 未完/失敗の疑い）")
            return False

        # 实体を見える化: 直下 + 1階層下を ls
        top = sorted(os.listdir(model_dir))
        log(f"  [model 点検] {model_dir} 直下: {top}")
        for name in top:
            sub = os.path.join(model_dir, name)
            if os.path.isdir(sub):
                log(f"        └ {name}/: {sorted(os.listdir(sub))}")

        if glob.glob(os.path.join(model_dir, "*.onnx")):
            log("  [model 点検] 直下に .onnx あり（配置は正常）")
            return False

        nested = glob.glob(os.path.join(model_dir, "*", "*.onnx"))
        if not nested:
            log("  [model 点検] .onnx が直下にもネストにも無い → flatten 不能（DL 失敗の疑い）")
            return False

        # flatten: ネスト先の中身を直下へ移動（二重ネスト antelopev2/antelopev2/ → antelopev2/）
        nested_dirs = sorted({os.path.dirname(p) for p in nested})
        moved = []
        for nd in nested_dirs:
            for fn in os.listdir(nd):
                src, dst = os.path.join(nd, fn), os.path.join(model_dir, fn)
                if os.path.exists(dst):
                    continue
                shutil.move(src, dst)
                moved.append(fn)
            try:
                if not os.listdir(nd):
                    os.rmdir(nd)
            except OSError as e:
                log(f"        （空ネスト dir 掃除 skip: {repr(e)}）")
        log(f"  [model 点検] flatten 実行: {len(moved)} ファイルを直下へ移動 "
            f"({[os.path.basename(d) for d in nested_dirs]} → {os.path.basename(model_dir)}/): {moved}")
        if autofix is not None:
            autofix.append({"stage": "flatten", "issue": "antelopev2.zip 二重ネスト",
                            "moved": moved, "from": nested_dirs, "to": model_dir,
                            "meaning_changed": False})
        return bool(moved)

    def _ensure(self, autofix=None):
        if self._app is not None:
            return
        from insightface.app import FaceAnalysis

        hf_cache = os.environ.get("HF_HOME", "/root/.cache/huggingface")
        root = os.path.join(hf_cache, "insightface")
        model_dir = os.path.join(root, "models", self.model_name)
        log(f"InsightFace({self.model_name}) root={root}")

        def _build(providers, ctx_id):
            app = FaceAnalysis(name=self.model_name, root=root, providers=providers)
            app.prepare(ctx_id=ctx_id, det_size=(640, 640))
            return app

        # provider は CUDA→CPU。ただし「モデル不在(AssertionError)」は provider と無関係なので別扱い:
        #   - AssertionError ('detection' in self.models) = .onnx が探索先に無い → flatten autofix で復旧
        #     （"CUDA provider 初期化失敗" と誤報しない）。
        #   - それ以外の例外 = 本物の provider 等の失敗 → 次 provider へフォールバック。
        #   antelopev2 の ArcFace は決定的＝CPU/GPU で embedding 同一→本番比較性は維持。GPU は FLUX 生成に温存。
        attempts = [(["CUDAExecutionProvider", "CPUExecutionProvider"], 0, "CUDA"),
                    (["CPUExecutionProvider"], -1, "CPU")]
        last_exc = None
        for providers, ctx_id, tag in attempts:
            try:
                self._app = _build(providers, ctx_id)
                self.provider = self._active_providers()
                log(f"  provider(実効)= {self.provider} ({tag} 要求)")
                return
            except AssertionError as e:
                # モデル不在。provider 失敗ではない（誤ラベル禁止）。flatten して同 provider で即再挑戦。
                log(f"  ✖ モデル不在(AssertionError): {repr(e)} ← provider 失敗ではない（{tag} 試行中）")
                log(traceback.format_exc())
                if self._inspect_and_flatten_models(model_dir, autofix):
                    try:
                        self._app = _build(providers, ctx_id)
                        self.provider = self._active_providers()
                        log(f"  ✅ flatten 後に復旧: provider(実効)= {self.provider} ({tag})")
                        return
                    except Exception as e2:
                        last_exc = e2
                        log(f"  flatten 後も {tag} で失敗: {repr(e2)}")
                        log(traceback.format_exc())
                        continue
                last_exc = e
                continue
            except Exception as e:
                # 握り潰さない: repr + traceback を必ず出す（空メッセージ＝デバッグ不能＝可観測性違反）。
                log(f"  ⚠ {tag} provider 初期化失敗 → 次へフォールバック: {repr(e)}")
                log(traceback.format_exc())
                last_exc = e
                continue
        raise RuntimeError(
            f"scorer 初期化に失敗。最後の例外: {repr(last_exc)}\n"
            f"  → モデル不在(AssertionError)で flatten も不能なら antelopev2 の DL/配置を確認: {model_dir}"
        ) from last_exc

    def embed(self, image: Image.Image):
        """最大顔の ArcFace 正規化埋め込み(512d, 単位ノルム)。顔無し→None。"""
        self._ensure()
        arr = np.array(image.convert("RGB"))[..., ::-1]  # RGB→BGR（本番と同じ）
        faces = self._app.get(arr)
        if not faces:
            return None
        face = max(faces, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1]))
        return np.asarray(face.normed_embedding, dtype=np.float32)

    @staticmethod
    def cosine(a, b):
        # normed_embedding は単位ノルム → cosine == dot。安全のため明示正規化。
        if a is None or b is None:
            return -1.0
        a = a / (np.linalg.norm(a) + 1e-8)
        b = b / (np.linalg.norm(b) + 1e-8)
        return float(np.dot(a, b))


def _ver_lt(v, target=(2, 1, 0)):
    """'2.0.1' < target を packaging 無しで判定（失敗時は True=要更新側に倒す）。"""
    try:
        parts = tuple(int(x) for x in str(v).split("+")[0].split(".")[:3])
        return parts < target
    except (ValueError, AttributeError):
        return True


def ensure_scorer_deps(autofix, skip=False):
    """
    識別器(insightface/onnxruntime-gpu)を **本番(02_colab_setup)と同じ方針** で自動導入。
    司令部が ① コマンドを再実行するだけで通るように、ここで自己ブートストラップする。

    本番一致の根拠（cosine を本番と比較可能に保つため）:
      - insightface / onnxruntime-gpu は **バージョン非ピン**（02_colab_setup.py:271,274 が None）。
        ＝本番と同じく「その時点の latest」を入れる。勝手な pin は本番との乖離を生むので張らない。
      - **numpy>=2.1.0** を保証（02_colab_setup.py:252 の insightface/scipy 互換要件 _center/_blas）。
      - 既に充足なら pip を呼ばない（C 拡張 ABI 不整合→自動再起動ループ回避。本番 PROTECT_IF_SATISFIED と同思想）。
    """
    if skip:
        log("scorer deps: --skip-deps 指定 → 自動導入を skip")
        return

    import importlib

    need = []
    # numpy 床（既に満たすなら触らない＝ABI 再起動回避）
    try:
        import numpy as _np
        if _ver_lt(_np.__version__, (2, 1, 0)):
            need.append("numpy>=2.1.0")
    except Exception:
        need.append("numpy>=2.1.0")
    # insightface
    try:
        importlib.import_module("insightface")
    except Exception:
        need.append("insightface")
    # onnxruntime（import 名は -gpu でも 'onnxruntime'）。無ければ GPU ビルドを入れる。
    try:
        importlib.import_module("onnxruntime")
    except Exception:
        need.append("onnxruntime-gpu")

    if not need:
        log("scorer deps: 充足（insightface / onnxruntime / numpy>=2.1.0）→ pip skip")
        autofix.append({"stage": "deps", "action": "skip(satisfied)"})
        return

    log(f"scorer deps 自動導入（本番方針=非ピン+numpy床）: {need}")
    cmd = [sys.executable, "-m", "pip", "install", "-q", *need]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    tail = (proc.stdout or "")[-800:] + (proc.stderr or "")[-800:]
    autofix.append({"stage": "deps", "installed": need, "rc": proc.returncode,
                    "cmd": " ".join(cmd), "log_tail": tail.strip(), "meaning_changed": False})
    if proc.returncode != 0:
        # 黙って続行しない。識別器が入らなければ cosine は測れない＝正直に止める材料。
        raise RuntimeError(f"scorer deps の pip install 失敗 (rc={proc.returncode}):\n{tail}")
    log("scorer deps 導入完了")


def prepare_scorer(scorer_name, autofix, skip_deps=False):
    """
    deps 自動導入 → スコアラー構築 → **antelopev2 を prefetch**（本番と同一の DL 経路で展開）。
    prefetch は FaceAnalysis(name=antelopev2, root=HF_HOME/insightface).prepare() を一度叩くだけ＝
    08_face_refiner.py と同一コードパス。これで cosine が本番と同一モデル・同一前処理で算出される。
    """
    ensure_scorer_deps(autofix, skip=skip_deps)
    scorer = ArcFaceScorer(scorer_name)
    # prefetch + 配置点検 + 二重ネスト flatten（autofix）を含む。実体 ls もここでログされる。
    scorer._ensure(autofix)
    autofix.append({"stage": "prefetch", "model": scorer_name, "provider": scorer.provider,
                    "hf_home": os.environ.get("HF_HOME", "/root/.cache/huggingface")})
    log(f"{scorer_name} prefetch 完了（本番と同一パス/モデル＝cosine 比較可能 / provider={scorer.provider}）")
    return scorer


# ============================================================
# 構成B パイプライン — Flux2KleinPipeline（成立しなければ findings で STOP）
# ============================================================
def load_configB_pipeline(repo_id, dtype_str, autofix: JsonlLog):
    """
    成立条件:
      - diffusers に Flux2KleinPipeline がある（>=0.38）
      - repo_id の重みが load できる
    成立しない場合は ExperimentNotEstablished を投げる（呼び出し側で findings.md → STOP）。
    ※ 黙って Flux2Pipeline(別 variant) や FLUX.1 に差し替えない。
    """
    import torch

    try:
        from diffusers import Flux2KleinPipeline
    except ImportError as e:
        raise ExperimentNotEstablished(
            "diffusers に Flux2KleinPipeline が無い（>=0.38 が必要）。"
            f"import エラー: {e}"
        ) from e

    dtype = {"bf16": torch.bfloat16, "fp16": torch.float16, "fp32": torch.float32}[dtype_str]

    # bf16 非対応 GPU(T4 等)での自動降格は「機械的摩擦」→ 自動修正+ログ（意味は不変）。
    if dtype == torch.bfloat16 and torch.cuda.is_available():
        if not torch.cuda.is_bf16_supported():
            autofix.append({
                "stage": "load", "issue": "bf16 unsupported on this GPU",
                "fix": "fall back to fp16", "meaning_changed": False,
            })
            dtype = torch.float16
            log("⚠ bf16 非対応 GPU → fp16 に降格（autofix ログ済み）")

    log(f"Flux2KleinPipeline.from_pretrained({repo_id}, dtype={dtype})")
    try:
        pipe = Flux2KleinPipeline.from_pretrained(repo_id, torch_dtype=dtype)
    except Exception as e:
        # repo gated / 重み欠落 / アーキ不整合 = 「成立しない」系。差し替えず正直に上げる。
        raise ExperimentNotEstablished(
            f"Flux2KleinPipeline の重み load に失敗: {repo_id}\n  {type(e).__name__}: {e}"
        ) from e

    # メモリ節約（OOM 予防の機械的処置）。CPU offload は VRAM 不足環境の保険。
    if torch.cuda.is_available():
        try:
            pipe.enable_model_cpu_offload()
            autofix.append({"stage": "load", "issue": "preempt OOM",
                            "fix": "enable_model_cpu_offload", "meaning_changed": False})
        except Exception as e:
            log(f"  (cpu offload 不可 → そのまま .to(cuda): {e})")
            pipe = pipe.to("cuda")
    return pipe, dtype


class ExperimentNotEstablished(Exception):
    """実験そのものが成立しない（前提破壊）。完走ではなく findings で報告して止まる。"""


# ============================================================
# 入力ロード
# ============================================================
def load_images_from_dir(d):
    if not d or not os.path.isdir(d):
        return []
    exts = (".png", ".jpg", ".jpeg", ".webp", ".bmp")
    out = []
    for name in sorted(os.listdir(d)):
        if name.lower().endswith(exts):
            try:
                out.append((name, Image.open(os.path.join(d, name)).convert("RGB")))
            except Exception as e:
                log(f"⚠ 画像読込失敗 skip: {name}: {e}")
    return out


def load_prompts(path):
    if not path or not os.path.isfile(path):
        return []
    if path.lower().endswith(".json"):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return [str(x) for x in (data if isinstance(data, list) else data.get("prompts", []))]
    with open(path, encoding="utf-8") as f:
        return [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]


# ============================================================
# グリッド合成
# ============================================================
def _thumb(img, size=320):
    im = img.copy()
    im.thumbnail((size, size))
    canvas = Image.new("RGB", (size, size), (24, 24, 24))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return canvas


def _label(img, text):
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 16)
    except Exception:
        font = ImageFont.load_default()
    d.rectangle([0, img.height - 22, img.width, img.height], fill=(0, 0, 0))
    d.text((4, img.height - 20), text, fill=(255, 255, 255), font=font)
    return img


def build_grid(out_path, char_refs, baselines, prompt_rows, cell=320):
    """
    行 = プロンプト。列 = [キャラ ref][baseline...][構成B(seed 毎, cos 付き)]。
    最上段にヘッダ（👁 PO 目視 / cos≠知覚 の注記）。
    """
    n_ref = min(1, len(char_refs))      # ref は代表1枚（先頭）をグリッドに
    n_base = len(baselines)
    n_b_max = max((len(r["cells"]) for r in prompt_rows), default=0)
    cols = n_ref + n_base + n_b_max
    rows = len(prompt_rows)
    header_h = 40
    W = cols * cell
    H = header_h + rows * cell
    grid = Image.new("RGB", (W, max(H, header_h + cell)), (12, 12, 12))

    d = ImageDraw.Draw(grid)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except Exception:
        font = ImageFont.load_default()
    d.text((8, 10),
           "構成B(Klein multi-ref)  |  👁 PO 目視判定（cos は識別器スコア=知覚的同一性ではない / 合格は宣言しない）",
           fill=(255, 220, 120), font=font)

    for r, row in enumerate(prompt_rows):
        y = header_h + r * cell
        x = 0
        if char_refs:
            grid.paste(_label(_thumb(char_refs[0][1], cell), "char ref"), (x, y)); x += cell
        for bn, bimg in baselines:
            grid.paste(_label(_thumb(bimg, cell), f"baseline:{bn[:18]}"), (x, y)); x += cell
        for c in row["cells"]:
            cap = f"B seed{c['seed']} cos={c['cos']:.3f}" if c["cos"] >= 0 else f"B seed{c['seed']} 顔未検出"
            grid.paste(_label(_thumb(c["img"], cell), cap), (x, y)); x += cell

    grid.save(out_path)
    log(f"グリッド保存: {out_path}")


# ============================================================
# チェックポイント
# ============================================================
def completed_keys(results_path):
    done = set()
    if os.path.isfile(results_path):
        with open(results_path, encoding="utf-8") as f:
            for ln in f:
                try:
                    rec = json.loads(ln)
                    done.add((rec["prompt_idx"], rec["seed"]))
                except (json.JSONDecodeError, KeyError):
                    continue
    return done


# ============================================================
# 本体
# ============================================================
@dataclass
class Config:
    repo_id: str = "black-forest-labs/FLUX.2-klein-base-4B"  # ★初回 run で正式名/gate を要確認
    steps: int = 50            # base klein は非蒸留 → 50。KV(蒸留4-step)は別 variant。
    guidance: float = 4.0      # diffusers 既定
    height: int = 1024
    width: int = 1024
    dtype: str = "bf16"
    max_refs: int = 4          # multi-reference に渡す顔 ref 上限
    seeds: list = field(default_factory=lambda: [1234, 5678, 9012])


def run(args):
    cfg = Config(
        repo_id=args.repo_id, steps=args.steps, guidance=args.guidance,
        height=args.height, width=args.width, dtype=args.dtype,
        max_refs=args.max_refs,
        seeds=[int(s) for s in args.seeds.split(",") if s.strip()],
    )

    scratch = args.scratch
    assert_not_production(scratch, "scratch/出力先")
    os.makedirs(scratch, exist_ok=True)
    img_dir = os.path.join(scratch, "configB_images")
    os.makedirs(img_dir, exist_ok=True)
    results_path = os.path.join(scratch, "results.jsonl")
    autofix = JsonlLog(os.path.join(scratch, "autofix_log.jsonl"))
    findings_path = os.path.join(scratch, "findings.md")

    # --- 入力（ゼロ手動化: face-refs/prompts は既定で既存資産/プリセットを参照） ---
    char_refs = load_images_from_dir(args.ref_dir)
    baselines = load_images_from_dir(args.baseline_dir)  # 第1走行は通常 空（baseline スキップ）
    if args.prompts:
        prompts = load_prompts(args.prompts)
        prompt_src = args.prompts
    else:
        prompts = list(DEFAULT_PROMPTS)
        prompt_src = "DEFAULT_PROMPTS（プリセット由来）"

    log(f"入力: face_refs={len(char_refs)} (<-{args.ref_dir}) / "
        f"baseline={len(baselines)}{'（第1走行スキップ）' if not baselines else ''} / "
        f"prompts={len(prompts)} (<-{prompt_src})")

    # --- face-refs は既定で既存資産を read-only 参照。空＝パス誤り/資産消失＝正直に止める（捏造しない） ---
    if not char_refs:
        msg = (f"既定/指定の face-refs に顔画像が無い: {args.ref_dir}\n"
               f"  → 本来 --self-check が本走行の前に捕まえる層。\n"
               f"  → 正規の本人 ref セットを --face-refs で指定して再実行してください。")
        log("⏸ " + msg.replace("\n", " "))
        with open(findings_path, "w", encoding="utf-8") as f:
            f.write(f"# findings(構成B) — face-refs 不在\n\n{msg}\n")
        self_check(cfg, args.ref_dir, autofix, skip_deps=args.skip_deps)
        return 0

    # --- スコアラー（deps 自動導入 + antelopev2 prefetch）& 参照埋め込み ---
    scorer = prepare_scorer(args.scorer, autofix, skip_deps=args.skip_deps)
    ref_embs = []
    for name, im in char_refs:
        e = scorer.embed(im)
        if e is None:
            log(f"⚠ ref で顔未検出 skip: {name}")
            autofix.append({"stage": "ref_embed", "issue": f"no face in ref {name}",
                            "fix": "skip this ref", "meaning_changed": False})
        else:
            ref_embs.append(e)
    if not ref_embs:
        raise ExperimentNotEstablished("全 ref で顔未検出。識別器がキャラ ref を読めない（前提破壊）。")
    mean_ref = np.mean(ref_embs, axis=0)
    mean_ref = mean_ref / (np.linalg.norm(mean_ref) + 1e-8)

    multi_refs = [im for _, im in char_refs[: cfg.max_refs]]
    log(f"multi-reference に {len(multi_refs)} 枚を投入")

    # --- パイプライン load（成立しなければ findings → STOP） ---
    try:
        pipe, used_dtype = load_configB_pipeline(cfg.repo_id, cfg.dtype, autofix)
    except ExperimentNotEstablished as e:
        with open(findings_path, "w", encoding="utf-8") as f:
            f.write(f"# findings(構成B) — 実験が成立しない\n\n"
                    f"構成B は **走らなかった**。理由（正直に）:\n\n```\n{e}\n```\n\n"
                    f"→ 黙って別モデルに差し替えていない。これも findings（答え）。"
                    f"司令部判断: repo_id/版数の確認 or 構成A 別トラックへ。\n")
        log(f"⛔ STOP（成立しない）: {e}")
        return 2

    import torch

    done = completed_keys(results_path)
    log(f"再開: 完了済み {len(done)} ジョブを skip")

    results = JsonlLog(results_path)
    t_all0 = time.time()
    n_ok = n_fail = n_noface = 0
    prompt_rows = []

    for pi, prompt in enumerate(prompts):
        row_cells = []
        for seed in cfg.seeds:
            key = (pi, seed)
            img_path = os.path.join(img_dir, f"b_p{pi:02d}_s{seed}.png")

            if key in done and os.path.isfile(img_path):
                # 既存結果を読み戻してグリッドに使う（再生成しない）
                try:
                    row_cells.append(_load_done_cell(results_path, pi, seed, img_path))
                    continue
                except Exception as e:
                    log(f"  既存セル読戻し失敗 → 再生成: {e}")

            cell = _gen_one_job(
                pipe, prompt, seed, multi_refs, cfg, used_dtype,
                scorer, mean_ref, ref_embs, img_path, autofix, torch,
            )
            results.append({
                "prompt_idx": pi, "prompt": prompt, "seed": seed,
                "img": img_path, "cos": cell["cos"], "cos_best": cell["cos_best"],
                "vram_mb": cell["vram_mb"], "sec": cell["sec"], "status": cell["status"],
            })
            if cell["status"] == "ok":
                n_ok += 1
            elif cell["status"] == "noface":
                n_noface += 1; n_ok += 1  # 生成は成功・顔未検出は別カウント
            else:
                n_fail += 1
            row_cells.append(cell)
        prompt_rows.append({"prompt": prompt, "cells": row_cells})

    # --- 集計 & グリッド & サマリ ---
    cosines = [c["cos"] for row in prompt_rows for c in row["cells"] if c["cos"] >= 0]
    summary = _summarize(cosines, n_ok, n_fail, n_noface, time.time() - t_all0, used_dtype, cfg)
    with open(os.path.join(scratch, "summary.md"), "w", encoding="utf-8") as f:
        f.write(summary)
    log("\n" + summary)

    build_grid(os.path.join(scratch, "grid_configB.png"), char_refs, baselines, prompt_rows)
    log(f"✅ 完走。出力: {scratch}")
    log("   ※ GO/NO-GO は宣言しない。グリッド + cos 分布で司令部/PO が判定。👁 知覚=PO 目視。")
    return 0


def _gen_one_job(pipe, prompt, seed, multi_refs, cfg, dtype, scorer, mean_ref, ref_embs,
                 img_path, autofix, torch):
    gen = torch.Generator(device="cuda" if torch.cuda.is_available() else "cpu").manual_seed(seed)
    if torch.cuda.is_available():
        torch.cuda.reset_peak_memory_stats()
    t0 = time.time()

    def _call():
        return pipe(
            image=multi_refs,                # ★ multi-reference = PIL list
            prompt=prompt,
            num_inference_steps=cfg.steps,
            guidance_scale=cfg.guidance,
            height=cfg.height, width=cfg.width,
            generator=gen,
        ).images[0]

    try:
        out = _call()
    except torch.cuda.OutOfMemoryError as e:
        # OOM = 機械的摩擦。VRAM 開放 + tiling/slicing で1回だけ自動リトライ（意味不変）。
        log(f"  OOM → VAE tiling + attention slicing で自動リトライ: {e}")
        torch.cuda.empty_cache()
        for fn in ("enable_vae_tiling", "enable_attention_slicing"):
            if hasattr(pipe, fn):
                getattr(pipe, fn)()
        autofix.append({"stage": "generate", "prompt_idx_seed": f"{prompt[:20]}/{seed}",
                        "issue": "CUDA OOM", "fix": "vae_tiling+attention_slicing+retry",
                        "meaning_changed": False})
        try:
            out = _call()
        except Exception as e2:
            log(f"  リトライも失敗: {e2}")
            autofix.append({"stage": "generate", "issue": f"retry failed: {e2}",
                            "fix": "record as fail (差し替えない)", "meaning_changed": False})
            return {"seed": seed, "img": None, "cos": -1.0, "cos_best": -1.0,
                    "vram_mb": _vram(torch), "sec": time.time() - t0, "status": "fail"}
    except Exception as e:
        # 生成系の予期せぬ失敗 → 記録して次へ（黙って握りつぶさない・差し替えない）
        log(f"  生成失敗: {e}")
        autofix.append({"stage": "generate", "issue": f"{type(e).__name__}: {e}",
                        "fix": "record as fail", "meaning_changed": False,
                        "trace": traceback.format_exc()[-1500:]})
        return {"seed": seed, "img": None, "cos": -1.0, "cos_best": -1.0,
                "vram_mb": _vram(torch), "sec": time.time() - t0, "status": "fail"}

    sec = time.time() - t0
    vram = _vram(torch)
    out.save(img_path)

    # スコア（mean ref / best single ref）
    gen_emb = scorer.embed(out)
    cos = scorer.cosine(mean_ref, gen_emb)
    cos_best = max((scorer.cosine(e, gen_emb) for e in ref_embs), default=-1.0) if gen_emb is not None else -1.0
    status = "ok" if gen_emb is not None else "noface"
    log(f"  p='{prompt[:28]}' seed={seed} cos={cos:.3f} best={cos_best:.3f} "
        f"{vram:.0f}MB {sec:.1f}s [{status}]")
    return {"seed": seed, "img": out, "cos": cos, "cos_best": cos_best,
            "vram_mb": vram, "sec": sec, "status": status}


def _load_done_cell(results_path, pi, seed, img_path):
    with open(results_path, encoding="utf-8") as f:
        for ln in f:
            rec = json.loads(ln)
            if rec.get("prompt_idx") == pi and rec.get("seed") == seed:
                return {"seed": seed, "img": Image.open(img_path).convert("RGB"),
                        "cos": rec.get("cos", -1.0), "cos_best": rec.get("cos_best", -1.0),
                        "vram_mb": rec.get("vram_mb", 0), "sec": rec.get("sec", 0),
                        "status": rec.get("status", "ok")}
    raise KeyError("done cell not found in results.jsonl")


def _vram(torch):
    if torch.cuda.is_available():
        return torch.cuda.max_memory_allocated() / (1024 ** 2)
    return 0.0


def _summarize(cosines, n_ok, n_fail, n_noface, total_sec, dtype, cfg):
    if cosines:
        arr = np.array(cosines)
        diff_rate = float((arr < 0.5).mean())  # 別人率 = ArcFace cos < 0.5（本番慣行）
        stat = (f"- cos 件数: {len(arr)}\n"
                f"- mean={arr.mean():.3f} median={np.median(arr):.3f} "
                f"min={arr.min():.3f} max={arr.max():.3f}\n"
                f"- 別人率(cos<0.5): {diff_rate*100:.1f}%\n")
    else:
        stat = "- 有効 cos なし（全ジョブ顔未検出 or 失敗）\n"
    return (
        f"# 構成B サマリ（Klein multi-reference / 識別器=antelopev2）\n\n"
        f"## ArcFace cosine 分布\n{stat}\n"
        f"## 機械チェック\n"
        f"- 生成成功: {n_ok}（うち顔未検出 {n_noface}） / 失敗: {n_fail}\n"
        f"- 総時間: {total_sec/60:.1f} 分 / dtype={dtype}\n"
        f"- 設定: repo={cfg.repo_id} steps={cfg.steps} guidance={cfg.guidance} "
        f"{cfg.width}x{cfg.height} max_refs={cfg.max_refs} seeds={cfg.seeds}\n\n"
        f"## 判定について\n"
        f"- ここでは **GO/NO-GO を宣言しない**。cos は識別器スコア=知覚的同一性ではない。\n"
        f"- 👁 本人に見えるか / アジア系忠実度 / 崩れ → grid_configB.png を **PO 目視**。\n"
    )


def self_check(cfg, face_refs_path, autofix, skip_deps=False):
    """
    成立性 + 入力健全性の軽量チェック。高い本走行の前に安く確実に止める層:
      1. 既定/指定 face-refs パスが存在し、顔画像があるか（パス誤り・資産消失を捕捉）
      2. 各 ref で本番識別器(antelopev2)が顔検出できるか（不正画像を捕捉）
      3. ref 同士が同一人物っぽいか（multi-ref は1人物前提・ペアワイズ cos<0.5 で別人混在を警告）
      4. Flux2KleinPipeline が import できるか（diffusers>=0.38）
      5. repo にアクセス可能か（huggingface_hub.model_info・DL しない）
    → identity の合否は名乗らない。あくまで「本走行に進んでよい配線か」の点検。
    """
    log("=== SELF-CHECK（成立性 + 入力健全性）===")
    ok = True

    # 0: 識別器 deps を本番方針で自動導入（refs の有無に関わらず・冪等）。
    try:
        ensure_scorer_deps(autofix, skip=skip_deps)
    except Exception as e:
        ok = False
        log(f"  [NG] scorer deps 自動導入失敗: {e}")

    # 1+2+3: face-refs の存在・顔検出・同一人物性
    refs = load_images_from_dir(face_refs_path)
    if not os.path.isdir(face_refs_path):
        ok = False
        log(f"  [NG] face-refs ディレクトリが無い: {face_refs_path}")
    elif not refs:
        ok = False
        log(f"  [NG] face-refs に画像が無い: {face_refs_path}")
    else:
        log(f"  [..] face-refs: {len(refs)} 枚 @ {face_refs_path}")
        try:
            sc = prepare_scorer("antelopev2", autofix, skip_deps=skip_deps)  # deps+antelopev2 prefetch
            embs = []
            for name, im in refs:
                e = sc.embed(im)
                log(f"     - {name}: {'顔検出OK' if e is not None else '顔未検出 NG'}")
                if e is None:
                    ok = False
                else:
                    embs.append((name, e))
            if len(embs) >= 2:  # multi-ref は1人物前提。別人混在を安く検出。
                lows = []
                for i in range(len(embs)):
                    for j in range(i + 1, len(embs)):
                        c = ArcFaceScorer.cosine(embs[i][1], embs[j][1])
                        if c < 0.5:
                            lows.append((embs[i][0], embs[j][0], c))
                if lows:
                    log("  [WARN] ref 同士の類似が低いペアあり（別人混在の疑い・multi-ref は1人物前提）:")
                    for a, b, c in lows[:6]:
                        log(f"        {a} vs {b}: cos={c:.3f}")
                    log("        → 同一人物の ref だけに絞るか、--face-refs を本人セットへ。")
                else:
                    log("  [OK] ref 同士は同一人物として整合（全ペア cos>=0.5）")
        except Exception as e:
            ok = False
            # 空メッセージで握り潰さない: repr + traceback を必ず出す（可観測性）。
            log(f"  [NG] スコアラー初期化/検出失敗: {repr(e)}")
            log(traceback.format_exc())

    # 4: import
    try:
        from diffusers import Flux2KleinPipeline  # noqa: F401
        log("  [OK] diffusers.Flux2KleinPipeline import 可")
    except ImportError as e:
        ok = False
        log(f"  [NG] Flux2KleinPipeline import 不可（diffusers>=0.38 要）: {e}")

    # 5: repo アクセス（DL しない）
    try:
        from huggingface_hub import model_info
        info = model_info(cfg.repo_id)
        log(f"  [OK] repo アクセス可: {cfg.repo_id} (siblings={len(info.siblings)})")
    except Exception as e:
        ok = False
        log(f"  [NG] repo にアクセスできない（gate/名称/トークン要確認）: {cfg.repo_id}: {e}")

    autofix.append({"stage": "self_check", "established": ok, "face_refs": face_refs_path})
    log(f"=== SELF-CHECK: {'PASS（本走行へ進んでよい）' if ok else 'FAIL（上記 NG を解消してから本走行）'} ===")
    return ok


def build_argparser():
    p = argparse.ArgumentParser(description="構成B: FLUX.2 Klein multi-reference identity 検証（CP付き）")
    p.add_argument("--face-refs", "--ref-dir", dest="ref_dir", default=DEFAULT_FACE_REFS,
                   help=f"キャラ顔 ref ディレクトリ（読取専用・既定=既存資産 {DEFAULT_FACE_REFS}）")
    p.add_argument("--baseline-dir", default="",
                   help="現行パイプライン出力サンプル（基準バー・第1走行は通常スキップ＝空）")
    p.add_argument("--prompts", default="",
                   help="評価プロンプト（.txt 1行1件 / .json list）。未指定なら PORTRAIT 系プリセット既定")
    p.add_argument("--scratch", default="/content/drive/MyDrive/aibo_lab/flux2_identity/run",
                   help="出力/CP 先（★本番 aibo_v7 配下は不可）")
    p.add_argument("--repo-id", default=Config.repo_id)
    p.add_argument("--steps", type=int, default=Config.steps)
    p.add_argument("--guidance", type=float, default=Config.guidance)
    p.add_argument("--height", type=int, default=Config.height)
    p.add_argument("--width", type=int, default=Config.width)
    p.add_argument("--dtype", default=Config.dtype, choices=["bf16", "fp16", "fp32"])
    p.add_argument("--max-refs", type=int, default=Config.max_refs)
    p.add_argument("--seeds", default="1234,5678,9012")
    p.add_argument("--scorer", default="antelopev2", help="本番と同じ識別器（既定 antelopev2）")
    p.add_argument("--skip-deps", action="store_true",
                   help="insightface/onnxruntime-gpu の自動導入を skip（既に同等環境がある時）")
    p.add_argument("--self-check", action="store_true", help="成立性の軽量チェックのみ（生成しない）")
    return p


def main():
    args = build_argparser().parse_args()
    if args.self_check:
        cfg = Config(repo_id=args.repo_id)
        os.makedirs(args.scratch, exist_ok=True)
        assert_not_production(args.scratch, "scratch/出力先")
        af = JsonlLog(os.path.join(args.scratch, "autofix_log.jsonl"))
        return 0 if self_check(cfg, args.ref_dir, af, skip_deps=args.skip_deps) else 3
    return run(args)


if __name__ == "__main__":
    sys.exit(main())
