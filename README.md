# TradingBot V1 — Trade Command Centre

Windows desktop trading console for MetaTrader 5 with optional Ollama AI.

| Item | Value |
|------|--------|
| Product name | **TradingBot V1** (window title) |
| In-app header | **Trade Command Centre** |
| Executable | `TradingBotV1.exe` |

## Quick start (developers)

```powershell
cd "G:\Tradingbot\trading bot v1"
.\install.ps1
python trade_command_centre.py
```

## Build Windows installer

Requires [Inno Setup 6](https://jrsoftware.org/isdl.php).

```powershell
.\build_installer.ps1
```

Output: `installer_output\TradingBotV1_Setup_1.0.0.exe`

The setup wizard can install:

1. **Trade Command Centre** (this app)
2. **Ollama** — local AI runtime
3. **llama3:latest** — default AI model (~2 GB download)
4. **MetaTrader 5** — official MetaQuotes installer (log in with your broker)

## After installation

1. Open MT5, log in, enable **Algo Trading**
2. Launch **Trade Command Centre** from Start menu
3. **Connect MT5** → **Start**

Settings and logs are stored in `%APPDATA%\TradingBotV1\`.

## Folder layout

```
trading bot v1/
  trade_command_centre.py   # Entry point
  app_branding.py           # Names / version
  build_installer.ps1       # Build EXE + Setup wizard
  installer.iss             # Inno Setup script
  installer/scripts/        # Ollama, models, MT5 installers
  desktop/                  # PySide6 UI
  ...
```

## Notes

- MT5 must be logged into **your broker**; the generic installer does not create trading accounts.
- AI model download requires internet and may take several minutes during setup.
- Use a smaller/faster model in Settings if `llama3:latest` is too slow on your PC.
