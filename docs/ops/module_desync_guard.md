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
