; Inno Setup script. Built by build.py with /DAppVersion=<VERSION>; run from the project root's installer folder.
; Per-user install: no administrator rights, so the program is never launched elevated by accident.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

; The Qt runtime and Pillow are downloaded from PyPI, not shipped: URLs and SHA-256 hashes pinned by pin_runtime.py.
#include "runtime.inc"

[Setup]
AppId={{6F4B2E1A-7C3D-4E58-9A21-5D0C8B7E3F14}
AppName=Grammar Sweeper
AppVersion={#AppVersion}
AppPublisher=Preceperi Limited
AppPublisherURL=https://github.com/PatrickKirby/GrammarSweeper
AppSupportURL=https://github.com/PatrickKirby/GrammarSweeper/issues
DefaultDirName={autopf}\Grammar Sweeper
DefaultGroupName=Grammar Sweeper
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=grammar-sweeper-setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\Grammar Sweeper.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
ArchiveExtraction=full
WizardStyle=modern
WizardImageFile=art\wizard-large.png,art\wizard-large@2x.png
WizardSmallImageFile=art\wizard-small.png,art\wizard-small@2x.png
WizardImageStretch=no

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\Grammar Sweeper\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "runtime-files.txt"; DestDir: "{tmp}"; Flags: dontcopy

[Icons]
Name: "{autoprograms}\Grammar Sweeper"; Filename: "{app}\Grammar Sweeper.exe"
Name: "{autodesktop}\Grammar Sweeper"; Filename: "{app}\Grammar Sweeper.exe"; Tasks: desktopicon

[UninstallDelete]
Type: filesandordirs; Name: "{app}\runtime"

[Run]
Filename: "{app}\Grammar Sweeper.exe"; Description: "Launch Grammar Sweeper"; Flags: nowait postinstall skipifsilent

[Code]
var
  DownloadPage: TDownloadWizardPage;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  Result := True;
end;

procedure InitializeWizard;
begin
  DownloadPage := CreateDownloadPage('Downloading the runtime',
    'Grammar Sweeper draws its window with Qt and its images with Pillow, both downloaded from PyPI (the Python package index).',
    @OnDownloadProgress);
end;

{ Runs after Next on the Ready page, and in silent installs too. A non-empty result stops the install with that message. }
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  try
    if WizardSilent then
    begin
      DownloadTemporaryFile('{#PYSIDEUrl}', 'pyside6.zip', '{#PYSIDESha}', nil);
      DownloadTemporaryFile('{#SHIBOKENUrl}', 'shiboken6.zip', '{#SHIBOKENSha}', nil);
      DownloadTemporaryFile('{#PILLOWUrl}', 'pillow.zip', '{#PILLOWSha}', nil);
    end
    else
    begin
      DownloadPage.Clear;
      DownloadPage.Add('{#PYSIDEUrl}', 'pyside6.zip', '{#PYSIDESha}');
      DownloadPage.Add('{#SHIBOKENUrl}', 'shiboken6.zip', '{#SHIBOKENSha}');
      DownloadPage.Add('{#PILLOWUrl}', 'pillow.zip', '{#PILLOWSha}');
      DownloadPage.Show;
      try
        DownloadPage.Download;
      finally
        DownloadPage.Hide;
      end;
    end;
  except
    Result := 'The runtime could not be downloaded from PyPI: ' + GetExceptionMessage + #13#10#13#10 +
      'Check the internet connection and run setup again. Nothing has been installed.';
  end;
end;

{ Unpacks the downloaded wheels and copies only the files the program uses into the runtime folder under the install folder. }
procedure InstallRuntime;
var
  Wanted: TArrayOfString;
  Source, Target: String;
  I: Integer;
begin
  ExtractArchive(ExpandConstant('{tmp}\pyside6.zip'), ExpandConstant('{tmp}\qt'), '', True, nil);
  ExtractArchive(ExpandConstant('{tmp}\shiboken6.zip'), ExpandConstant('{tmp}\qt'), '', True, nil);
  ExtractArchive(ExpandConstant('{tmp}\pillow.zip'), ExpandConstant('{tmp}\qt'), '', True, nil);
  ExtractTemporaryFile('runtime-files.txt');
  if not LoadStringsFromFile(ExpandConstant('{tmp}\runtime-files.txt'), Wanted) then
    RaiseException('The list of Qt files is missing from the installer.');
  for I := 0 to GetArrayLength(Wanted) - 1 do
  begin
    if Trim(Wanted[I]) = '' then Continue;
    StringChangeEx(Wanted[I], '/', '\', True);
    Source := ExpandConstant('{tmp}\qt\') + Wanted[I];
    Target := ExpandConstant('{app}\runtime\') + Wanted[I];
    if not ForceDirectories(ExtractFileDir(Target)) then
      RaiseException('Could not create ' + ExtractFileDir(Target));
    if not FileCopy(Source, Target, False) then
      RaiseException('The downloaded Qt package is missing ' + Wanted[I]);
  end;
  DelTree(ExpandConstant('{tmp}\qt'), True, True, True);
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
  begin
    try
      InstallRuntime;
    except
      SuppressibleMsgBox('Grammar Sweeper was installed, but the runtime could not be unpacked: ' +
        GetExceptionMessage + #13#10#13#10 + 'Run setup again, or uninstall and reinstall.', mbCriticalError, MB_OK, IDOK);
      Log('Runtime failed: ' + GetExceptionMessage);
    end;
  end;
end;
