# Download and launch MetaTrader 5 official installer.
$ErrorActionPreference = "Stop"

$mt5Paths = @(
    "${env:ProgramFiles}\MetaTrader 5\terminal64.exe",
    "${env:ProgramFiles(x86)}\MetaTrader 5\terminal64.exe"
)
foreach ($p in $mt5Paths) {
    if (Test-Path $p) {
        Write-Host "MetaTrader 5 is already installed: $p"
        exit 0
    }
}

$setup = Join-Path $env:TEMP "mt5setup.exe"
Write-Host "Downloading MetaTrader 5 installer..."
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$uri = "https://download.mql5.com/cdn/web/metaquotes.software.corp/mt5/mt5setup.exe"
Invoke-WebRequest -Uri $uri -OutFile $setup -UseBasicParsing

Write-Host "Launching MetaTrader 5 setup — complete the wizard and log in to your broker."
Start-Process -FilePath $setup -Wait

foreach ($p in $mt5Paths) {
    if (Test-Path $p) {
        Write-Host "MetaTrader 5 installed."
        exit 0
    }
}

Write-Host "MT5 setup finished. If not installed, download from your broker or https://www.metatrader5.com"
exit 0
