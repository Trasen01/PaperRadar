#define MyAppName "PaperRadar"
#define MyAppVersion "0.3.0"
#define MyAppPublisher "PaperRadar"
#define MyAppExeName "PaperRadar.exe"
#define MyAppId "{{1F0CB35D-5B7B-45D1-9B31-202603000001}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\PaperRadar
DefaultGroupName=PaperRadar
DisableProgramGroupPage=no
OutputDir=..\dist\installer
OutputBaseFilename=PaperRadar_Setup_v{#MyAppVersion}
SetupIconFile=..\assets\PaperRadar.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "..\dist\PaperRadar-v0.3.0\PaperRadar.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "..\dist\PaperRadar-v0.3.0\paperradar-backend.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\PaperRadar"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\PaperRadar"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 PaperRadar"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 用户数据目录会保留，避免卸载时误删本地文献、缓存和报告。
