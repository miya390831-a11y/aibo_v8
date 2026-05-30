# 🔬 エラー修正くろうど 半自動ループ ― セットアップ & 運用

実装検証チームの errorfix を「常駐ウォッチャー → headless で診断+パッチ提案 → 統括へ通知 → PO 承認で適用」にする一式。

---

## 全体フロー(ドクトリン B)

```
[Colab A100]  エラー発生 → logs/ に出力
      │  (Drive 同期)
      ▼
[watch_errorfix.py]  常駐・ポーリング監視  ← "常時起動" の正体
      │  検知 → dedup / debounce / circuit-break / lock
      ▼
[当直: エラー修正くろうど]  診断 + 直し方(diff)の報告を作る
      │
      ├─ 既知の安全パターン(WHITELIST)= 司令部の常設指示で自動対応OK
      │     → diff を決定論的に適用(git apply→構文チェック→commit)
      │     → 司令部へ「自動対応しました」と事後報告(FYI・判断不要)
      │
      └─ 新規 / リスクあり
            → 適用しない。報告を logs/errorfix_inbox/ に上げる
            ▼
        [司令部 = この対話(CTOくろうど + みやちん)]
            報告をレビュー(必要ならディープリサーチ)→ 直し方を決定
            ▼
        [統括(VS Code)]  指示を受けて現場に実行させる → 結果を報告
            ▼
        [Colab]  手動で再 run(os.kill 再起動)  ← 無人化の境界
```

指揮系統: **司令部(ここ)=頭脳/意思決定** → **統括=遂行管理** → **現場=実装**。
既知パターンだけは「自動対応してよい」という司令部の常設指示で当直が片付け、事後報告する。

---

## 配置

```
<repo>/
  .claude/
    agents/
      errorfix-kuroudo.md          # 当直: 検知・診断・報告
      lead-verify-kuroudo.md       # 統括: 指示の遂行管理・報告(現場監督)
    settings.json                  # settings_hooks.json の hooks をマージ
  .errorfix/
    watch_errorfix.py              # 常駐ウォッチャー(検知→診断→自動/レビュー振分け)
    apply_fix.py                   # 統括が司令部承認済みの修正を安全適用する補助
    guard_forbidden.py             # 厳守ルールの機械ロック(PreToolUse フック)
    whitelist_signatures.txt       # (任意) 自動対応を許可した署名の追加リスト
    incoming/  applied/            # 作業用(自動生成)
  start_errorfix_watcher.bat       # デスクトップ 🔬 アイコンから
  logs/
    errorfix_inbox/                # 当直の報告(自動生成)→ 司令部に持ち込む
```

※ 旧 `approve_errorfix.py`(みやちん承認制)は廃止。ドクトリン B では「既知=自動」
「新規=司令部レビュー」に置き換わったため。手動適用が要るときは `apply_fix.py` を使う。

## セットアップ手順

1. `.errorfix/` に `watch_errorfix.py` `apply_fix.py` `guard_forbidden.py`、ルートに .bat を配置。
2. `settings_hooks.json` の `hooks` を `.claude/settings.json` にマージ。
   配置後 Claude Code で `/hooks` を開いて承認(設定はセッション開始時にスナップショット)。
3. `start_errorfix_watcher.bat` の `AIBO_REPO` を実環境に合わせる。
4. **`claude --help` でフラグ名を確認**。`watch_errorfix.py` の `CLAUDE_FLAGS`
   (`--allowedTools` / `--output-format`)はバージョンで変わることがある。
5. `watch_errorfix.py` 冒頭の `WHITELIST_PATTERNS` を確認(初期は引継書の既知障害を登録済み)。
6. 🔬 アイコン(.bat)起動 → ウォッチャー常駐開始。

## 日々の運用

- ウォッチャーは出しっぱなしでOK。
- **既知パターン**を検知 → 当直が自動で直し、`logs/errorfix_inbox/` に「自動対応しました(FYI)」報告。
  判断不要。AUTO_PUSH=False なのでローカル commit 止まり(push は人が判断)。
- **新規/リスクあり**を検知 → 適用せず報告だけ上がる。これを**司令部(この対話)に持ち込んでレビュー**。
  - 報告は repo の `logs/errorfix_inbox/` → GitHub 経由 or 貼り付けで司令部へ。
  - 司令部で直し方を決定 → 統括(タブ2)に指示 → 統括が実行 → `apply_fix.py` で安全適用。
- どの自動対応でも、適用後の Colab 再 run(`os.kill(os.getpid(), 9)`)は手動。

## 既知パターンの増やし方(自動対応の昇格)

司令部レビューで「この署名は今後自動でいい」と判断したら、その署名を
`.errorfix/whitelist_signatures.txt` に1行追記する(報告の `署名:` 値)。
次回から当直が自動対応する。最初は少なめにして、実績を見て増やすのが安全。

## 統括(タブ2)からの見え方

- SessionStart フックが「司令部レビュー待ち N 件」を表示。
- 統括は司令部の指示を受けて実行する役。指示が来たら `apply_fix.py` で適用し結果を報告。
  統括自身は直し方を決めない(それは司令部の仕事)。

---

## 安全装置

| 装置 | 効果 |
|---|---|
| whitelist | 自動対応は司令部が認めた既知パターンに限定。新規は必ずレビューへ |
| dedup / debounce | 同一エラーの多重発火を抑制(DEBOUNCE_SEC) |
| circuit breaker | 同一署名 MAX_RETRIES 回でエスカレーション(司令部判断へ・暴走防止) |
| lock | 同時1件のみ処理。多重起動を防止 |
| guard_forbidden.py | Setting A 値変更・禁止パターンを exit 2 で機械的にブロック |
| git + py_compile | 自動適用は可逆。構文NGなら自動ロールバック |
| AUTO_PUSH=False | 自動対応はローカル commit 止まり。push は人の判断 |

## 注意・境界

- **Colab/PC 分離**: エラーは Colab、修正は PC。自動範囲は「検知→診断→(既知なら)適用・commit」。
  Colab の再 run は手動(または別途ブラウザ自動化)。
- **同期遅延**: Drive 同期があるため「即座に」には数秒〜のフロアがある。
  ポーリング監視は FUSE イベントより堅牢なのでこの構成。
- **司令部 ⇄ Claude Code は別システム**: 自動連携しない。報告の橋渡しは
  みやちん(と GitHub)が行う。GitHub コネクタを繋げば司令部からも報告を読める。
- フラグ名・フック仕様は Claude Code のバージョンで変わり得る。`claude --help` / `/hooks` で確認を。
