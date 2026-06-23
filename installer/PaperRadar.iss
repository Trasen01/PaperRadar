#define MyAppName "PaperRadar"
#define MyAppVersion "0.2.3"
#define MyAppPublisher "PaperRadar 项目"
#define MyAppExeName "PaperRadar.exe"
#define MyAppId "{{1F0CB35D-5B7B-45D1-9B31-202602000001}}"

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
PrivilegesRequired=admin
PrivilegesRequiredOverridesAllowed=dialog
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "chinesesimplified"; MessagesFile: "ChineseSimplified.isl"

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加快捷方式："; Flags: unchecked

[Files]
Source: "..\dist\PaperRadar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PaperRadar"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\PaperRadar"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "启动 PaperRadar"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; 程序文件会由卸载程序自动移除。
; 用户数据会保留在 %APPDATA%\PaperRadar，此处不会删除。
