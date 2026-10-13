; Installer fuer AutoClicker (Inno Setup 6)
; Bauen am besten mit:  python tools/build_windows.py

#ifndef AppVersion
  #define AppVersion "6.16"
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
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"
Name: "fr"; MessagesFile: "compiler:Languages\French.isl"
Name: "tr"; MessagesFile: "compiler:Languages\Turkish.isl"
Name: "pl"; MessagesFile: "compiler:Languages\Polish.isl"
Name: "it"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "pt"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"
Name: "nl"; MessagesFile: "compiler:Languages\Dutch.isl"
Name: "sv"; MessagesFile: "compiler:Languages\Swedish.isl"
Name: "nb"; MessagesFile: "compiler:Languages\Norwegian.isl"
Name: "da"; MessagesFile: "compiler:Languages\Danish.isl"
Name: "fi"; MessagesFile: "compiler:Languages\Finnish.isl"
Name: "cs"; MessagesFile: "compiler:Languages\Czech.isl"
Name: "sk"; MessagesFile: "compiler:Languages\Slovak.isl"
Name: "hu"; MessagesFile: "compiler:Languages\Hungarian.isl"
Name: "bg"; MessagesFile: "compiler:Languages\Bulgarian.isl"
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "uk"; MessagesFile: "compiler:Languages\Ukrainian.isl"
Name: "ja"; MessagesFile: "compiler:Languages\Japanese.isl"
Name: "ko"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\AutoClicker\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\AutoClicker"; Filename: "{app}\AutoClicker.exe"
Name: "{autodesktop}\AutoClicker"; Filename: "{app}\AutoClicker.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\AutoClicker.exe"; Description: "{cm:LaunchProgram,AutoClicker}"; Flags: nowait postinstall skipifsilent
; Nach einem Update aus der App heraus (leise Installation) automatisch neu starten
Filename: "{app}\AutoClicker.exe"; Flags: nowait; Check: WizardSilent
