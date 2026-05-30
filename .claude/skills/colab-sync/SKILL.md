---
name: colab-sync
description: >
  修正を適用してリポに反映・同期するときに使う。git commit/push する時、4拠点同期を行う時、
  Colab に変更を反映する時、修正後に「Colab 側で再 run が必要」を扱う時に発火。
allowed-tools: Read, Bash
---

# 反映・同期の作法

修正は「適用して終わり」ではない。同期と Colab 反映まで含めて完了。

## 同期先(4拠点)
- C:\Users\yuuki\aibo_v7\(主)
- C:\Users\yuuki\Downloads\AIBOV7\
- C:\Users\yuuki\Downloads\AIBOV7\3a\
- G:\マイドライブ\aibo_v7\(Colab 参照)

## git
- push は **master と colab-stable の両方**へ。
- 自動対応(既知パターン)は AUTO_PUSH=False なら**ローカル commit 止まり**。push は人の判断。
- Drive 同期は FUSE が不安定。rsync ではなく tar pipe + symlink fallback を前提に扱う。

## Colab 反映(忘れやすい・必ず報告に書く)
- PC 側でコードを直しただけでは Colab の実行には反映されない。
- **Colab 側で手動の再 run が必要**: `os.kill(os.getpid(), 9)` でランタイム再起動 → Cell 0 から。
- numpy 再 install ループに注意: PROTECT_IF_SATISFIED を尊重し、os.kill 強制再起動に頼りすぎない。

## チェックリスト
1. 構文確認済みか(py_compile)。
2. 適切なブランチに反映したか。
3. 報告に「Colab 再 run が必要」を明記したか。
