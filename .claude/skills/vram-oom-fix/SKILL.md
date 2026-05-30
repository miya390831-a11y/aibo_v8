---
name: vram-oom-fix
description: >
  VRAM の OOM(out of memory)系エラーを診断・修正するときに使う。CUDA out of memory,
  torch.cuda.OutOfMemoryError, PuLIDFluxPipeline 構築時のメモリ枯渇、FluxPipeline への
  意図しない fallback、T5-XXL/EVA-CLIP ロードでの枯渇を扱う時に発火。
allowed-tools: Read, Grep, Glob, Edit, Bash
---

# VRAM OOM 診断・修正の作法

A100 40GB でも、ロード順序を誤ると OOM。既知パターンに沿って根本原因を潰す。

## 既知の典型
- PuLIDFluxPipeline 構築時に T5-XXL / EVA-CLIP をロードして枯渇 → 素の FluxPipeline に
  fallback してしまう(= PuLID 機能喪失)。これは「動いた風」で最悪。fallback を成功と誤認しない。

## 確認する対処(順に)
1. パイプライン構築の**前**に VRAM を明示 flush しているか(キャッシュ解放)。
2. ロード時に `low_cpu_mem_usage=True` を使っているか。
3. 構築後に `enable_model_cpu_offload()` を入れているか。
4. 競合する `.to(device)` を二重に呼んでいないか(offload と衝突する)。
5. Hyper-FLUX LoRA の注入順序が、pipeline 構築の前になっているか。

## 手順
1. トレースバックと該当ロード箇所を Read で特定(証拠を示す。推測で直さない)。
2. 上記1〜5のどれが欠けているかを言語化してから最小修正。
3. fallback 経路がある場合、fallback 時は明示ログを出す(silent に FluxPipeline 化させない)。
4. `try/except: pass` で握りつぶさない。例外は必ずログ化。
5. 修正後 `python -m py_compile` で構文確認。Colab 側の再 run は手動である旨を報告に明記。

## 禁止
Setting A 値の変更で OOM を回避しようとしない(setting-a-guard)。メモリ問題はロード設計で解く。
