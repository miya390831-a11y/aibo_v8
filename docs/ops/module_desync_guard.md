# module desync 防止ガード(B1/B2/B3)— 運用ガイド

- 制定: 2026-06-14(GATE① 真因 = 04新/05旧 の silent module desync の再発防止)
- 要旨: **「sync した」は証拠ではない。「md5 一致」と「manifest preflight 緑」が証拠。**

## 背景(なぜ要るか)
Colab は `.py` を G:\マイドライブ\aibo_v7\ 経由でロードする。Drive sync が部分失敗すると、
一部モジュールだけ旧版のまま走り(例: 04 のフックは新版だが 05 の注入ブロックが旧版)、
**沈黙したまま挙動だけ壊れる**(GATE①: OSS 注入が発火せず `OSS='None'`、しかも他ゲートは緑)。
原因特定に時間を要した。二度と silent desync を通さないため、検出を自動化する。

## 構成

### B1. sync 自己検証 — `.errorfix/sync_modules_v3.ps1`
- コア全 `.py`(01–17)+ `module_manifest.json` + `tools/` を 4拠点へコピー。
- コピー後に **src↔各 dest の md5 を比較**。1個でも不一致/欠落なら
  `RESULT: SYNC-FAILED` + `exit 1`(成功扱いにしない)。
- 実行: `powershell -ExecutionPolicy Bypass -File .errorfix\sync_modules_v3.ps1`
- `RESULT: ALL-MATCH` を確認してから Colab 再起動へ進む。

### B2. module-manifest preflight — `tools/gen_manifest.py` / `tools/check_manifest.py`
- **commit 前**: `python tools/gen_manifest.py` → 各コア .py の**改行正規化 md5**を
  `module_manifest.json` に記録(これを commit)。
  - 改行正規化(CRLF/CR→LF)なので Windows(CRLF)/Drive/git(LF)で同一ハッシュ=改行差で誤検出しない。
- **Cell 0 build 時**(自動): `07_main.run()` 冒頭の `_verify_module_manifest_preflight()` が
  `tools/check_manifest.verify_module_manifest(strict=True)` を呼ぶ。
  - runtime 実ロードモジュール(`sys.modules[...]__file__`・無ければ repo 直下)の正規化 md5 を
    manifest と照合。
  - 緑: `[OBS] module manifest | 01=<h8> 04=<h8> 05=<h8> 09=<h8> …` + `✅ runtime modules == committed`。
  - desync: `❌ MODULE DESYNC 検出 …` を表示し **SystemExit で build を即死**。
    ```
    ❌ MODULE DESYNC 検出(committed manifest と不一致 → build STOP):
       05_orchestrator.py  runtime=4055f4a5  expected=deadbeef  src=loaded  (…/05_orchestrator.py)
       対処: 該当 .py を G:\マイドライブ\aibo_v7\ に再同期(md5 一致を確認)→ Colab 再起動。
    ```
  - manifest 不在/ツール import 不可 → warn して続行(ガード未導入環境は壊さない)。
- **手動確認も可**(restart 不要の素振り):
  `exec(open("/content/drive/MyDrive/aibo_v7/tools/check_manifest.py", encoding="utf-8").read())`

### B3. プロセスルール
- **verify / ship ゲートは manifest preflight が緑になるまで回さない。**
- desync 検出時は **Drive Web UI で手動再アップ**(過去の確実手段)→ 再 sync(B1)→ md5 一致 → 再起動。

## 標準手順(コア .py を変えたとき)
1. コード編集 → `python -m py_compile <変更.py>`。
2. `python tools/gen_manifest.py`(manifest 再生成)。
3. `git commit`(.py + module_manifest.json)。push は PO 判断。
4. `.errorfix\sync_modules_v3.ps1` → `RESULT: ALL-MATCH` を確認。
5. Colab 再起動(`os.kill(os.getpid(),9)`)→ Cell 0 build。
6. build ログで `[OBS] module manifest …` + `✅ runtime modules == committed` を確認 → 以降の検証/ship へ。

## 限界(正直に)
- B2 は __file__(=ディスク)の md5 を見る。**「旧モジュールを import 済のまま .py だけ更新して再起動しない」**
  ケースは、ディスクが新でもメモリが旧になり得る。→ だから **B3(必ず再起動)** が対。
  再起動さえすれば sys.modules は新規 import され、ディスク=メモリ=manifest が一致する。

## ★事例: DriveFS clobber(2026-06-14・03/07)
manifest ガードが build STOP(設計通り)。原因は **「sync 完了 ≠ 正しい中身」**:
- `.errorfix/sync_modules_v3.ps1` は `RESULT: ALL-MATCH` を出した(G:\ への書込み直後は正)。
  だが後刻、G:\ の 03/07 が **mtime 新しいのに中身は旧**(committed と不一致)に化けていた。
  → Google **DriveFS**(`%LOCALAPPDATA%\Google\DriveFS` 仮想マウント = G:)が、
  **クラウド側の旧版を local 書込みに被せて revert** していた(= clobber)。mtime は revert 時刻で更新されるため
  「新しい=最新」に見えるが中身は旧。**mtime も sync 成功表示も、中身が正しい証拠にならない。**
- 切り分け(git 実測): `git show <commit>:<file>` を **同じ正規化(CRLF→LF→md5[:8])** して
  manifest 期待値と突合。
  - committed 正規化 md5 == 期待値、Drive == 旧 → **Drive が古い(本件)**。
  - committed 正規化 md5 == 旧(=未改変なのに manifest が別値) → **manifest 生成バグ**(編集中/未保存から記録)。
    → 実 committed から `python tools/gen_manifest.py` で再生成。
- **確実な復旧手段**: clobber は desktop 経由(G:\ 書込み)では負ける。
  **Drive Web UI(drive.google.com → MyDrive/aibo_v7)で正版を手動アップロード**=クラウドへ直書きし、
  DriveFS の stale キャッシュをバイパスする。アップ後、PO の正規化 md5 セルで **expected 一致**を確認してから
  Colab 再起動。
- 教訓3点(運用に固定):
  1. **sync 完了 ≠ 正しい中身**(mtime 新でも中身旧があり得る)。証拠は常に「正規化 md5 == expected」。
  2. **DriveFS clobber 時は Web UI 手動アップ**(desktop 同期は当てにしない)。
  3. **manifest 期待値は必ず実 committed から生成**(編集中バッファから作らない)。

## ★根治: code 同期を GitHub transport へ移管(2026-06-14 確定)
DriveFS の双方向同期が clobber の根。**code を Drive から外し GitHub(exact commit)に移す**ことで
構造的に解消する。新アーキ = **code=GitHub / data=Drive / models=HF**。
- **code**: notebook Cell 0 が `aibo_v8` の `sync/colab` を clone/fetch → exact commit checkout →
  `AIBO_ROOT=/content/aibo_src`(repo 直下に *.py)。clone した版がそのまま動く=部分 desync 不能・
  version pin 明示(Cell 0 が `@ <sha8>` を print)。PAT は **Colab Secrets `GH_PAT`**(コード/chat 直書き禁止)。
- **data**: refs `/content/drive/MyDrive/顔/` / outputs `…/aibo_v7/experiments/` は Drive 絶対パスのまま。
  Colab `drive.mount` は **PC の Drive デスクトップアプリ非依存**(Google へ直接認証)→ PC アプリ撤去で無影響。
- **models**: HF Hub → `/content/aibo_hf_cache`(NVMe)直 DL(従来通り・Drive 非経由)。
- **PC 側**: Google Drive デスクトップ(DriveFS)は **code に使わない**(撤去 or 自動起動 OFF+完全終了)。
  `G:\マイドライブ\…` ローカルミラーは消えて可(code=GitHub、refs は cloud に存在)。
- **旧経路の扱い**: DriveFS 4拠点 sync(`.errorfix/sync_modules_v3.ps1`)は **code 用は廃止**(git push に置換)。
  manifest ガード(B2)は維持 = GitHub pull の取り違え/branch ずれを引き続き検出。
- **パス監査(移行時)**: code dir 変更で壊れるのは **code-path を Drive 直書きしてるセルのみ**。
  本リポでは `exp_portrait_verify_oneshot.py` の `sys.path/chdir` を `/content/aibo_src` へ更新済。
  data-path(`MyDrive/顔` `MyDrive/aibo_v7/experiments`)は絶対 Drive のまま変更不要。
- **revert**: 旧 Drive code 経路は notebook の `AIBO_ROOT` を戻すだけ(branch 上で即可逆)。
