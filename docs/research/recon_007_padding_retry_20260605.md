# RECON-007 — 案X(余白パディングリトライ)のセカンドオピニオン

- 日付: 2026-06-05
- 担当: ダイナミックくろうど(特殊部隊・偵察)
- 種別: コード調査 + 案レビュー(変更なし)。核非接触。
- 実証された真因(司令部報告・3実験 + 追加④):
  - ① 生画像 1080×2340(余白大)→ id_embeds=有 ✅
  - ② きついクロップ+1024×1024 正方形リサイズ(顔ドアップ)→ `facexlib align face fail` → id_embeds=無 ❌
  - ③ 余白多めクロップ+アスペクト維持 936×936 → `fail to detect face using insightface, extract embedding on align face` の後に抽出成功 → id_embeds=有 ✅
  - ④(追加・切り分け用)きついクロップ**だがリサイズなし(等倍)** → **本書 §1-bis の予測対象**。

---

## 結論(先に要点)

1. **真因は facexlib(FaceRestoreHelper 内 RetinaFace)のランドマーク検出失敗。主因は「余白不足=顔がフレームを占有/端で切れる」。正方形リサイズの歪みは“実 UI 経路では”主因ではない。**
   - 根拠: CropDialog は `aspect={1}`(crop-dialog.tsx:76)で **クロップ領域自体が正方形** → `cropAndResize`(image-utils.ts:46-56)は正方形→正方形を**等倍スケール**するだけで**歪まない**。③(936×936 正方形)も成功。→ **正方形であること自体は無害**。②と③の差は **余白量**。
   - `fail to detect face using insightface ...`(③でも出た)は **致命傷ではない**(insightface 不検出 → facexlib align 顔で代替する正常フォールバック)。**致命傷は `facexlib align face fail`**(②のみ)。

2. **案X(余白パディングリトライ)は真因に直接効く。バックエンド完結で API 直叩きも守る。副作用最小。→ 主対策として妥当。推奨。**
   - 既存リトライ(768px thumbnail 縮小・03:278-283)が効かない理由も判明: **縮小しても顔はフレームを占有したままで余白が増えない**。案X は「縮小」でなく「余白付加(レターボックス)」なのでここを是正する。

3. **「正方形リサイズをやめる/アスペクト維持」は UI 経路には不要**(`aspect=1` で既に無歪み)。API 直叩きで歪んだ画像が来る場合の保険としてのみ意味があり、それも **案X のレターボックス(等倍貼り付け)で歪み再導入なしに吸収**できる。

4. **品質劣化の懸念は無し**(③が shape=(1,32,2048) を取得済)。理由は §4。

---

## 1. facexlib align fail のメカニズム(公式 PuLID FLUX + facexlib 仕様)

`get_id_embedding` 本体はリポに無く、ランタイムで `/content/PuLID` に clone される公式 `pulid/pipeline_flux.py`(03:90, 124-129, 256 で import/呼び出し)。当方が呼ぶのは `03_identity_engine.py:256, 281`:
```python
id_embeds, uncond_embeds = self.pulid_pipeline.get_id_embedding(image_bgr, cal_uncond=True)
```
公式 `get_id_embedding` の流れ(要旨):
1. **antelopev2(insightface)`app.get(img)`** で顔検出 → 失敗すると `id_ante_embedding=None` になり **`fail to detect face using insightface, extract embedding on align face` を print** して align 顔から代替抽出するだけ(**非致命**)。
2. **facexlib `FaceRestoreHelper`**: `read_image` → `get_face_landmarks_5(only_center_face=True)` → `align_warp_face()`。内部検出器は **RetinaFace(retinaface_resnet50 等)**。顔/5点ランドマークが取れず `cropped_faces` が空だと **`raise RuntimeError('facexlib align face fail')`** ← ②の致命エラー。当方では `03:270 except Exception as e1` で捕捉される。

**なぜ「余白不足」で RetinaFace が落ちるか:**
- RetinaFace は WIDER FACE 系で学習され、**顔が画面の一部を占め周囲に文脈(背景)がある**前提のアンカー/特徴ピラミッド検出器。**顔がフレーム全体を占有し四辺で切れる**と、アンカーのスケール分布外+文脈境界の欠如で検出器が反応しない。facexlib は検出のため内部で固定サイズへリサイズするため、占有率の高い顔はさらにアンカー比が崩れる。
- → **主因は「顔の占有率が高すぎる/端で切れる(=余白不足)」**。正方形リサイズの歪みは、UI 経路では `aspect=1` のため発生せず主因ではない(歪み画像が来る API 直叩きでのみ副因たりうる)。

### 1-bis. 追加実験④(きついクロップ・リサイズなし)の位置づけと予測

④は **「余白不足」と「正方形リサイズ歪み」を分離する決定実験**。②から「1024 正方形リサイズ」だけを外し、**等倍のきついクロップ**を extract に通す。

- **予測: ④ も失敗(`pulid_used=False` / `_last_extract_error ≒ "facexlib align face fail"`)。**
  理由: リサイズを外しても **顔の占有率(余白不足)は②と同じ**。RetinaFace が落ちる主因は占有率なので、リサイズ有無に関わらず fail するはず。→ **「リサイズ歪みは主因でない / 余白が支配因子」を実証**でき、§結論1 と案Xの妥当性が確定する。
- もし **④が成功**したら、リサイズ歪みが主因だったことになり、案Xに加えて「アスペクト維持(正方形リサイズ廃止)」も必須になる。→ その場合は §6 の推奨を「案X(レターボックス)+ 送信側の等倍化」へ更新。
- 注意(④の解釈の前提): `_last_extract_error` は共有 extractor に残り**リセットされない**(RECON-006c)。④判定は **その generate 直後・他の extract を叩く前**に読むこと。最も確実なのは **サーバ/セルログの per-call 行**(`facexlib align face fail` か `✅ ID embedding 抽出完了` か)。
- ④の `IdentityConfig(reference_image=tight_noresize)` → orchestrator が **Phase0Sniper.snipe を二重掛け**(05:493)する点に注意。snipe が更にタイト化/素通りするので、④は「snipe 後の画像」での結果になる。**extractor 単体**で純粋にリサイズ要因だけ見たいなら `orchestrator.ie.pulid_extractor.extract(tight_noresize)` を直接叩く版も併走させると切り分けが綺麗(generate 版=本番経路、直接版=純粋要因)。

**現時点の判定**: ②(占有率高)fail / ③(余白あり)success、かつ UI は `aspect=1` で無歪み。これだけで既に **余白が支配因子**と結論できる。④はそれを ダメ押しで確証する実験。

---

## 2. 案X(余白パディングリトライ)の最適実装形

### 2-1. パディング色
- **推奨: 単色ニュートラルグレー(114,114,114 もしくは 127)**。検出器のレターボックス標準色で、偽エッジ/偽勾配を作らず RetinaFace が無視するよう条件づいている。
- 黒/白は人工的な強エッジを作り、顔が境界近くだと誤検出/未検出を誘発しうる → 非推奨。
- エッジ複製(BORDER_REPLICATE)は境界の引き伸ばし痕が顔近傍に出ると誤ランドマークの種になりうる → 第2候補(グレーで通らない時のみ試す)。
- **重要**: パディング色は **embedding 品質に影響しない**。facexlib `align_warp_face` がランドマークで顔だけを再切り出し→正準 512×512 にワープしてから EVA-CLIP/antelope に渡すため、**余白は最終 align 顔に含まれない**(§4)。色は“検出が通るか”だけに効く。

### 2-2. パディング量
- 目的: 顔占有率を RetinaFace の快適域(おおむね 30–60%)へ戻す。顔ドアップ(占有≒100%)から、**各辺へ画像サイズの ~50% を付加 → 正方キャンバス ≒ 2.0× → 顔占有 ≒ 50%**。③(余白多め)を再現。
- 推奨デフォルト: **正方レターボックス、辺長 = round(max(W,H) × 2.0)、顔を中央配置**。定数化(例 `_PAD_CANVAS_FACTOR = 2.0`)。
- 段階エスカレーション(任意): 2.0× で fail なら 3.0× を1回試す。**上限注意**: 付加し過ぎると facexlib 内部リサイズ後に顔が最小検出サイズを下回り逆に未検出になる。2.0–3.0× に留める。

### 2-3. 実装位置(★案X の肝)
- **`03_identity_engine.py:_extract_single` の例外リトライ枝(現 270-301)に「パディング再 extract」を追加/置換**。
  - `facexlib align face fail` は **RAISE** で来る → 既に `except Exception as e1`(270)で捕捉済み。現状はそこで **768 thumbnail 縮小**(278-283)= 余白が増えず効かない。ここを **レターボックス・パディング**に差し替える(または縮小の前段に入れる)。
  - **extract 内に置くと UI / API 直叩き / neutralize 全呼び出しを一律に救済**(バックエンド完結)。これが案Xの決定的長所。
- 実装イメージ(擬似コード・**コードは書かない**):
  ```
  except (align/extract 失敗) as e:
      side = round(max(W, H) * 2.0)
      canvas = new RGB (side, side) fill=(114,114,114)
      paste original at center  # 等倍・歪みなし=③の再現
      retry get_id_embedding(canvas_bgr, cal_uncond=True)
      # 必要なら canvas を ≤1280 等へ等倍ダウンスケール(顔ピクセルを大きく削らない範囲)
  ```
- 既存の 768 縮小リトライは **削除 or パディング後の二段目**に格下げ(縮小単独は無効と実証済)。

### 2-4. 正方形リサイズ/アスペクト
- UI 経路: `aspect=1` のため **歪み無し**。案X はレターボックス(等倍貼り付け)なので **歪みを再導入しない** → ③と同形を再現。
- API 直叩きで非正方・歪み画像が来る場合: 案X は「来た画像をそのまま中央に等倍配置」するので、既存の歪みは“消せない”が、**余白付加で大多数は救済**できる(②の主因は余白)。完全な歪み対策が要るなら §3 の併用で前段(送信側)を正す。

---

## 3. 案X vs 案3(CropDialog 緩和)vs 併用

| 観点 | 案X(バックエンド パディングリトライ) | 案3(フロント CropDialog 緩和) |
|---|---|---|
| 真因への効き | ◎ 余白を確実に付加(③再現) | ○ ズーム抑制/最小余白で発生率減 |
| カバレッジ | ◎ UI + **API 直叩き** + neutralize 全部 | △ UI のみ。API 直叩き/外部呼び出しは無防備 |
| ユーザー依存 | ◎ 無し(自動) | △ ユーザーのズーム操作に依存 |
| 副作用/blast radius | ◎ 失敗リトライ枝のみ。happy-path/Setting A/集約核 不触 | ◎ フロントのみ・核不触 |
| 初回コスト | ○ fail 時のみ +1 回 extract | ◎ 初回から余白で一発成功しやすい |
| 実装難度 | ○ extract 内に局所追加 | ◎ Cropper の既定ズーム/最小余白 |

- **案X は「確実性・カバレッジ・自動性」で優位**。バックエンド完結で API 直叩きも守るのが決定的(司令部指摘どおり)。
- **案3 は予防(発生率と初回リトライを減らす)として相補的**。`aspect=1` は維持(歪み防止に有効)しつつ、**既定ズームを下げる/最小余白を強制**する形が良い。`aspect` を変える必要は無い。
- **推奨: 案X を主対策(安全網)、案3 を副(発生率低減・初回高速化)で併用**。まず案X 単独でも症状は解消する見込み。

---

## 4. 落とし穴: 余白で顔が小さくなり embedding 品質が落ちないか

- **落ちない見込み(③で実証)**。facexlib `align_warp_face` は **ランドマークで顔のみ再切り出し→正準 512×512 にワープ**してから EVA-CLIP / antelope に渡す。最終 align 顔の解像度は **元の顔ピクセル解像度**で決まり、**周囲のパディングは align 顔に含まれない**。レターボックス(等倍貼り付け)なら顔ピクセルは縮まないので **品質はパディング無しと同等**。
- 唯一のリスク: パディング後に**全体を大きくダウンスケール**して顔ピクセルが facexlib の顔サイズ(既定 512)を大きく下回ると劣化/未検出。→ **ダウンスケールは控えめ(顔を512相当以上に保つ)**。2.0–3.0× レターボックスのみなら問題なし。
- ③が `shape=(1,32,2048)` を取得済 = **品質保持の実証**。

---

## 5. 実機1行の検証(案X の妥当性を即確認)

失敗した顔ドアップ b64(②再現相当)を1枚用意し、パディングで通るかを確認:
```python
from PIL import Image
img = b64_to_pil(failing_b64)                      # ②で落ちた顔ドアップ
W, H = img.size; side = round(max(W, H) * 2.0)
cv = Image.new("RGB", (side, side), (114, 114, 114))
cv.paste(img, ((side - W)//2, (side - H)//2))      # 中央・等倍=③再現(レターボックス)
ext = orchestrator.ie.pulid_extractor
print("raw :", ext.extract(img, bypass_pre_crop=False)[0] is not None)   # 期待 False(再現)
print("pad :", ext.extract(cv,  bypass_pre_crop=False)[0] is not None)   # 期待 True (案X有効)
```
- `raw=False / pad=True` なら **案X 有効が実証**。
- 量の当たりを見るなら `*1.5 / *2.0 / *3.0` を振って最小で通る倍率を確認(本番デフォルト決めに使用)。
- 色比較: `(114,114,114)` と `(0,0,0)` / `(255,255,255)` で通り方を比較(グレー優位の確認)。

### 5-bis. 実験④を「純粋要因」で読む補助1行(任意)
generate 経由(snipe 二重掛け)とは別に、extractor 単体で「リサイズ無し・余白無し」を直接確認:
```python
ext = orchestrator.ie.pulid_extractor
print("tight_noresize 直接:", ext.extract(tight_noresize, bypass_pre_crop=True)[0] is not None)  # 予測 False
```
- False なら「リサイズではなく余白が要因」を純粋に確証(§1-bis の予測どおり)。

---

## 6. 推奨(案・決定は司令部)

1. **案X を主対策**として `_extract_single` の失敗リトライ枝(03:270-301)に **グレー(114)・2.0× 正方レターボックスの再 extract** を実装(既存 768 縮小は二段目へ降格 or 削除)。バックエンド完結で全呼び出し救済。
2. **案3 を副**として CropDialog の既定ズームを下げる/最小余白を強制(`aspect=1` は維持)。発生率と初回リトライを削減。
3. 実装前に §5 の1行で「倍率・色」を、§1-bis の④で「真因(余白 vs リサイズ)」を実機確定 → 定数・方針に反映。
4. **核非接触の確認**: 本案は識別子抽出の前処理リトライのみ。Setting A 7値・PuLID embedding 集約(medoid/quality-weighted)・量子化核には一切触れない。例外を黙って捨てる握り潰しも作らない(リトライ後も失敗なら `_last_extract_error` に理由を残す現設計を踏襲)。

> 決定(実装可否・デフォルト値)は司令部。実装は統括下の実装くろうどへ。

---

## 参照(file:line)

- 抽出本体/リトライ: `03_identity_engine.py:191-301`(特に 256, 270-301 リトライ枝, 278-283 既存縮小)
- extractor 初期化/PuLID clone: `03_identity_engine.py:90, 124-129, 156-186`
- prepare→extract: `03_identity_engine.py:1526-1548`
- snipe 二重掛け(④解釈の注意): `05_orchestrator.py:474-501`(特に 493)
- フロント クロップ(無歪みの根拠): `frontend/components/aibo/crop-dialog.tsx:76`(`aspect={1}`)/ `frontend/lib/image-utils.ts:32-58`(`cropAndResize`)
- 受け渡し(API 直叩きも extract を通る): `09_fastapi_server.py:470-475, 518`
- 過去知見(PuLID import 系): `docs/research/recon_005_pulid_noinject_20260531.md:106`
