#define AppVersion "0.3.1"
#define AppName "YouTube Live Recorder"
#ifndef BundleDir
  #define BundleDir "..\dist\YouTubeLiveRecorder"
#endif

[Setup]
AppId={{35C68D30-7145-4C68-8A1E-37E7E726D209}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=YouTube Live Recorder
AppSupportURL=https://github.com/blogbooster/WebinarAutoRecorder
DefaultDirName={localappdata}\Programs\YouTubeLiveRecorder
DefaultGroupName={#AppName}
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=..\dist\installer
OutputBaseFilename=YouTubeLiveRecorder-{#AppVersion}-Setup
SetupIconFile=..\build\package-resources\app.ico
UninstallDisplayIcon={app}\YouTubeLiveRecorder.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
AppMutex=Local\YouTubeLiveRecorder.Running
CloseApplications=no
RestartApplications=no
Uninstallable=yes
SetupLogging=yes

[Languages]
Name: "korean"; MessagesFile: "compiler:Languages\Korean.isl"

[Tasks]
Name: "desktopicon"; Description: "바탕 화면에 바로가기 만들기"; Flags: unchecked

[Files]
Source: "{#BundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\YouTubeLiveRecorder.exe"; WorkingDir: "{app}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\YouTubeLiveRecorder.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\YouTubeLiveRecorder.exe"; Description: "YouTube Live Recorder 실행"; Flags: nowait postinstall skipifsilent

; 사용자 DB/로그/녹화 폴더는 설치하거나 삭제하지 않는다.
; [UninstallDelete]와 Windows 자동 실행 등록은 의도적으로 사용하지 않는다.
