# Install Ollama for Windows (silent) if not already present.
$ErrorActionPreference = "Stop"

$ollamaExe = Join-Path $env:LOCALAPPDATA "Programs\Ollama\ollama.exe"
if (Test-Path $ollamaExe) {
    Write-Host "Ollama already installed."
    exit 0
}

$setup = Join-Path $env:TEMP "OllamaSetup.exe"
Write-Host "Downloading Ollama..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
Invoke-WebRequest -Uri "https://ollama.com/download/OllamaSetup.exe" -OutFile $setup -UseBasicParsing

Write-Host "Installing Ollama (silent)..."
$proc = Start-Process -FilePath $setup -ArgumentList "/S" -Wait -PassThru
if ($proc.ExitCode -ne 0 -and $proc.ExitCode -ne $null) {
    Write-Warning "Ollama installer exit code: $($proc.ExitCode)"
}

Start-Sleep -Seconds 5
if (-not (Test-Path $ollamaExe)) {
    Write-Error "Ollama installation did not complete. Install manually from https://ollama.com"
    exit 1
}

Write-Host "Ollama installed successfully."
exit 0
