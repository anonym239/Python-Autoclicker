; Installer fuer AutoClicker (Inno Setup 6)
; Bauen am besten mit:  python tools/build_windows.py

#ifndef AppVersion
  #define AppVersion "6.0.0"
#endif

[Setup]
AppId={{8C1F2B7A-5E3D-4B8E-9A61-2F0C7D4E6A15}
AppName=AutoClicker
AppVersion={#AppVersion}
AppVerName=AutoClicker {#AppVersion}
AppPublisher=anonym239
AppPublisherURL=https://github.com/anonym239/Python-Autoclicker
AppSupportURL=https://github.com/anonym239/Python-Autoclicker/issues
VersionInfoVersion={#AppVersion}
DefaultDirName={autopf}\AutoClicker
DefaultGroupName=AutoClicker
DisableProgramGroupPage=yes
; Ohne Admin-Rechte installierbar (landet dann im Benutzerordner)
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=AutoClicker-Setup-{#AppVersion}
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\AutoClicker.exe
UninstallDisplayName=AutoClicker
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Laeuft der AutoClicker noch, fragt der Installer nach
AppMutex=AutoClicker6.Running
CloseApplications=yes

[Languages]
Name: "de"; MessagesFile: "compiler:Languages\German.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AutoClicker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AutoClicker"; Filename: "{app}\AutoClicker.exe"
Name: "{autodesktop}\AutoClicker"; Filename: "{app}\AutoClicker.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoClicker.exe"; Description: "{cm:LaunchProgram,AutoClicker}"; Flags: nowait postinstall skipifsilent
