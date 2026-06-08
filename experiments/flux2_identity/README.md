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

# セル3a: まず成立性チェック（GPU 重み DL なし・速い）
!python /content/drive/MyDrive/aibo_lab/flux2_identity/configB_klein_multiref.py \
    --self-check --ref-dir /content/drive/MyDrive/aibo_lab/inputs/char_ref \
    --scratch /content/drive/MyDrive/aibo_lab/flux2_identity/run

# セル3b: 本走行（チェックポイント付き。落ちたら同じコマンドを再実行＝未完ジョブだけ継続）
!python /content/drive/MyDrive/aibo_lab/flux2_identity/configB_klein_multiref.py \
    --ref-dir      /content/drive/MyDrive/aibo_lab/inputs/char_ref \
    --baseline-dir /content/drive/MyDrive/aibo_lab/inputs/baseline \
    --prompts      /content/drive/MyDrive/aibo_lab/inputs/prompts.txt \
    --scratch      /content/drive/MyDrive/aibo_lab/flux2_identity/run \
    --seeds 1234,5678,9012
```

## 出力（すべて scratch 配下・逐次保存）
- `configB_images/b_pNN_sSEED.png` … 生成画像（1枚ずつ即保存＝CP）
- `results.jsonl` … 1ジョブ1行（cos / cos_best / vram / sec / status）。再開判定に使用
- `grid_configB.png` … 比較グリッド（キャラ ref | baseline | 構成B(seed毎, cos付き)）
- `summary.md` … cos 分布（mean/median/min/max・**別人率 cos<0.5**）+ 機械チェック
- `autofix_log.jsonl` … 自動修正の全ログ（何のエラーを・どう直したか・意味が変わってないか）
- `findings.md` … 入力未投入 or 「成立しない」時の正直な報告

## 入力（司令部 → 後追い投入可・skeleton は先行配置済み）
- `inputs/char_ref/` … キャラ顔 ref（複数可・読取専用）
- `inputs/baseline/` … 現行 FLUX.1+PuLID の出力サンプル（基準バー・**再生成しない**）
- `inputs/prompts.txt` … 評価プロンプト（1行1件 / `.json` の list も可）
- 未投入なら本走行は走らず `findings.md` に「投入待ち」を書いて止まる（捏造しない）。

## 厳守の実装対応（指示§3）
- **境界**: `--scratch` が `aibo_v7`/`AIBOV7` 配下なら起動時に停止（`assert_not_production`）。ref 読取は可。
- **機械的/β エラーは自動修正して完走**: OOM→VAE tiling+attention slicing 再試行 / bf16非対応→fp16 / cpu offload。**全部 autofix_log に記録**。
- **成立しない系は差し替えない**: `Flux2KleinPipeline` が import/load できない等は `findings.md` に正直に書いて STOP（FLUX.1 等に黙って替えない）。
- **知覚は自分で合格と言わない**: グリッド/サマリに「👁 PO 目視」「cos≠知覚的同一性」を明記。GO/NO-GO は司令部/PO。
- 識別器は本番と同一（`08_face_refiner.py` と同じ `FaceAnalysis(name="antelopev2")` / `normed_embedding` / cos）。

## ⚠ 統括からの保留（みやちんが Colab 実機で確定すること）
このタブは PC 上のため Colab 実機実行はできていない。下記は**初回 run で要確認**:
1. **`--repo-id` の正式名と gate**: 既定 `black-forest-labs/FLUX.2-klein-base-4B`。
   HF 上の正確なリポ名/利用規約同意(gate)を `--self-check` で確認（`model_info` がアクセス可否を返す）。
   別名候補: `FLUX.2-klein-4B` / `FLUX.2-klein-base-9B`。**勝手に別モデルへは替えない**＝findings で報告する設計。
2. **multi-reference API**: diffusers v0.38.0 公式 `Flux2KleinPipeline.__call__(image=list[PIL], prompt=...)` を採用（docs 確認済み）。
   実機で list 渡しが顔同一性条件として効くかは出力グリッドで判断（API 形は確定、効果は未知＝それが本検証の目的）。
3. **step/guidance**: base klein 前提で steps=50/guidance=4.0（diffusers 既定）。
   ※蒸留4-step は `Flux2KleinKVPipeline`(別 variant, `FLUX.2-klein-9b-kv`)。今回は base を採用。
4. **bootstrap の Node/認証**: `claude doctor` と往復スモークで自動確認するが、Colab の Node 版数・`claude doctor` の実出力は実機で最終確認。
