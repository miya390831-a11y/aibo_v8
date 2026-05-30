---
name: setting-a-guard
description: >
  AIBO のパイプライン定数(Setting A の7値や生成パラメータ)に触れる作業のときに使う。
  04_pipeline_manager.py / 05_orchestrator.py / config 系を編集・調整しようとする時、
  GFPGAN_STRENGTH, ip_adapter_weight, pulid_sigma_start/end, cn_depth_guidance_end,
  pass2_strength, pass2_pulid_boost のいずれかが視野に入る時に発火する。
allowed-tools: Read, Grep, Glob
---

# Setting A 保護の作法

AIBO の Setting A は実機で焼き付け済みの7値。変更は禁止(司令部の明示決定がない限り)。
パイプライン定数に触れる前に必ずこの手順を踏む。

## 触れてはいけない7値
- GFPGAN_STRENGTH = 0.0
- ip_adapter_weight = 0.75
- pulid_sigma_start = 0.25
- pulid_sigma_end = 0.90
- cn_depth_guidance_end = 0.65
- pass2_strength = 0.34
- pass2_pulid_boost = 1.25

## 手順
1. 編集対象に上記の名前が含まれるか Grep で確認する。
2. 含まれる場合、その**値**を変更しない。周辺コードの修正でも、これらの代入行は保持する。
3. もし「値を変える必要がある」と判断したら、**実行を止めて司令部に確認を上げる**。自分で変えない。
4. 関連する禁止も併せて守る: PHASE3B_ENABLED=True 禁止 / pulid_double_interval 変更禁止 /
   負の PuLID weight 禁止。

## 注意
これは自発的な保護層。最終的には .errorfix/guard_forbidden.py(PreToolUse フック)が
値変更を機械的にブロックするが、その手前で自分で避けるのが正しい振る舞い。
