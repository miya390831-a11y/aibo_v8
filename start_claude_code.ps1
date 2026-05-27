# AIBO · Claude Code CLI Launcher
$Host.UI.RawUI.WindowTitle = "AIBO · Claude Code CLI"

Set-Location -Path "C:\Users\yuuki\aibo_v7"

Write-Host ""
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host "  AIBO Cyber Studio · Claude Code CLI 起動" -ForegroundColor Cyan
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  作業ディレクトリ: $(Get-Location)" -ForegroundColor White
Write-Host "  モデル:           Opus 4.7" -ForegroundColor White
Write-Host "  引継書:           HANDOVER_2026-05-24_v3.md" -ForegroundColor White
Write-Host ""
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host ""

# Claude Code 起動
try {
    & claude
} catch {
    Write-Host ""
    Write-Host " ============================================" -ForegroundColor Red
    Write-Host "  ERROR: Claude Code が起動できませんでした" -ForegroundColor Red
    Write-Host " ============================================" -ForegroundColor Red
    Write-Host ""
    Write-Host "  原因の可能性:" -ForegroundColor Yellow
    Write-Host "    1. 未インストール → irm https://claude.ai/install.ps1 | iex"
    Write-Host "    2. PATH 未設定 → C:\Users\yuuki\.local\bin を PATH に追加"
    Write-Host "    3. 認証切れ → claude auth login を実行"
    Write-Host ""
    Write-Host " ============================================" -ForegroundColor Red
    Read-Host "Press Enter to exit"
}
