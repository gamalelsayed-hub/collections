#ifndef AppVersion
  #define AppVersion "0"
#endif

[Setup]
AppId={{C2DDF7BD-7B9E-4360-A7A4-9A48057F1538}
AppName=برنامج المطابقة والتحصيل
AppVersion={#AppVersion}
AppPublisher=Altameer
DefaultDirName={localappdata}\Programs\Collections
DefaultGroupName=برنامج المطابقة والتحصيل
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Collections-Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayIcon={app}\Collections.exe

[Tasks]
Name: "desktopicon"; Description: "أيقونة على سطح المكتب"; Flags: checkedonce

[Files]
Source: "..\dist\Collections\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\برنامج المطابقة والتحصيل"; Filename: "{app}\Collections.exe"
Name: "{userdesktop}\برنامج المطابقة والتحصيل"; Filename: "{app}\Collections.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Collections.exe"; Description: "تشغيل البرنامج"; Flags: nowait postinstall skipifsilent
