#define MyAppName "PaperRadar"
#define MyAppVersion "0.2.0"
#define MyAppPublisher "PaperRadar Project"
#define MyAppExeName "PaperRadar.exe"
#define MyAppId "{{1F0CB35D-5B7B-45D1-9B31-202602000001}"

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
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; GroupDescription: "Additional shortcuts:"; Flags: unchecked

[Files]
Source: "..\dist\PaperRadar\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PaperRadar"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"
Name: "{autodesktop}\PaperRadar"; Filename: "{app}\{#MyAppExeName}"; WorkingDir: "{app}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch PaperRadar"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Program files are removed by the uninstaller automatically.
; User data is intentionally kept in %APPDATA%\PaperRadar and is never deleted here.
