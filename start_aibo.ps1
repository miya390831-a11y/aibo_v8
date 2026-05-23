# AIBO Cyber Studio Quick Start
$frontendPath = Join-Path $PSScriptRoot "frontend"
Set-Location $frontendPath

$portInUse = Get-NetTCPConnection -LocalPort 3000 -ErrorAction SilentlyContinue
if ($portInUse) {
    Write-Host "✅ Dev server は既に起動中 (port 3000 in use)"
} else {
    Write-Host "🚀 Starting npm run dev..."
    Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$frontendPath'; npm run dev"
    Start-Sleep -Seconds 5
}

Write-Host "🌐 Opening browser..."
Start-Process "http://localhost:3000"
