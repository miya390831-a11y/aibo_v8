# RECON-006c — extract 未到達の確定調査:reference → extract(03:1536) 区間の skip 分岐

- 日付: 2026-06-05
- 担当: ダイナミックくろうど(特殊部隊・偵察)
- 種別: コード調査のみ(変更なし)。核非接触。
- 前提(006c の実機確定とされた事実):
  - orchestrator/ie/pulid_extractor は FastAPI と Colab セルで完全同一(006b の `is` 比較 全 True)。
  - pulid_extractor は非 None。
  - UI 生成完走直後、`orchestrator.ie.pulid_extractor._last_extract_error` が None、`_last_face_count` が ATTR_MISSING。
  - これを根拠に「UI 生成経路は extract() に到達していない」と判断された。
  - セルで `extract(ref)` を直接叩くと成功する。

---

## 結論(先に要点)

1. **「extract 未到達」の根拠(`_last_extract_error=None` / `_last_face_count=ATTR_MISSING`)は、判定材料として無効。** これらは **`PuLIDExtractor.__init__` で初期化されていない**(03:92-103)。実行時にしか作られず、しかも **生成ごとにリセットされず共有 extractor に残り続ける**。
   - `_last_extract_error` は `_extract_single` の冒頭 `03:238` でしか「None」に設定されない。**= この属性が None で存在する時点で、過去に `_extract_single` が走って成功した証拠**。これは「**セルで直接叩いた `extract(ref)` の成功**」がそのまま残っているだけで説明できる(同一オブジェクトだから・006b)。
   - `_last_face_count` は `_compute_quality_score`(03:319、**複数枚 quality 集約パスでのみ呼ぶ**)でしか作られない。単一枚 extract では成功しても作られない → ATTR_MISSING は**単一枚なら正常**。「未到達」を意味しない。
   - **致命的な罠**: もし UI 生成が「顔未検出で None」(=本命A)だったとしても、その後にセルで `extract(ref)` を成功させると `_last_extract_error` が **None に上書き**され、A の痕跡(`"get_id_embedding が None..."`)が消える。手元属性での事後判定は順序汚染で信頼できない。

2. **reference → extract 区間に、extract を呼ばず PuLID を skip する「モード分岐」は無い。**
   - `ModeManager.apply`(05:205-247)は `id_cfg` を **その場で変更して同一オブジェクトを返すだけ**で、`reference_image` / `reference_images` には一切触れない(触るのは prompt/negative/width/height/controlnet_type/multi-cn のみ)。PORTRAIT で PuLID を切る分岐や IP-Adapter 優先で prepare を飛ばす分岐は**存在しない**。
   - `generate` は単一経路(PORTRAIT 専用の別生成メソッドは無い。05:399 の1本)。

3. **extract が本当に呼ばれない条件は1つだけ**: prepare 入口で `get_reference_images()` が `[]` を返す(03:1527-1528 早期 return)= **prepare に渡る `id_cfg` の `reference_image` も `reference_images` も両方 None**。だがコード経路上、FastAPI がセットした `reference_image` はここまで同一オブジェクトで届くはずで(下記トレース)、**通常は `[]` にならない**。

→ **最有力は「extract には到達しており、顔未検出で None(=RECON-006 本命A)。手元属性が直接テストで上書きされ、未到達に見えていた」。** 真偽はサーバログ(per-call・上書き不能)で一意に判定できる(§4)。

---

## 1. reference → extract のトレース(同一オブジェクトで流れる)

- `09_fastapi_server.py:470-475`(`_build_configs`): `id_cfg.reference_image = face_imgs[0]`(単一時 `reference_images=None`)。
- `09:528,549`: `gen_cfg, id_cfg = _build_configs(...)` → `orch.generate(gen_cfg, id_cfg, mode=PORTRAIT)`。**差し替えなし**。
- `05_orchestrator.py:430`: `gen_cfg, id_cfg, mode_cfg = self.mode_manager.apply(mode, gen_cfg, id_cfg)`。
  - `apply`(05:205-247)は **in-place 変更し同じ `id_cfg` を返す**。`reference_image`/`reference_images` 不変。→ 別オブジェクトに差し替わらない・reference 落ちない。
- `05:477` `if id_cfg.reference_images and len(...)>0:` … 単一時は None で skip。
- `05:492` `elif id_cfg.reference_image is not None:` … **ここで snipe → `IdentityConfig(**asdict(id_cfg))` でコピー → `reference_image=sniped`**(495-496)。reference_image が None ならここを外れ `05:498 else: id_cfg_for_extraction = id_cfg`。
- `05:501` `identity_data = self.ie.prepare(id_cfg_for_extraction)`。
- `03:1526-1528` prepare 入口: `ref_images = get_reference_images()`; `if not ref_images: return prepared`(=**extract skip・error 設定なし**)。
- `03:1534` `if self.pulid_extractor:`(非 None 確認済) → `03:1536` `extract(...)`。

→ extract を skip できるのは **`get_reference_images()==[]`(03:1527)** か **pulid_extractor falsy(03:1534、否定済)** のみ。前者は **prepare 入口で reference_image・reference_images が両方 None** の時だけ(01:414-420)。

## 2. get_reference_images が [] を返す条件(01:414-420)

```python
def get_reference_images(self):
    if self.reference_images: return self.reference_images   # None/空なら skip
    if self.reference_image:  return [self.reference_image]  # PIL は常に truthy
    return []                                                # 両方 None の時だけ
```
- PIL Image は常に truthy なので、`reference_image` が None でない限り `[]` にはならない。
- **`[]` になる = prepare に渡った `id_cfg` の reference が両方 None**。FastAPI でセットしているので、ここが None なら「セット後〜prepare までで None 化」or「別 id_cfg がprepareに渡った」を意味する。だが §1 の通りコード上は同一オブジェクトで reference 保持。→ **このシナリオは考えにくい(要ログ確認)**。

## 3. 「extract 未到達」を示す手元属性が無効な理由(03:92-103)

`PuLIDExtractor.__init__`:
```python
self._initialized = False
self._last_init_error = None        # ← これは初期化される
self._init_fail_time = None
# _last_extract_error は設定しない    ← __init__ に無い
# _last_face_count    は設定しない    ← __init__ に無い
```
- `_last_extract_error`: 生成存在は `_extract_single` 実行時(03:238 で None 化、失敗時 264/288/295/299 で文字列化)。**初期化されないので「属性が存在する」だけで `_extract_single` が過去に走った証拠**。値 None = 直近の `_extract_single` が成功(or 入口通過後エラー無し)。
- `_last_face_count`: `_compute_quality_score`(03:305-319、**複数枚パス専用**)でのみ生成。単一枚では成功しても作られない。
- どちらも **per-generation リセット無し**(orchestrator 460-502 に reset コード無し)。共有 extractor に残るため、**直接テストの結果や前回生成の結果が混入**する。
- → 手元属性での事後判定は **順序汚染**で不正確。特に「セルで extract 成功させた」後は `_last_extract_error` が必ず None になる。

---

## 4. 実機で一意に判定する方法(サーバログ=上書き不能の一次情報)

手元変数ではなく **FastAPI 稼働スレッドのログ**を見る。各生成で per-call 行が出る。

**(A) その生成1回ぶんのログを grep(最有力の判別):**
```bash
# 直近生成のログから extract 到達/結果を確認
grep -E "\[PuLIDExtractor\]|\[OBS-C\]|\[OBS-SUMMARY\]|失敗理由|PORTRAIT 経路|Multi-CN 経路" <server.log> | tail -40
```
判定:
- `✅ [PuLIDExtractor] ID embedding 抽出完了: shape=...`(03:267)が出る → **extract 到達・成功**。なのに `pulid_used=False` なら、原因は **prepare return 後〜`result.pulid_used` までの下流**(要追加調査)。
- `⚠️ [PuLIDExtractor] get_id_embedding が None (顔未検出の可能性)`(03:264/288)が出る → **extract 到達・顔未検出 = RECON-006 本命A 確定**(UI クロップ + Phase0Sniper 二重クロップ)。「未到達」は誤判定。
- 上記 `[PuLIDExtractor]` 行が **両方とも出ず**、`[OBS-C] ... id_embeds=無`(05:518)だけ出る → **extract 真に未到達** = `get_reference_images()==[]`(reference が prepare 前で None 化)。§5 の追加確認へ。
- `[OBS-SUMMARY]` の `↳ 失敗理由 : extract=... / init=...`(05:673-675)は **その生成時点の値を生成時に出力**しているので、後の手動テストに汚染されない最良の一次情報。

**(B) reference が prepare 入口で生きているかを、生成1回だけ覗く1行(任意・観測のみ):**
セル側で生成を投げる直前に extractor をラップせず、prepare 入口の値をログで見たい場合は **サーバログの上記行で十分**。どうしてもオブジェクトで見たいなら、生成直後(かつ手動 extract を叩く前)に:
```python
# UI生成を1回完走 → 直後・他の extract を叩く前に実行
ext = orchestrator.ie.pulid_extractor
print("err:", getattr(ext,"_last_extract_error","MISSING"))   # 'get_id_embedding が None...' なら A
# ↑ ただし、この後に手動 extract(ref) を叩くと None に上書きされる点に注意
```

---

## 5. extract が真に未到達だった場合のみ追う追加確認(reference None 化)

ログで「extract 未到達」が確定したときだけ、prepare に渡る reference が None になる箇所を潰す:
- 生成リクエストの実 body を確認(DevTools → `/api/portrait/generate`)。`face_references` が空配列で来ていないか(空なら 09:514 でハードフェイルのはずなので、来ている前提)。
- 複数スロット時の挙動: `face_references` が2枚以上なら `_build_configs` で `reference_images` がセットされ、orchestrator 477 の **複数枚パス → `_extract_quality_weighted`** に入る。これは `_compute_quality_score` を呼ぶので `_last_face_count` が**作られる**。今回 ATTR_MISSING = **複数枚パスは通っていない**(=単一枚 or extract 未到達)。
- `IdentityConfig(**asdict(id_cfg))`(05:487/495)はコピーだが reference を明示再設定しているので落ちない。

---

## 修正案(あくまで案・決定は司令部)

> いずれも Setting A / PuLID 集約核 / 量子化核 非接触。

- **案1(観測の信頼性・最優先)**: `PuLIDExtractor.__init__` に `self._last_extract_error = None` / `self._last_face_count = None` を初期化として追加し、**`generate` の prepare 直前で per-generation リセット**する観測フックを入れる。これで手元属性が「その生成の真値」を表すようになり、順序汚染が消える。観測性のみ・核不変。
- **案2(本命A だった場合)**: RECON-006 の案(extract が None の時に snipe 前原画でリトライ / UI 既クロップ時 snipe スキップ / CropDialog に最小余白)。
- **案3(真の未到達だった場合)**: prepare 入口・orchestrator 492 直前に「reference 有無」の1行ログを足し、reference が None 化する地点を確定 → 該当箇所を是正。

**推奨の段取り(案・非決定)**: まず §4(A) のサーバログ grep で「到達・成功 / 到達・顔未検出 / 真の未到達」を三択判定。ほぼ確実に「到達・顔未検出(本命A)」になるはず。手元属性は案1を入れるまで判定に使わない。

---

## 参照(file:line)

- mode 分岐(reference を落とさない証明): `05_orchestrator.py:399-430, 205-247`
- snipe→prepare: `05_orchestrator.py:474-501`
- prepare 早期 return / extract gate: `03_identity_engine.py:1524-1536`
- get_reference_images: `01_config.py:414-420`
- 手元属性が初期化されない証明: `03_identity_engine.py:92-103`(__init__)、設定箇所 `238, 264, 288, 295, 299, 319`
- per-call ログ(一次情報): `03_identity_engine.py:251, 264, 267` / `05_orchestrator.py:518, 656-678`
- FastAPI 経路: `09_fastapi_server.py:470-475, 528, 549, 514`
