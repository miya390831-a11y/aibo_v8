# IMPL-008 設計案 — CropDialog 顔きつすぎクロップの根治(フロント・案3)

- 日付: 2026-06-05
- 種別: 設計案(調査+方針)。**実装は司令部承認後**(指示「方針を上げてから実装」)。
- スコープ: フロントのみ(`frontend/`)。バックエンド/PuLID 核/Setting A 非接触。

---

## 1. 調査結果(現状のクロップ挙動)

### 対象ファイル
- `frontend/components/aibo/crop-dialog.tsx` — クロップ UI(react-easy-crop)
- `frontend/lib/image-utils.ts` — `cropAndResize()` 実体
- 使用箇所: `frontend/components/aibo/portrait-mode.tsx`(`handleCropConfirm` で
  出力 b64 を face_references スロットに格納 → 生成時 backend へ送信)

### 現状フロー
1. `react-easy-crop` の `<Cropper aspect={1} zoom 1→3 objectFit="contain">`。
   - ズームは **slider で 1〜3 倍**(crop-dialog.tsx:88-96, max=3)。
2. `onCropComplete` で `croppedAreaPixels`(元画像ピクセル座標の矩形)を保持。
3. 確定時 `cropAndResize(img, croppedAreaPixels, 1024, 0.92)` で
   その矩形を 1024×1024 にdrawImage → JPEG b64(image-utils.ts:32-58)。
4. b64 が face_reference として backend に渡る。

### 問題点(確定)
- **顔サイズを一切認識していない**。ユーザーが「顔を中央に」と促され(crop-dialog.tsx:100)
  顔へズーム → crop 矩形が顔ドアップになり、出力で顔が枠ほぼ100%。
- → backend generate 内 snipe で二重クロップ → facexlib align face fail → PuLID 無注入。
- グレー余白では facexlib が通らない(実証)= **実画像コンテキスト(髪・首・肩)が必要**。

---

## 2. 実証パラメータの解釈(重要・バンドである)

実機段階テスト: **0.22/0.30 = fail、0.40/0.55/0.70 = success**。
IMPL-007 実証(余白あり原画=成功 / ドアップ≈100%=fail)と合わせて読むと:

- facexlib が通る「顔/枠 比率」には **下限と上限の両方がある = バンド**。
  - 顔が大きすぎ(ドアップ ≈100%)→ fail(align のランドマーク周辺余白不足)
  - 顔が小さすぎ(0.22/0.30、グレー余白で顔が極小)→ fail(顔が小さすぎて align 不能)
  - 成功帯 ≈ **顔が枠の 0.40〜0.70**、**安全目標 ≈ 0.50**。
- → 「とにかく広げる」だけでも駄目(広げすぎると下限割れで fail)。
  **実画像コンテキスト込みで顔を ~0.50 に“着地”させる**のが要件。

この「バンド」性が設計判断の肝。固定倍率で一律拡張すると、もともと緩めに
切った人は顔が小さくなりすぎてバンド下限を割る恐れがある。

---

## 3. 案(a)(b) の比較と判断

### (a) クロップ枠の最小サイズ制限(maxZoom 下げ等でズーム上限を絞る)
- 実装: react-easy-crop の `maxZoom` を 3→低めに。
- 長所: 最小実装。
- 短所: **顔サイズを知らないため「顔 ≤50%」を保証できない**。
  元画像内の顔の大きさ次第で、ズーム上限を絞っても顔が枠を占める比率は不定。
  ⇒ 「確実」ではない。UX も劣化(寄れない)。

### (b) 確定クロップを中心に元画像から実コンテキストを含めて枠拡張 ★推奨
- 実装: `handleConfirm` で `croppedAreaPixels` を**中心固定で拡張**してから
  `cropAndResize` に渡す。拡張は元画像の実ピクセルをサンプル(グレー余白を作らない)、
  元画像の範囲にクランプ(はみ出し時は枠を内側にシフト/上限は min(W,H))。
- 長所:
  - **最も実装が容易**: `croppedAreaPixels` の後処理だけ。react-easy-crop の再設定不要・
    新規依存なし・フロントのみ・npm run dev でホットリロード。
  - **要件に直接効く**: ユーザーの crop ≒ 顔枠 とみなし、出力で顔を ~0.50 に着地。
    UI は「顔を枠に」と促す設計なので、失敗母集団(きつい crop)では crop ≒ 顔枠が成立。
  - グレー余白を作らず実画像コンテキスト(髪・肩)を取り込む(実証要件を満たす)。
- 短所/残リスク:
  - 顔サイズ非認識のため、**もともと緩く切った人**は拡張でバンド下限(0.40)を割る可能性。
    → 後述の倍率選定とクランプで実害を最小化。

### 判断: **(b) を推奨**(実装容易 × 要件直撃 × 新規依存なし)。
(a) は単体では「確実」要件を満たさないため不採用。必要なら (a) を (b) の補助
(極端な寄りを防ぐ maxZoom ガード)として併用も可。

---

## 4. (b) の実装方針(詳細・承認後に着手)

### 4.1 変更箇所(フロントのみ)
- `frontend/lib/image-utils.ts`: 矩形拡張ヘルパ `expandCropWithContext()` を新設
  (純関数・テスト容易)。
- `frontend/components/aibo/crop-dialog.tsx`: `handleConfirm` で
  `cropAndResize` 呼び出し前に `expandCropWithContext()` を挟む。
- `cropAndResize` 自体は不変(描画ロジックは触らない)。

### 4.2 拡張ロジック(擬似コード)
```
expandCropWithContext(crop, imgW, imgH, factor):
    cx = crop.x + crop.width/2
    cy = crop.y + crop.height/2
    side = max(crop.width, crop.height) * factor      # aspect=1 を維持(正方)
    side = min(side, imgW, imgH)                       # 画像より大きくしない
    x = clamp(cx - side/2, 0, imgW - side)             # はみ出しは内側へシフト
    y = clamp(cy - side/2, 0, imgH - side)
    return { x, y, width: side, height: side }
```
- `factor` の選定(バンド [0.40,0.70] に着地させる):
  - 失敗母集団のきつい crop(顔≈0.75〜1.0)を狙う。
    - factor=1.6 → 顔1.0→0.625 / 0.75→0.47(共にバンド内)
    - factor=2.0 → 顔1.0→0.50 / 0.75→0.375(0.75 はやや下限割れ)
  - **推奨 factor ≈ 1.6〜1.8**(きつい crop を確実にバンド内へ。緩い crop の
    下限割れリスクを抑える)。実機で 1〜2 枚試し微調整。初期値は **1.7** を提案。
- 1:1 維持(side で正方)。グレー余白を作らない(常に実画像クランプ)。

### 4.3 これで満たす要件
- 顔がドアップ(≈100%)でも、確定後に中心拡張 → 顔 ~0.5、髪/肩の実コンテキスト同梱
  → facexlib align 成立 → PuLID 注入。
- backend(IMPL-007 原画リトライ)との二段保険: フロントで根治しつつ、
  万一すり抜けても backend が原画リトライで拾う。

### 4.4 残リスクと将来オプション(司令部判断材料)
- 固定倍率は顔サイズ非認識のため**完全保証ではない**(緩い crop で下限割れの可能性)。
- **完全保証が要るなら**: フロントに軽量顔検出(ブラウザ実験的 `FaceDetector` API、
  または mediapipe/face-api.js)を入れ、実顔枠を測って顔を ~0.50 に正確に着地させる。
  ただし新規依存・ブラウザ対応・実装コスト増。今回スコープ外として提示のみ。

---

## 5. 反映チャネル(確認結果)
- フロントは **Next.js 15**(`frontend/`、git remote = GitHub **aibo_v8**、
  `npm run dev`=next dev → **localhost:3000 ホットリロード**)。
- 反映手順:
  1. 拠点1 `frontend/` の .tsx/.ts を編集 → localhost:3000 が自動リロード(PO 即確認可)。
  2. 永続化/他環境向けに **GitHub(aibo_v8)へ push**(フロントは git 管理下)。
- **`.py` の 4拠点 Drive 同期は本タスクでは不要**(Colab の .py ではなくフロント変更のため)。
  ※ Colab 再 run も不要(フロントは PC の localhost:3000)。

---

## 6. 司令部へのお伺い(承認が要る点)
1. 案 **(b) 中心拡張** で実装してよいか(推奨)。(a) 併用の要否。
2. 拡張 **factor の初期値=1.7**(実機で 1.6〜2.0 を微調整)で着手してよいか。
3. 反映は **localhost:3000 ホットリロード + GitHub(aibo_v8) push**。
   push は司令部確認後で良いか(統括の常規に合わせるなら push 前に確認)。
4. 完全保証が必要なら将来「フロント顔検出」を別タスク化するか(今回は (b) で根治+
   backend IMPL-007 の二段保険で十分か)。
