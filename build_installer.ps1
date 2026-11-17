# TradingBot V1 — build application + Windows installation wizard
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host "`n=== TradingBot V1 — Trade Command Centre — Build ===" -ForegroundColor Cyan

python -m pip install --upgrade pip | Out-Null
python -m pip install -r requirements.txt pyinstaller PySide6 | Out-Null

Write-Host "`n[1/2] Building TradingBotV1.exe (PyInstaller)..." -ForegroundColor Yellow
python -m PyInstaller build.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller build failed" }

$exe = "dist\TradingBotV1\TradingBotV1.exe"
if (-not (Test-Path $exe)) { throw "EXE not found at $exe" }
Write-Host "  Built: $exe" -ForegroundColor Green

Write-Host "`n[2/2] Building Windows setup wizard (Inno Setup)..." -ForegroundColor Yellow

$iscc = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $iscc) {
    Write-Host @"

  Inno Setup 6 is not installed.
  Download: https://jrsoftware.org/isdl.php

  Application ready at:
    $((Resolve-Path $exe).Path)

  Install Inno Setup, then run this script again to create:
    installer_output\TradingBotV1_Setup_1.0.0.exe

"@ -ForegroundColor Yellow
    exit 0
}

& $iscc installer.iss
if ($LASTEXITCODE -ne 0) { throw "Inno Setup compile failed" }

$setup = Get-ChildItem installer_output\*.exe | Select-Object -First 1
Write-Host "`n=== Done ===" -ForegroundColor Green
Write-Host "  Installer: $($setup.FullName)" -ForegroundColor Green
Write-Host "`n  Run the Setup EXE to install the app, Ollama, AI models, and MT5.`n" -ForegroundColor White
