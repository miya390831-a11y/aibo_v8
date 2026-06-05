# RECON-006 — UI 経由で id_embeds=無 になる原因調査

- 日付: 2026-06-05
- 担当: ダイナミックくろうど(特殊部隊・偵察)
- 種別: コード調査のみ(変更なし)。Setting A / PuLID 集約核 / 量子化核 非接触。
- 出発点の確定事実:
  - `ie.pulid_extractor.extract(ref, bypass_pre_crop=False/True)` を直接呼ぶと両方 `emb is None=False`(抽出成功・error=None)。→ extractor / PuLID / モデル本体は正常。
  - UI(localhost:3000)で reference は毎回アップロード済(PO 確認)。だが UI 経由生成は `id_embeds=無`(`pulid_used=False`)。

---

## 結論(先に要点)

**「受け渡し経路(フロントのキー名 / base64 / data URL prefix)」は無傷。そこでは落ちていない。**
落ちているのは **orchestrator → extractor の内部**で、症状は次のどちらか:

- **本命(確度・高): `extract()` が「顔未検出」で None を返す。**
  UI 側でユーザーが顔ドアップにクロップした画像へ、orchestrator がさらに `Phase0Sniper.snipe()`(YOLO タイトクロップ)を二重に噛ませる。余白の無いタイト顔は PuLID 内部の InsightFace で検出できず None。
  → standalone テストは「生画像」で叩いたので成功し、UI だけ落ちる、という非対称が綺麗に説明できる。

- **対抗(確度・中): server の `ie.pulid_extractor` が `None`(PuLID ブロック丸ごと skip)。**
  `enable_pulid=False` か PuLID パイプライン縮退時。extract が一度も走らずに `pulid_used=False`。
  ※ ただし「`ie.pulid_extractor.extract` を直接呼べた」事実が *同一インスタンス* で得られたものなら、この対抗案は否定される。standalone を叩いた `ie` が server の live インスタンスか別プロセスの fresh かで切り分く(後述)。

**いずれも既存ログ `[OBS-SUMMARY]`(05_orchestrator.py:664-678)1 行で判別できる。** まずそこを読むのが最短。

---

## 受け渡し経路の精読(=ここは無傷、と確認した根拠)

参照画像 UI → FastAPI → orchestrator → extractor の各継ぎ目を行番号付きで追跡。すべて整合:

1. **フロント生成リクエスト構築** — `frontend/components/aibo/portrait-mode.tsx:227,246`
   - `validRefs = faceUploads.filter(non-null)` → `req.face_references = validRefs`。
   - `faceUploads` には CropDialog の結果が入る(`handleCropConfirm` → `setFaceUploads`、portrait-mode.tsx:186-194)。
   - クロップ出力は `cropAndResize(img, area, 1024, 0.92)`(crop-dialog.tsx:37)=**JPEG quality0.92 の data URL**。
2. **API クライアント** — `frontend/lib/api-portrait.ts:20-30, 105-112`
   - `GenerateRequest.face_references: string[]` を JSON body で `/api/portrait/generate` に POST。
3. **FastAPI 受信モデル** — `09_fastapi_server.py:177-178`
   - `class GenerateRequest(BaseModel): face_references: list[str]`。**キー名はフロントと完全一致**(`face_references`)。
4. **ルートハンドラ** — `09_fastapi_server.py:711-720`
   - `req` をそのまま `_run_portrait_generation(job_id, req)` に渡す。欠落・改名なし。
5. **base64 デコード** — `09_fastapi_server.py:425-429, 518`
   - `b64_to_pil` は `if "," in b64_str: split(",",1)` で **data URL prefix(`data:image/jpeg;base64,`)を正しく除去**。JPEG 出力と整合。
   - `face_imgs = [b64_to_pil(b64) for b64 in req.face_references if b64]`。
6. **空参照はハードフェイル** — `09_fastapi_server.py:514-520`
   - `if not req.face_references: raise ValueError(...)` / `if not face_imgs: raise(...)`。
   - → **参照が届いていなければ「生成が失敗」する**。実症状は「生成は走るが pulid_used=False」なので、**参照はバックエンドに届いている**(transport ドロップは症状と矛盾=除外)。
7. **config セット** — `09_fastapi_server.py:470-475`(`_build_configs`)
   - `id_cfg.reference_image = face_imgs[0]`、複数時のみ `reference_images`。単数時 `reference_images=None`。
8. **get_reference_images** — `01_config.py:414-420`
   - `reference_images` が truthy ならそれ、なければ `[reference_image]`、両方無しのみ `[]`。**手順7 で reference_image は必ずセット済**なので `[]` にはならない。

→ 1〜8 のどこにもキー不一致・prefix 取りこぼし・None 化は無い。**経路は構造的に reference を落とせない**(落ちるなら手順6 でハードフェイル)。

---

## 内部(prepare / extract)で `pulid_used=False` が出る2つの口

### 本命 A: `extract()` が顔未検出で None(クロップ起因)

- 経路: `05_orchestrator.py:493`(`sniped_image = self.sniper.snipe(reference_image)`)
  → `:501` `identity_data = self.ie.prepare(id_cfg_for_extraction)`
  → `03_identity_engine.py:1535-1539` `extract(sniped画像, bypass_pre_crop=False)`
  → `:256` `get_id_embedding(...)` が None
  → `:263-265` `_last_extract_error = "get_id_embedding が None (顔未検出の可能性)"`
  → `prepare` は `id_emb is None` で PuLID 辞書を埋めない(`:1540` の `if id_emb is not None:` を素通り)
  → `05:502` `result.pulid_used = "id_embeds" in identity_data` = **False**、生成は継続。
- **standalone と UI の差分は「extract に渡る画素」**:
  - standalone: 生画像 → InsightFace 検出 OK。
  - UI: ① CropDialog でユーザーが顔ドアップ(余白少)→ ② orchestrator が `Phase0Sniper.snipe()` を二重掛け(05:493)。
  - `Phase0Sniper.snipe`(05:138-187)は YOLO 顔検出 → タイトクロップ。**顔未検出時は元画像をそのまま返す**(05:159-160, 186-187)ので「snipe が None を返す」事故ではない。問題は **出力が更にタイト/余白不足**になり、PuLID 内部 InsightFace(antelopev2)が検出できなくなること。
  - margin は `margin_ratio=0.4`(05:97-99)で 40% 付与されるが、UI の元クロップが既に顔ドアップだと付与しても全体が顔で埋まり検出マージン不足になりうる。`ultralytics` 未導入時は `lazy_init` が False で **snipe は素通り**(05:111-113,145-146)=UI のタイトクロップが生で extract に行く。
- **OBS シグネチャ**: `[OBS-SUMMARY]`(05:672-675)が
  `id_embeds : 無⚠️` / `↳ 失敗理由 : extract=get_id_embedding が None (顔未検出の可能性) / init=なし`。

### 対抗 B: server の `ie.pulid_extractor` が None(PuLID ブロック skip)

- `03_identity_engine.py:1476` `PuLIDExtractor(sys_cfg) if sys_cfg.enable_pulid else None`。
  `enable_pulid` 既定は True(`01_config.py:571`)。server は `07_main.py:198` で `IdentityEngine(sys_cfg)` を生成。起動 sys_cfg で `enable_pulid=False` なら **`self.pulid_extractor = None`**。
- その場合 `prepare` の `:1534 if self.pulid_extractor:` が False → **PuLID 抽出を一切やらず** id_embeds 無で返す(生成は IP-Adapter/ControlNet で継続)。
- 別ルートで `enable_pulid=True` でも **PuLIDFluxPipeline 構築失敗 → 素 FluxPipeline 縮退**(`04_pipeline_manager.py:500`)があり、注入経路が死ぬ。ただし extractor 自体は別物なので、これは「対抗 B'」として要観測。
- **OBS シグネチャ**: extract が走っていないので `_last_extract_error` は None のまま
  → `[OBS-SUMMARY]` が `↳ 失敗理由 : extract=なし / init=なし`。
- **留意**: 確定事実「`ie.pulid_extractor.extract` が直接成功」と矛盾しうる。standalone を叩いた `ie` が **server の live インスタンス**なら B は否定(extractor は非 None)。**fresh な別インスタンス**なら B 生存。要切り分け。

### 除外: 受け渡し経路(キー名 / base64 / data URL)

上記「受け渡し経路の精読」の通り、キー一致・prefix 処理・空参照ハードフェイルにより、transport では「生成は走るが id_embeds 無」を作れない。**症状と矛盾するため除外**。

---

## 実機で確認できる切り分け(数行)

1. **最短: server ログを読む。** 生成1回ごとに出る
   `05_orchestrator.py:664` の `[OBS-SUMMARY]` ブロックと `:518` の `[OBS-C]` を見る。
   - `失敗理由 : extract=get_id_embedding が None ...` → **本命 A 確定**(クロップ起因)。
   - `失敗理由 : extract=なし / init=なし` → **対抗 B**(extractor None / PuLID skip)。
   - `init=PuLID pipeline lazy_init 失敗: ...` → ロード/縮退系(B')。
2. **クロップ起因の直接確認(A の決め手)**: ブラウザ DevTools → Network → `/api/portrait/generate` の request body から実際に送った `face_references[0]` の b64 を取得。それを
   - (a) `b64_to_pil` で復元しそのまま `ie.pulid_extractor.extract()` に投入、
   - (b) `Phase0Sniper.snipe()` を通した後の画像で投入、
   の2回叩いて None になる側を見る。(b) だけ None なら snipe が、両方 None なら UI クロップ自体が原因。
3. **UI 操作での確認(A の傍証)**: CropDialog のズームを緩め、顔の周囲に余白を残して再生成 → `pulid_used=True` に変われば A 確定。
4. **B の切り分け**: server 起動ログで `[OBS-A] ... enable_pulid=<?>`(`04_pipeline_manager.py:521`)と、standalone test を叩いた `ie` が `attach_orchestrator` 済みの live インスタンスか別プロセスかを確認。

---

## 修正案(あくまで案・決定は司令部)

> いずれも Setting A / PuLID 集約核 / 量子化核 には触れない範囲の案。

- **案1(A 向け・低リスク)**: extract が None の時、`snipe` 前の原画像で 1 回だけリトライ。
  実装位置は orchestrator(05:501 付近、`id_cfg`(snipe 前)で `prepare` を再試行)か extract 側。余白付き原画で再検出。PuLID 核非接触・glue のみ。
- **案2(A 向け)**: UI 既クロップ検知時は `Phase0Sniper.snipe()` をスキップ、もしくは `margin_ratio` を上げる(05:97)。トレードオフ=「ベレー帽幻覚抑止」目的のタイトクロップが弱まる(05:16 のクロップ意図)。
- **案3(A 向け・フロントのみ)**: CropDialog に最小余白を強制 or 顔周囲ガイド(顔が枠いっぱいにならないよう制限)。バックエンド/核に一切触れない。
- **案4(B 向け・調査継続)**: server 起動の `enable_pulid` と PuLIDFluxPipeline 構築可否(04:500 ログ)を確認。縮退なら VRAM/ロード問題として別タスク化。

**推奨の方向性(案・非決定)**: まず切り分け手順1(ログ)で A/B を確定 → A なら案1(原画リトライ)が副作用最小。決定と実装着手は司令部 → 統括下の実装くろうど。

---

## 参照(file:line)

- フロント: `frontend/components/aibo/portrait-mode.tsx:186-194,227,246` / `frontend/lib/api-portrait.ts:20-30,105-112` / `frontend/components/aibo/crop-dialog.tsx:32-44`
- FastAPI: `09_fastapi_server.py:177-178,425-429,470-475,510-520,711-720`
- orchestrator: `05_orchestrator.py:97-99,138-187,475-502,518,656-678`
- identity engine: `03_identity_engine.py:191-300,1476,1507-1548`
- config: `01_config.py:414-420,571`
- pipeline: `04_pipeline_manager.py:500,521`
- main: `07_main.py:198`
