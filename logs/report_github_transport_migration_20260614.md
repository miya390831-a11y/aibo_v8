# 報告: code 同期を GitHub transport へ移管(DriveFS clobber 根絶 + GATE① unblock)

- 日付: 2026-06-14
- 担当: 統括(GitHub 移管・notebook 改修・パス監査・push・文書化)
- 状態: **GitHub 側 push 完了 / notebook GitHub-pull 化 / パス監査・修正完了 / docs 更新 / ローカルコミット完了。**
  **Colab 実機(Secrets 設定→Cell 0→manifest 緑→GATE①)と PC アプリ撤去は PO 待ち**(実機ログは PO のみ取得可)。

## 0. push した branch / commit(version pin の基準)
- **branch: `sync/colab`(新規・PO 承認)** / remote: `github.com/miya390831-a11y/aibo_v8`
- **commit SHA: `f2479622828c4e551b6befa4adb8728109b420a5`**(notebook 既定 `AIBO_PIN="sync/colab"`=この tip)
- master は **parked**(push せず)。

### ★GATE① unblock の機械的証拠(GitHub 上の code が正しい)
push 済 commit の numbered modules を**正規化 md5**で manifest と突合 → 全一致:
```
03_identity_engine.py : pushed=a7556198  manifest=a7556198  OK
05_orchestrator.py    : pushed=4055f4a5  manifest=4055f4a5  OK   (OSS schedule 維持)
07_main.py            : pushed=6e7f8a1a  manifest=6e7f8a1a  OK
```
→ Colab が `sync/colab` を pull すれば **03/05/07 とも正版**。DriveFS clobber の影響を受けない。

## 1. アーキテクチャ確定: code=GitHub / data=Drive / models=HF
- **code**: notebook Cell 0 が `aibo_v8` の `sync/colab` を clone/fetch → exact commit checkout。
  PAT は **Colab Secrets `GH_PAT`**(コード/chat 直書きなし)。Cell 0 が `@ <sha8>` を print=稼働版が明示。
- **data**: refs `/content/drive/MyDrive/顔/` / outputs `…/aibo_v7/experiments/` は Drive 絶対パスのまま。
  `drive.mount` は **PC の Drive デスクトップアプリ非依存**(Google 直認証)→ PC アプリ撤去で無影響。
- **models**: HF Hub → `/content/aibo_hf_cache`(NVMe)直 DL(従来通り・Drive 非経由)。

## 2. ★directive からの1点訂正(repo 構造の実測)
- directive は code dir を `/content/aibo_src/aibo_v7`(repo 内 aibo_v7 ディレクトリ)としていたが、
  **本 repo は toplevel 直下に `*.py`**(`git rev-parse --show-toplevel`=リポ root、`aibo_v7/` サブディレクトリは無い)。
- ∴ clone 先 `/content/aibo_src` の**直下**に 01–17 が来る → **`AIBO_ROOT = "/content/aibo_src"`** に確定。
  notebook もこの値で実装。

## 3. notebook 改修(aibo_v7_colab.ipynb・Cell 0 / Cell 1)
- Cell 0 の `AIBO_ROOT = "/content/drive/MyDrive/aibo_v7"`(Drive code 読み)を **GitHub clone/fetch ブロック**へ置換:
  ```python
  from google.colab import userdata as _udata
  _PAT = _udata.get('GH_PAT')                      # 値はログに出さない
  AIBO_PIN = "sync/colab"                          # 既定=branch tip。SHA を入れれば版固定
  _SRC, _BR = "/content/aibo_src", "sync/colab"
  _URL = f"https://{_PAT}@github.com/miya390831-a11y/aibo_v8.git"
  # .git があれば fetch、無ければ clone → checkout(origin tip or 指定 SHA)→ HEAD sha を print
  AIBO_ROOT = _SRC
  ```
- Cell 1 の `AIBO_ROOT` も `/content/aibo_src` へ。Drive mount / HF cache(NVMe)/ HF_TOKEN 経路は不変。
- notebook は valid JSON を確認済。

## 4. ★パス監査(code dir 変更で壊れる箇所)
- **code-path を Drive 直書きしてたセル = 1つだけ**: `exp_portrait_verify_oneshot.py` の
  `sys.path.insert/chdir("/content/drive/MyDrive/aibo_v7")` → **`/content/aibo_src` に更新**(修正済)。
- **data-path は変更不要**: 全 exp セルの `FACE_DIR=/content/drive/MyDrive/顔` /
  `OUT_DIR=/content/drive/MyDrive/aibo_v7/experiments` は **絶対 Drive パス**でそのまま機能(cloud 上に実在)。
- core 01–17 は `import_module` 名前解決(sys.path 依存)で絶対 code パス非依存 → 変更不要。

## 5. manifest ガード(B2)維持
- `07_main.run()` 冒頭の preflight はそのまま。GitHub pull は exact commit=必ず緑。
  pull 取り違え/branch ずれ/将来の事故は引き続き `[OBS] module manifest …` + STOP で検出。

## 6. PC 側(DriveFS 撤去)— PO 実施手順
1. **Google Drive デスクトップ(DriveFS)を撤去**: 設定 → アカウント切断 → アンインストール。
   最低でも「自動起動 OFF + 完全終了」。
2. `G:\マイドライブ\…` ローカルミラーは消えて可(**code=GitHub**、refs は cloud に実在)。
3. 旧 sync script(`.errorfix/_impl004_sync_v2.ps1` / `sync_modules_v3.ps1`)は **code 用は廃止**(git push に置換)。

## 7. 厳守事項の遵守
- **検証済み構成 不変**(Setting A 7値/PHASE3A3B/no-Hyper/**OSS 05=4055f4a5**/pass2off/phase3off/PuLID 0.7)。
  変えたのは **同期 transport と notebook/verify のパスのみ**(生成ロジック非改変)。
- token は **Colab Secrets `GH_PAT`**(chat/コード直書きなし)。**main は parked**(push は `sync/colab`)。
- 最小・**revertible**(notebook の `AIBO_ROOT` を Drive に戻すだけで旧経路へ即復帰)。
- ローカルコミットのみ(本 report)。`sync/colab` は f2479622 で固定(report churn を載せない)。

## 8. ★PO 次アクション(GATE① 緑まで)
1. **Colab Secrets に `GH_PAT`**(private repo pull 用 PAT)を登録(chat に貼らない)。
2. 新 notebook(`sync/colab` の `aibo_v7_colab.ipynb`)で **Colab 再起動 → Cell 0**:
   - `✅ [code=GitHub] sync/colab @ f2479622 -> /content/aibo_src` が出る。
   - 続く build で `[OBS] module manifest …` + **`✅ runtime modules == committed`**(STOP しない)。
3. ログ蛇口 attach → UI 1枚 → `!tail -n 120 /content/aibo_gen.log` で
   **`🧩 [OSS] inject-point reached` + `[OSS] APPLIED n=14 maxΔ≈0.0 ✓`** → **GATE① 緑**。
4. refs=Nika 反映 / experiments 保存も確認(data=Drive 経路の健全性)。

---
**要点:** clobber の根=DriveFS 双方向同期。**code を GitHub transport(`sync/colab` @ f2479622・exact commit)へ移管**し
構造的に根絶。push 済 code は 03/05/07 とも manifest と一致=Colab pull で正版確定(GATE① unblock を兼ねる)。
data=Drive / models=HF は不変、PC アプリ撤去は Colab に無影響。repo に aibo_v7 サブ無し→`AIBO_ROOT=/content/aibo_src`。
**残りは PO 実機(Secrets→Cell 0→manifest 緑→GATE①)と DriveFS 撤去。**
