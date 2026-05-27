# AIBO · Claude Code CLI Launcher (BYPASS MODE)
$Host.UI.RawUI.WindowTitle = "AIBO · Claude Code [BYPASS]"

Set-Location -Path "C:\Users\yuuki\aibo_v7"

Write-Host ""
Write-Host " ============================================" -ForegroundColor Magenta
Write-Host "  AIBO Cyber Studio · Claude Code [BYPASS]" -ForegroundColor Magenta
Write-Host " ============================================" -ForegroundColor Magenta
Write-Host ""
Write-Host "  [!] 完全自動モード" -ForegroundColor Yellow
Write-Host "  [*] 危険コマンドは settings.json で deny 済" -ForegroundColor Green
Write-Host ""
Write-Host "  作業ディレクトリ: $(Get-Location)" -ForegroundColor White
Write-Host "  モデル:           Opus 4.7" -ForegroundColor White
Write-Host "  設定ファイル:     $env:USERPROFILE\.claude\settings.json" -ForegroundColor White
Write-Host ""
Write-Host " ============================================" -ForegroundColor Magenta
Write-Host "  注意:" -ForegroundColor Yellow
Write-Host "    ファイル編集 / Git / コマンド全て自動承認" -ForegroundColor Yellow
Write-Host "    暴走を感じたら Ctrl+C で中断" -ForegroundColor Yellow
Write-Host "    致命的なら emergency_stop.bat (デスクトップ)" -ForegroundColor Yellow
Write-Host " ============================================" -ForegroundColor Magenta
Write-Host ""

# bypass モード起動 (deny rules は settings.json で定義)
try {
    & claude --dangerously-skip-permissions
} catch {
    Write-Host ""
    Write-Host " ============================================" -ForegroundColor Red
    Write-Host "  ERROR: Claude Code 起動失敗" -ForegroundColor Red
    Write-Host " ============================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  対処方法:" -ForegroundColor Yellow
    Write-Host "    1. claude auth status で認証確認"
    Write-Host "    2. claude auth login で再ログイン"
    Write-Host "    3. where claude で PATH 確認"
    Write-Host ""
    Read-Host "Press Enter to exit"
}
