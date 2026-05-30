---
name: pulid-embedding
description: >
  PuLID の identity embedding の集約・参照処理に触れるときに使う。reference 画像から
  embedding を作る/集約する箇所、Phase A の集約ロジック、PuLIDExtractor、顔の identity を
  まとめる処理を編集・設計する時に発火。外国人化(西洋バイアス)対策の作業で特に重要。
allowed-tools: Read, Grep, Glob
---

# PuLID embedding 集約の作法

外国人化(西洋顔バイアス)対策の核心。embedding 集約は雑にやると burstiness で別人化する。

## 原則
- **単純 mean embedding は禁止**。複数 reference を `.mean(dim=0)` で平均しない。
- 使うのは: **quality-weighted 集約**(#002 Phase A)、または **cluster medoid**(Phase B)。
  品質や代表性で重み付け/代表点選択をする。
- **負の PuLID weight は使わない**。

## 処理順序(崩さない)
reference 画像 → Phase0Sniper(YOLOv8-face で顔クロップ・デフォルト ON)→ PuLIDExtractor
  → 集約(quality-weighted / medoid)→ PuLID 統合 → 生成

- Phase0Sniper は EVA-CLIP の背景誤認防止のため常時 ON。順序を入れ替えない。

## 手順
1. 集約ロジックを触る前に、現在の集約方式を Read で確認(単純 mean になっていないか)。
2. 変更する場合も quality-weighted / medoid の枠内で行う。
3. Setting A の ip_adapter_weight / pulid_sigma_* は値を変えない(setting-a-guard 参照)。
4. 設計を変える判断は司令部の領分。実装は決まった方式に従うだけ。

## 文脈
外国人化の主因推定: PuLID/IP-Adapter の西洋バイアス(高) + 単純 mean の burstiness(中)。
根本対応は A1/A3(Identity OS)で別途進行。ここでは集約品質を落とさないことが目的。
