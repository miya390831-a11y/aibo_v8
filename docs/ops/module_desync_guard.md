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

## ★事例: transport は正なのに「起動 side effect が Drive 旧版を aibo_src に上書き」疑い(2026-06-23)
GATE① 前ブロッカーの 4 周目。Cell 0 transport の `disk md5==manifest` が **PASS した直後**(=clone は正版)に、
PO 実機で `/content/aibo_src/03` を測ると **3b297f80(旧)**・mtime=Cell0 直後・**中身は Drive 旧 03 と完全一致**。
→ transport 後の何かが `/content/drive/MyDrive/aibo_v7` の旧コードを aibo_src に被せている、という症状。
- **コード調査の結論(重要)**: `sync/colab` の全 `.py` を grep した結果、**Drive→aibo_src のコード書き戻しは
  committed code に存在しない**。`aibo_src` は write 対象に一度も現れず、`copytree` は outputs→Drive の
  正方向のみ、`CacheSync` は未 instantiate、`drive_root` は別フォルダ(あいぼすたじお2)。
  → 「起動コードが書き戻す」仮説は本ブランチでは裏付けられない。**writer は旧 notebook(DriveFS 期)由来の
  常駐プロセス/Drive 常駐スクリプト等の runtime 副作用**が濃厚(=クリーン再起動で消える類)。
- **多層ガード(Cell 0 に実装・59591b8)**: 捏造削除はせず writer を**現認**する instrumentation を追加。
  - `_snap_core()` が 03/07 の md5+mtime を **post-transport / post-import / post-boot** の 3 点で記録 →
    どの段で stale 化したか現認。
  - `AiboMain.run()`(起動 side effect)後に**最終ゲート**: `disk md5 != manifest` なら STOP し診断ダンプ:
    (a) Drive 旧コードと**内容一致**か(上書き元の同定)、(b) transport 後に **mtime 更新された aibo_src 配下**
    (writer の足跡)、(c) **生存スレッド**一覧(clobber daemon 捕捉)。
- **教訓**: GitHub transport で「clone が正」を保証しても、**runtime に残る旧世代の副作用(常駐 sync 等)**が
  後段で上書きし得る。manifest 検証は **transport 直後だけでなく起動 side effect の後にも**置く。
  根治には writer の発生源(常駐プロセス/Drive スクリプト)を特定して止める必要があり、本ガードはその特定を
  次回 1 実行で完了させるためのもの。

## ★真因確定: Colab で git checkout/reset が rc=0 詐欺。materialize は cat-file→直書きが唯一信頼できる(2026-06-23)
4 周ループの真因が PO 実機で確定。**この Colab 環境では `git checkout` / `git reset --hard` / `git checkout-index`
が rc=0 を返すのに working tree を書かない**(= rc=0 詐欺。`check=True` も `-C` も env 無害化も無意味)。
- 証拠: `HEAD:03 blob=a820b6eb`(正)≠ `hash-object 03(disk)=24113acf`(旧)が reset/checkout-index 後も継続。
  disk md5=3b297f80(旧)。一方 **`git cat-file -p HEAD:<f>` の blob 読み出しは正常**で、Python で
  `open(fp,"wb").write(blob)` すると一発で正版(全14コアを PO が実証: 03=a7556198 / 07=6e7f8a1a / 05=4055f4a5 …)。
- これまでの「Drive 旧で上書き」説は誤認。実体は **checkout が working tree を一切更新せず、clone 先に残った
  旧ファイル(or 空)をそのまま放置**していた。`disk md5==manifest` の PASS 誤報も、checkout 後に測る位置次第で説明可能。
- **根治(materialize の置換)**: working tree は git checkout 系で作らない。**HEAD tree の全 tracked を
  `git ls-tree -r --name-only HEAD` で列挙 → 各 blob を `git cat-file -p HEAD:<f>` → Python 直書き**で materialize。
  直後に `disk md5 == module_manifest.json` を assert(silent fail 禁止)。`sys.dont_write_bytecode=True` +
  `__file__` ベース purge + `invalidate_caches()` も併用。Cell 0 transport に実装(rev catfile-fix)。
- **enumerate は `ls-tree`(commit tree)で**:`git ls-files`(index)は `--no-checkout`/checkout 詐欺時に空に
  なり 0 件 materialize になる。`ls-tree -r HEAD` は object graph を読むので index/working-tree 状態に依存しない。
- **原因の推定(任意)**: Colab の overlayfs/特定 git バージョンで checkout の working-tree 書込み段が黙って no-op。
  cat-file は object store の read のみで成立するため影響を受けない。原因究明より**回避策(cat-file 直書き)が本線**。
- **今すぐ build(GATE① を当日通す)**: Cell 0 に `SKIP_TRANSPORT=True` 分岐。既に全コア materialize 済みの
  `/content/aibo_src` をそのまま使い、clone/materialize を skip して import→build→起動。md5 assert が
  「本当に materialize 済みか」を検証してから build に進む。

## ★追確定: cat-file の出力は正でも Cell0 内 write がディスクに反映されない(2026-06-23)
真因をさらに 1 行に詰めた。PO 実機で同一ファイルを多角測定:
- `cat-file -p HEAD:03` の中身 md5=a7556198(正・size 77897)/ `disk _norm_md5`=3b297f80(旧・size 77894)/
  mtime 不変(5回測定)= **Cell 0 後に誰も書き換えていない**(clobber/daemon 否定)。
- つまり **Cell 0 内の `open(fp,"wb").write(blob)` がディスクに効かず(no-op)**、clone が最初に置いた旧版が残存。
  **PO が手動で同じ `cat-file→open().write()` を打つと a7556198 に直る** = Cell0 実行コンテキスト固有の write 無効化。
- 「snap✓ なのに最終ガード✗」の積年の矛盾は、snap が `cat-file 出力`(正)を測り、最終ガードが `実ディスク`(旧)を
  測っていたため(測定対象の差)。
- **対策(materialize 書込みを確実化・多層)**:(a) **書込み直後に読み戻して `disk bytes == HEAD blob` を
  1 ファイルずつ assert**(no-op を書込み地点で検出 → 即 raise)。(b) **clone が置いた旧ファイルを書込み前に
  物理 `os.remove`**(同一視スキップ/上書き no-op を回避)。(c) **新規 tmp に書いて `flush+os.fsync` →
  `os.replace`(atomic rename)**(in-place 上書きの no-op 化を回避・lower-layer の影が無いパスへ書く)。

## ★2系統化: Drive に code(.py)を置かない。Drive は data 専用(2026-06-23)
旧 code(`/content/drive/MyDrive/aibo_v7/*.py` `*.ipynb` `__pycache__`)が各種 clobber/誤 import の弾薬源。
**code は GitHub(`/content/aibo_src`)のみ・data は Drive のみ・models は HF** の3系統を徹底し、Drive 直下の
旧 code を**削除**(退避でなく)。notebook に削除セル(DRY-RUN 既定・直下のみ・data 不可侵)を追加。
- **残す data(絶対パスで実コードが参照)**: `experiments/`(outputs)/ `gfpgan/weights/GFPGANv1.4.pth`(08:323)/
  `bodyrefs` `depth_ab` `bodycn_ab` `_models/`(exp 用)/ 別 dir `/content/drive/MyDrive/顔/`(refs)/ `aibo_hf_cache`。
- 以後 **Drive に .py を置かない**(置くと旧 code 経路が復活する)。コア .py の変更は GitHub `sync/colab` push のみ。
