# Download default Ollama models used by TradingBot V1.
$ErrorActionPreference = "Stop"

$ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (-not (Test-Path $ollamaExe)) {
    Write-Error "Ollama not found. Enable 'Install Ollama' in the setup wizard first."
    exit 1
}

$models = @("llama3:latest")
if ($env:TCC_OLLAMA_MODELS) {
    $models = $env:TCC_OLLAMA_MODELS -split "[,;]" | ForEach-Object { $_.Trim() } | Where-Object { $_ }
}

$ollamaDir = Split-Path $ollamaExe -Parent
foreach ($model in $models) {
    Write-Host "Pulling model: $model (this may take several minutes)..."
    & $ollamaExe pull $model
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Failed to pull $model — you can run later: ollama pull $model"
    }
}

Write-Host "Model download finished."
exit 0
