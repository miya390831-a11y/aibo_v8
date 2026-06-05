# RECON-005 調査ログ — reference あり なのに faces_detected=0 / id_embeds=無(PuLID 未注入)

- 日付: 2026-05-31
- 種別: コード調査・原因特定のみ(**変更なし**・修正案は提示するが決定は司令部)
- 担当: ダイナミックくろうど(特殊部隊)
- 対象観測: OBS-C `pulid_used=False / id_embeds=無 / faces_detected=0`(seed 1495779812 / steps_pass1=8)
- 前提(正常): `pipe_base=PuLIDFluxPipeline` / `_hyper_flux_loaded=True`

---

## 0. 結論(先に要点)

1. **`faces_detected=0` は「検出失敗」ではない。** single-ref 経路では `_last_face_count` が
   **一度も書かれない**(初期化すらされない)。OBS-C のこの値は single-ref では**無意味/stale**。
   → 質問③の答え: **non-update どころか single-ref では never-update**。OBS-001 §5 の指摘の強化版。
2. **id_embeds=無 の真因は `PuLIDExtractor._extract_single()` が `(None, None)` を返したこと**。
   reference は Sniper で落ちていない(Sniper は失敗時も元画像を返す=ref は必ず生存)。
3. 最有力は **PuLIDExtractor 専用の `lazy_init()` 失敗**(`pipe_base` とは別物・独立にロードする)。
   失敗すると 30s の **cooldown サーキットブレーカー**が以後の生成も PuLID 無しにし続ける。
4. **silent fail(例外の握り潰し)は無い**。全失敗は error ログ + `_last_init_error`/`_last_extract_error`
   に記録される。**ただし OBS-C がその理由を出さない**ため「静かに失敗」に見えるだけ。
   → 質問④の答え: 握り潰しは無い。**観測の穴**(理由が表に出ない)。

---

## 1. id_embeds が identity_data に入る/入らないを決める場所(質問①)

### 決定点: `03_identity_engine.py:1525-1532`(`IdentityEngine.prepare`)
```
1525  if self.pulid_extractor:
1526      extract_input = ref_images if len(ref_images) > 1 else primary_ref
1527      id_emb, uncond_emb = self.pulid_extractor.extract(extract_input, bypass_pre_crop=False)
1531      if id_emb is not None:
1532          prepared["id_embeds"] = id_emb      # ← ここでだけ id_embeds が入る
```
- `id_embeds` が入る条件は **`self.pulid_extractor` が真** かつ **`extract()` が非 None を返す**の2つだけ。
- どちらか欠けると `prepared` に `id_embeds` は入らない → 下流が PuLID 無しになる。

### 受け取り側
- `05_orchestrator.py:501-502`: `identity_data = self.ie.prepare(...)` → `result.pulid_used = "id_embeds" in identity_data`。
- `05_orchestrator.py:518`: OBS-C ログ(`id_embeds=有/無` と `faces_detected` をここで出す)。
- `03_identity_engine.py:1658`: `attach_to_pipeline` も `if "id_embeds" not in identity_data: return False`。
  → id_embeds 無なら注入も skip。

### `self.pulid_extractor` は None か?
- OBS-C は `getattr(getattr(self.ie,'pulid_extractor',None),'_last_face_count','n/a')`(05:518)。
  **`faces_detected=0` が出た = pulid_extractor オブジェクトは存在する**(None なら `'n/a'` になる)。
  → 「extractor が None」線は否定。**extract() が None を返した**のが本筋。

---

## 2. reference が UI → orchestrator → 顔抽出に渡る経路(質問②・行番号付き)

| 段 | 場所 | 挙動 |
|---|---|---|
| UI 受信 | `09_fastapi_server.py:428-429` | base64 → `Image.open(...).convert("RGB")` |
| Config 構築 | `09_fastapi_server.py:470-475` | `id_cfg.reference_image = face_imgs[0]`。顔1枚なら **`reference_images=None`**(=single-ref) |
| Sniper | `05_orchestrator.py:492-496` | single-ref は `sniped_image = self.sniper.snipe(reference_image)` → `id_cfg_for_extraction.reference_image = sniped_image` |
| **Sniper 失敗時** | `05_orchestrator.py:146 / 160 / 187` | **常に元画像を返す**(None を返さない)。YOLO 無/顔未検出/例外でも ref は生存 |
| prepare | `03_identity_engine.py:1517-1520` | `ref_images = get_reference_images()`。空なら早期 return(今回は非空) |
| 単/複分岐 | `03_identity_engine.py:1526` / `:209-215` | len==1 → `_extract_single`、len>1 → `_extract_quality_weighted` |
| 抽出本体 | `03_identity_engine.py:256` | `self.pulid_pipeline.get_id_embedding(image_bgr, cal_uncond=True)` |

- `get_reference_images()`(`01_config.py:414-420`): `reference_images` 優先、無ければ `[reference_image]`、両方無で `[]`。
- **reference が「落ちる」箇所は実質無い**(Sniper が None を返さない設計)。
  → ref 喪失説は否定。**抽出器内部(`_extract_single`)で None 化**しているのが結論。

---

## 3. faces_detected=0 は「検出失敗」か「single-ref non-update」か(質問③)

**single-ref non-update(かつ never-update)が正解。検出失敗の証拠ではない。**

- `_last_face_count` が書かれるのは **`03_identity_engine.py:310`** の1箇所だけ:
  ```
  309  faces = face_app.get(img_bgr)
  310  self._last_face_count = len(faces) if faces else 0
  ```
  これは **`_compute_quality_score()`** 内(296-333)。
- `_compute_quality_score()` を呼ぶのは **`_extract_quality_weighted()`(multi-ref 経路)の 361 行だけ**。
- **single-ref 経路(`_extract_single`)は `_compute_quality_score` を一切呼ばない** → `_last_face_count` は更新されない。
- さらに `PuLIDExtractor.__init__`(92-103)は **`_last_face_count` を初期化していない**。
  → 純 single-ref のみのセッションでは属性が存在せず OBS-C は本来 `'n/a'`。
    `0` が出ているなら **過去の multi-ref 実行が残した stale 値**(前回 0 検出)を引きずっている可能性。
- 実際の顔検出は **公式 `get_id_embedding` の内部**(antelopev2)で行われ、`_last_face_count` には反映されない。

→ **OBS-C の faces_detected は single-ref では「今回の検出結果」を表していない。** 判断材料にしてはいけない。

---

## 4. silent fail(握り潰し)の有無(質問④)

**例外を黙って捨てる型(silent fail)は PuLID 抽出経路に無い。** すべて error ログ + 理由文字列を残す。
ただし理由が **OBS-C に出ない**ため「静かに失敗」に見える。失敗点と記録先:

### `_extract_single`(`03_identity_engine.py:238-292`)
- `:240-243` `lazy_init()` 失敗 → `_last_extract_error="PuLID pipeline lazy_init 失敗: <reason>"` を残し return None。
- `:265-292` `get_id_embedding` が 1st + 768px リトライ両方で例外 → warning/error + `_last_extract_error` に記録、return None。
- ⚠️ **見落としやすい点(C3)**: `get_id_embedding` が**例外を出さず None を返す**と、
  `:261` の `shape_str` が `"?"` になり `:262` で **`✅ ID embedding 抽出完了: shape=?`** という
  **誤解を招く成功ログ**を出したうえで、prepare の `if id_emb is not None` が False になる。
  → 「✅完了と出てるのに id_embeds 無」はこのケース。

### `lazy_init`(`03_identity_engine.py:107-186`)— extractor 専用・`pipe_base` とは別物
- `:113-121` **cooldown ブレーカー**: 直近30s 以内に失敗していると**再試行せず False**(前回エラーを warning 表示)。
- `:130-140` `from pulid.pipeline_flux import PuLIDPipeline` 失敗(numpy2.x×scipy/insightface, facexlib 不一致)。
- `:162-166` `PuLIDPipeline(...)` インスタンス化失敗(InsightFace antelopev2 / EVA-CLIP / BiSeNet の自動 DL 失敗)。
- `:171-182` `hf_hub_download(guozinan/PuLID, pulid_flux_v0.9.0.safetensors)` 重みロード失敗。
- いずれも `_last_init_error` + `_init_fail_time` を立て、`logger.error` を出す(握り潰しではない)。

> **重要**: extractor の `pulid_pipeline` は `pipe_base`(PM の PuLIDFluxPipeline)とは**独立にロード**する。
> よって「pipe_base 正常」でも extractor の lazy_init は独立に失敗しうる。今回の最有力線。

---

## 5. 原因候補(行番号付き・確度順)

- **C1(最有力): PuLIDExtractor.lazy_init() 失敗** → `_extract_single` が `03:240-243` で None。
  - 内訳: import 失敗(`:130`)/ インスタンス化失敗(`:162`, InsightFace/EVA-CLIP/BiSeNet)/ 重み DL 失敗(`:178`)。
  - cooldown(`:113-121`)で以後30s も PuLID 無しが継続。
  - **ログの目印**: `❌ [PuLIDExtractor] ... 失敗` または `⏳ [PuLIDExtractor] lazy_init cooldown 中`。
  - Case-A/G1 との接続: extractor は antelopev2/EVA-CLIP/BiSeNet を内部 DL する。Case-A の cache が
    Drive FUSE 直結(G1 の H1)だと mmap/DL 失敗でここが落ちる可能性。
- **C2: get_id_embedding が例外**(公式 antelopev2 が顔未検出 or 解析失敗)→ `03:265-292`。
  - **ログの目印**: `⚠️ [PuLIDExtractor] 1st attempt 失敗` + `❌ ... リサイズ後リトライも失敗`。
- **C3: get_id_embedding が例外なく None を返す** → `03:256-263`。
  - **ログの目印**: `✅ [PuLIDExtractor] ID embedding 抽出完了: shape=?`(shape が `?` / None)。

---

## 6. 切り分け方法(実機で1行・確度高い順)

```python
# (推奨・最速) extractor の内部状態を直接見る — どの候補かが即わかる
ie = orchestrator.ie
print("initialized=", ie.pulid_extractor._initialized,
      "| last_init_error=", getattr(ie.pulid_extractor, "_last_init_error", None),
      "| last_extract_error=", getattr(ie.pulid_extractor, "_last_extract_error", None))
```
- `_initialized=False` かつ `_last_init_error` に文字列 → **C1 確定**(その文字列が import/インスタンス化/重みのどれか教える)。
- `_initialized=True` だが `_last_extract_error` に "1st: ... / resize-retry: ..." → **C2 確定**。
- `_initialized=True` で両 error とも None なのに id_embeds 無 → **C3 確定**(get_id_embedding が None)。

補助(ログ grep・1行):
```
grep -E "\[PuLIDExtractor\]" <そのrunのログ>   # ✅完了/⚠️1st失敗/❌リトライ失敗/⏳cooldown/重みロード失敗 のどれが出たか
```

---

## 7. 修正案(あくまで案・決定は司令部・コード変更は確認後)

> いずれも **観測性・診断の改善**であり、PuLID 集約ロジック / Setting A / 量子化核には触れない。

- **FIX-1(最優先・観測性): OBS-C に失敗理由を出す。**
  `05_orchestrator.py:518` の OBS-C ログに `_last_init_error` / `_last_extract_error` を併記。
  「無」だけでなく「なぜ無か」が一目で分かる(司令部の判断材料に直結)。
- **FIX-2(faces_detected の正直化): single-ref でも検出数を出す。**
  `_last_face_count` を `__init__` で初期化(例: `None`)し、single-ref でも実検出数を記録 or
  OBS-C 側で single-ref のときは `'n/a(single-ref)'` と明示(OBS-001 §5 の恒久対策)。
  ※ 検出値そのものを集約に使わない(誤用防止)。
- **FIX-3(C3 の誤解ログ修正): None 返り時に成功ログを出さない。**
  `03:261-262` で `id_embeds is None` の時は `✅完了 shape=?` ではなく
  `⚠️ get_id_embedding が None(顔未検出の可能性)` を出す。
- (任意)C1 が Case-A の cache(G1 H1)起因なら、**根治は G1 FIX-1**(/content を実 NVMe 化)。
  本 RECON-005 はその診断可視化を担保する位置づけ。

---

## 8. 司令部判断が要る点(保留)
1. まず **§6 の1行**で C1/C2/C3 を確定 → 真因に応じて FIX を選択。
2. FIX-1〜3 の採否(全て観測性寄りで低リスク。PuLID 核心は不変)。
3. C1 が cache 起因なら G1(Drive FUSE)と一体で対処するか。
4. 実装は確定後に**統括下の実装くろうど**へ(偵察と本体改修の分離)。

## 9. スコープ遵守
- 調査・原因特定のみ。**コードを1行も変更していない**(03/05/09/01 は読のみ)。
- Setting A / PuLID 集約核 / 量子化核に非接触。提示は「案」で決定は司令部。
