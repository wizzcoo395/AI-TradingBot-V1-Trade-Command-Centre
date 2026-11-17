# TradingBot V1 — developer setup (run from source)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "TradingBot V1 — Trade Command Centre (developer install)" -ForegroundColor Cyan
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Write-Host "`nRun the desktop app:" -ForegroundColor Green
Write-Host "  python trade_command_centre.py" -ForegroundColor White
Write-Host "`nBuild Windows installer wizard:" -ForegroundColor Yellow
Write-Host "  .\build_installer.ps1" -ForegroundColor White
