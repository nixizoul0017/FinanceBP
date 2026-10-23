#ifndef AppVersion
  #define AppVersion "1.2.2"
#endif

#ifndef ProjectRoot
  #define ProjectRoot ".."
#endif
#ifndef AppBundleDir
  #define AppBundleDir ProjectRoot + "\dist\windows\FinanceBP"
#endif

[Setup]
AppId={{64AD31ED-176B-4A28-ACEC-B3C9191C142D}
AppName=FinanceBP
AppVersion={#AppVersion}
AppPublisher=FinanceBP
AppComments=Local financial analysis. Unsigned personal and portfolio build.
DefaultDirName={localappdata}\Programs\FinanceBP
DefaultGroupName=FinanceBP
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.22000
OutputDir={#ProjectRoot}\dist
OutputBaseFilename=FinanceBP-{#AppVersion}-windows-x64-setup
SetupIconFile={#ProjectRoot}\docs\assets\financebp.ico
UninstallDisplayIcon={app}\FinanceBP.exe
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
DisableProgramGroupPage=yes
CloseApplications=yes
RestartApplications=no
SetupLogging=yes
InfoBeforeFile={#ProjectRoot}\docs\windows_install_notice.txt

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: checkedonce

[Files]
Source: "{#AppBundleDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#ProjectRoot}\outputs\desktop_build\tools\MicrosoftEdgeWebView2RuntimeInstallerX64.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall; Check: NeedsWebView

[Icons]
Name: "{group}\FinanceBP"; Filename: "{app}\FinanceBP.exe"
Name: "{autodesktop}\FinanceBP"; Filename: "{app}\FinanceBP.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\FinanceBP.exe"; Description: "Open FinanceBP"; Flags: nowait postinstall skipifsilent

[Code]
function HasWebViewAt(Root: Integer; Key: String): Boolean;
var Names: TArrayOfString; I: Integer; Product, Version: String;
begin
  Result := False;
  if RegGetSubkeyNames(Root, Key, Names) then
    for I := 0 to GetArrayLength(Names)-1 do
      if RegQueryStringValue(Root, Key+'\'+Names[I], 'name', Product) and
         (Pos('WebView2', Product)>0) and
         RegQueryStringValue(Root, Key+'\'+Names[I], 'pv', Version) and
         (Version<>'') and (Version<>'0.0.0.0') then Result := True;
end;

function NeedsWebView: Boolean;
begin
  Result := not (HasWebViewAt(HKCU, 'Software\Microsoft\EdgeUpdate\Clients') or
    HasWebViewAt(HKLM32, 'Software\Microsoft\EdgeUpdate\Clients') or
    HasWebViewAt(HKLM64, 'Software\Microsoft\EdgeUpdate\Clients'));
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer;
begin
  if (CurStep=ssPostInstall) and NeedsWebView then begin
    if not Exec(ExpandConstant('{tmp}\MicrosoftEdgeWebView2RuntimeInstallerX64.exe'),
      '/silent /install', '', SW_HIDE, ewWaitUntilTerminated, Code) then
      RaiseException('WebView2 offline installation could not be started.');
    if NeedsWebView then
      RaiseException('WebView2 installation did not complete. Check the setup log and retry.');
  end;
end;

// Personal data is intentionally outside {app}; no UninstallDelete entry targets it.
