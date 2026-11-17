# Master post-install script invoked by the setup wizard.
param(
    [switch]$InstallOllama,
    [switch]$PullModels,
    [switch]$InstallMT5
)

$ErrorActionPreference = "Continue"
$scriptDir = $PSScriptRoot

if ($InstallOllama) {
    & (Join-Path $scriptDir "install_ollama.ps1")
}

if ($PullModels) {
    if (-not $InstallOllama) {
        $ollama = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
        if (-not (Test-Path $ollama)) {
            Write-Host "Skipping models — Ollama not installed."
        } else {
            & (Join-Path $scriptDir "pull_ollama_models.ps1")
        }
    } else {
        Start-Sleep -Seconds 8
        & (Join-Path $scriptDir "pull_ollama_models.ps1")
    }
}

if ($InstallMT5) {
    & (Join-Path $scriptDir "install_mt5.ps1")
}

exit 0
