; TradingBot V1 — Trade Command Centre — Windows Setup Wizard
; Build:  .\build_installer.ps1
; Requires Inno Setup 6: https://jrsoftware.org/isinfo.php

#define AppProduct "TradingBot V1"
#define AppDisplay "Trade Command Centre"
#define AppVersion "1.0.0"
#define AppPublisher "TradingBot"
#define AppExeName "TradingBotV1.exe"

[Setup]
AppId={{B4E8F2A1-9C3D-4E7B-8F1A-TRADEBOTV100}
AppName={#AppProduct}
AppVersion={#AppVersion}
AppVerName={#AppProduct} {#AppVersion}
AppPublisher={#AppPublisher}
AppComments={#AppDisplay} — automated MT5 trading console
DefaultDirName={autopf}\{#AppProduct}
DefaultGroupName={#AppProduct}
AllowNoIcons=yes
OutputDir=installer_output
OutputBaseFilename=TradingBotV1_Setup_{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#AppExeName}
WizardImageFile=compiler:WizModernImage-IS.bmp
WizardSmallImageFile=compiler:WizModernSmallImage-IS.bmp
InfoBeforeFile=installer\welcome.txt
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "installollama"; Description: "Install Ollama (local AI runtime)"; GroupDescription: "AI components:"; Flags: checked
Name: "installmodels"; Description: "Download AI model llama3:latest (~2 GB)"; GroupDescription: "AI components:"; Flags: checked
Name: "installmt5"; Description: "Install MetaTrader 5 (official MetaQuotes installer)"; GroupDescription: "Trading platform:"; Flags: checked

[Files]
Source: "dist\TradingBotV1\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "installer\scripts\*"; DestDir: "{app}\installer\scripts"; Flags: ignoreversion
Source: "installer\welcome.txt"; DestDir: "{app}\installer"; Flags: ignoreversion

[Icons]
Name: "{group}\{#AppDisplay}"; Filename: "{app}\{#AppExeName}"; Comment: {#AppProduct}
Name: "{group}\{cm:UninstallProgram,{#AppProduct}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#AppDisplay}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon; Comment: {#AppProduct}

[Run]
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\installer\scripts\install_ollama.ps1"""; StatusMsg: "Installing Ollama AI..."; Tasks: installollama; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\installer\scripts\pull_ollama_models.ps1"""; StatusMsg: "Downloading AI models (may take several minutes)..."; Tasks: installmodels; Flags: runhidden waituntilterminated
Filename: "powershell.exe"; Parameters: "-ExecutionPolicy Bypass -NoProfile -File ""{app}\installer\scripts\install_mt5.ps1"""; StatusMsg: "Installing MetaTrader 5..."; Tasks: installmt5; Flags: waituntilterminated
Filename: "{app}\{#AppExeName}"; Description: "Launch {#AppDisplay}"; Flags: postinstall nowait skipifsilent

[Code]
function InitializeSetup(): Boolean;
begin
  if not FileExists(ExpandConstant('{src}\dist\TradingBotV1\{#AppExeName}')) then
  begin
    MsgBox('Build the application first:' + #13#10 + '  Run build_installer.ps1 from the "trading bot v1" folder.', mbError, MB_OK);
    Result := False;
  end
  else
    Result := True;
end;
