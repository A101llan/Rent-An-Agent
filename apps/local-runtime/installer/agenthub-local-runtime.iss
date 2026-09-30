; Inno Setup script - AgentHub Local Runtime (per-user, no admin rights needed)
#define AppVersion "0.1.0"
#define AppExe "agenthub-local-runtime.exe"

[Setup]
AppId={{5E2B8C1A-7D4F-4A9B-9C3E-2F6A1B0D8E71}
AppName=AgentHub Local Runtime
AppVersion={#AppVersion}
AppVerName=AgentHub Local Runtime {#AppVersion}
AppPublisher=AgentHub
DefaultDirName={localappdata}\Programs\AgentHub Local Runtime
DefaultGroupName=AgentHub Local Runtime
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build\installer
OutputBaseFilename=AgentHubLocalRuntimeSetup-{#AppVersion}
Compression=lzma2/max
SolidCompression=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayName=AgentHub Local Runtime {#AppVersion}
UninstallDisplayIcon={app}\{#AppExe}
WizardStyle=modern

[Tasks]
Name: "autostart"; Description: "Start the AgentHub local runtime when I sign in"; GroupDescription: "Startup:"
Name: "setupollama"; Description: "Check Ollama and download the AI model now (opens a console window)"; GroupDescription: "AI model:"

[Files]
Source: "..\build\dist\agenthub-local-runtime\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Start AgentHub Local Runtime"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\start-hidden.vbs"""; WorkingDir: "{app}"
Name: "{group}\Stop AgentHub Local Runtime"; Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExe} /F"
Name: "{group}\Setup - check Ollama and model"; Filename: "{app}\{#AppExe}"; Parameters: "setup --open-browser"; WorkingDir: "{app}"
Name: "{group}\Uninstall AgentHub Local Runtime"; Filename: "{uninstallexe}"
Name: "{userstartup}\AgentHub Local Runtime"; Filename: "{sys}\wscript.exe"; Parameters: """{app}\start-hidden.vbs"""; WorkingDir: "{app}"; Tasks: autostart

[Run]
Filename: "{app}\{#AppExe}"; Parameters: "setup --open-browser"; WorkingDir: "{app}"; StatusMsg: "Checking Ollama and the AI model..."; Flags: waituntilterminated; Tasks: setupollama
Filename: "{sys}\wscript.exe"; Parameters: """{app}\start-hidden.vbs"""; WorkingDir: "{app}"; Description: "Start AgentHub Local Runtime now (127.0.0.1:8765)"; Flags: postinstall nowait

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/IM {#AppExe} /F"; Flags: runhidden; RunOnceId: "StopSidecar"

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  { stop a running copy so its files can be replaced }
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/IM {#AppExe} /F', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Result := '';
end;
