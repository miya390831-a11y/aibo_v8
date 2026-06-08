# 実験くろうど 第1号 — 構成B（FLUX.2 Klein multi-reference）走らせ方

- 日付: 2026-06-08 / 統括実装
- 指示: `impl_colab_agent_bootstrap_and_configB_20260607`
- スコープ: **構成B のみ**（Klein ネイティブ multi-reference / diffusers / PuLID 不使用）。
  構成C(baseline)は再生成しない＝提供サンプルを基準バーに使う。構成A(PuLID-Flux2/ComfyUI, β)は別トラックで後回し。
- 位置づけ: 隔離サンドボックス。本番コード/Setting A 非接触。**本番 Drive(aibo_v7)に書かない**。

## 構成
- `colab_bootstrap.py` … Claude Code CLI を Max(OAuth) 認証で入れるブートストラップ（ハードニング版）。
- `configB_klein_multiref.py` … 構成B 本体。**チェックポイント付き**・本番と同じ識別器(antelopev2)で cos 計測・グリッド出力。

## 手順（Colab）
```python
# セル1: ブートストラップ（このリポの colab_bootstrap.py の中身を貼るか、Drive から実行）
#   事前: PC で `claude setup-token` → 出た sk-ant-oat... を Colab Secrets 名 CC_OAUTH_TOKEN に登録
%run /content/drive/MyDrive/aibo_lab/flux2_identity/colab_bootstrap.py

# セル2: 依存（隔離環境推奨）+ 重みを Drive にキャッシュ
import os
os.environ["HF_HOME"] = "/content/drive/MyDrive/aibo_lab/hf_cache"   # ★本番フォルダではない
!pip install -q "diffusers>=0.38" transformers accelerate safetensors \
    insightface onnxruntime-gpu sentencepiece pillow huggingface_hub

# セル3a: 成立性 + 入力健全性チェック（GPU 重み DL なし・速い）
#   ★ゼロ手動化: face-refs/prompts は既定で既存資産/プリセットを参照。司令部の手配置 不要。
#   self-check が「ref 存在 + 顔検出 + 同一人物性 + repo + import」を本走行の前に安く点検。
!python /content/drive/MyDrive/aibo_v7/experiments/flux2_identity/configB_klein_multiref.py \
    --self-check --scratch /content/drive/MyDrive/aibo_lab/flux2_identity/run

# セル3b: 第1走行（チェックポイント付き。落ちたら同じコマンドを再実行＝未完ジョブだけ継続）
#   baseline は第1走行スキップ（Klein 生成 + cosine + Klein グリッドのみ）。
!python /content/drive/MyDrive/aibo_v7/experiments/flux2_identity/configB_klein_multiref.py \
    --scratch /content/drive/MyDrive/aibo_lab/flux2_identity/run \
    --seeds 1234,5678,9012
#   ↑ 本人 ref が別セットなら --face-refs <dir> で上書き。プロンプト差替は --prompts <file>。
```

## ゼロ手動化の既定（司令部は input を置かない）
- `--face-refs` 既定 = **`/content/drive/MyDrive/aibo_v7/recon015_refs`**（read-only）。
  既存の実 face-ref 資産（RECON-015 が antelopev2 で使用済み・easy1-3/hard1-3 の6枚）。
  ※本番 config に「顔 id-ref の固定ディレクトリ定数」は無い（face_ref は実行時パス渡し設計）＝
  これは統括の提案既定。正規の本人セットが別なら司令部が `--face-refs` で指定（self-check が事前に点検）。
- `--prompts` 既定 = プロジェクトの **PORTRAIT/COORDINATE/SITUATION プリセット由来 4 本**（`DEFAULT_PROMPTS`）。`--prompts <file>` で上書き可。
- baseline = **第1走行スキップ**。第2走行で `--baseline-dir /content/drive/MyDrive/あいぼすたじお2/outputs/generated` を read-only 参照し「現行 vs Klein」グリッドを足す。

## 出力（すべて scratch 配下・逐次保存）
- `configB_images/b_pNN_sSEED.png` … 生成画像（1枚ずつ即保存＝CP）
- `results.jsonl` … 1ジョブ1行（cos / cos_best / vram / sec / status）。再開判定に使用
- `grid_configB.png` … 比較グリッド（キャラ ref | baseline | 構成B(seed毎, cos付き)）
- `summary.md` … cos 分布（mean/median/min/max・**別人率 cos<0.5**）+ 機械チェック
- `autofix_log.jsonl` … 自動修正の全ログ（何のエラーを・どう直したか・意味が変わってないか）
- `findings.md` … 入力未投入 or 「成立しない」時の正直な報告

## 入力（ゼロ手動化済み・司令部は配置しない）
- face-refs / prompts は上記の既定で既存資産・プリセットを read-only 参照。
- 既定 face-refs が空/パス誤りの時のみ `findings.md` に書いて停止（捏造しない）。`--self-check` が本走行の前に捕捉。
- 上書きしたい時だけ `--face-refs <dir>` / `--prompts <file>` / 第2走行で `--baseline-dir <dir>`。

## 厳守の実装対応（指示§3）
- **境界**: `--scratch` が `aibo_v7`/`AIBOV7` 配下なら起動時に停止（`assert_not_production`）。ref 読取は可。
- **機械的/β エラーは自動修正して完走**: OOM→VAE tiling+attention slicing 再試行 / bf16非対応→fp16 / cpu offload。**全部 autofix_log に記録**。
- **成立しない系は差し替えない**: `Flux2KleinPipeline` が import/load できない等は `findings.md` に正直に書いて STOP（FLUX.1 等に黙って替えない）。
- **知覚は自分で合格と言わない**: グリッド/サマリに「👁 PO 目視」「cos≠知覚的同一性」を明記。GO/NO-GO は司令部/PO。
- 識別器は本番と同一（`08_face_refiner.py` と同じ `FaceAnalysis(name="antelopev2")` / `normed_embedding` / cos）。

## 統括が PC 側で実証済み / 残る Colab 実機確認
**実証済み（このタブで確認）:**
- 既定 face-refs の6枚は全て妥当な画像（1080×2340 RGB・読込OK）。
- repo `black-forest-labs/FLUX.2-klein-base-4B` は **gated=False / 25 files**＝正名・ゲート無しでアクセス可（保留①解消）。
  `FLUX.2-klein-4B` も同等。`FLUX.2-klein-base-9B` は gated=auto（規約同意要）。
- multi-reference API は diffusers v0.38.0 公式 `Flux2KleinPipeline.__call__(image=list[PIL], prompt=...)`（docs 確認済み）。
- argparse 既定/別名（`--face-refs`＝`--ref-dir`）配線 OK。

**残る Colab 実機確認（GPU/insightface 要・self-check が捕捉）:**
1. **antelopev2 で6枚の顔検出が通るか + ref 同士が同一人物か**（self-check が per-ref 検出 + ペアワイズ cos で点検。別人混在なら WARN→本人セットへ）。
2. **list 渡しが顔同一性条件として効くか**（API 形は確定。効果＝本検証の目的。グリッドで PO 判定）。
3. **step/guidance**: base klein 前提 steps=50/guidance=4.0（diffusers 既定）。蒸留4-step は別 variant `Flux2KleinKVPipeline`（`FLUX.2-klein-9b-kv`）。今回 base 採用。
4. **bootstrap の Node/認証**: `claude doctor`＋往復スモークで自動確認するが Colab 実出力は実機で最終確認。
5. local diffusers は 0.37.1（<0.38）。**Colab 側で `diffusers>=0.38` を入れること**（セル2 済み）。
