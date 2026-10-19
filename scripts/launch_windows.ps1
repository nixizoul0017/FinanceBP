param([switch]$Advanced, [switch]$NoBrowser, [switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
$projectDirectory = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$env:PYTHONUTF8 = '1'
function Show-StartupError([string]$Message) {
  if ($CheckOnly) { Write-Output ("STARTUP_ERROR: " + $Message); return }
  Add-Type -AssemblyName System.Windows.Forms
  [System.Windows.Forms.MessageBox]::Show($Message, '财务分析：启动未完成', 'OK', 'Error') | Out-Null
}
try {
  $candidates = @($env:FINANCEBP_PYTHON, (Join-Path $projectDirectory '.venv\Scripts\python.exe'))
  foreach ($version in @('3.14','3.13')) {
    foreach ($registryRoot in @('HKCU:','HKLM:')) {
      $registryPath = "$registryRoot\Software\Python\PythonCore\$version\InstallPath"
      if (Test-Path -LiteralPath $registryPath) {
        $installation = Get-ItemProperty -LiteralPath $registryPath
        if ($installation.ExecutablePath) { $candidates += $installation.ExecutablePath }
      }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
      try {
        $found = & py "-$version" -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) { $candidates += $found }
      } catch { }
    }
  }
  $selectedPython = $null
  foreach ($candidate in ($candidates | Where-Object { $_ } | Select-Object -Unique)) {
    if (-not (Test-Path -LiteralPath $candidate -PathType Leaf)) { continue }
    try {
      # PowerShell5.1 strips embedded double quotes from native arguments.
      # Keep this Python probe free of string literals.
      & $candidate -c 'import sys; sys.exit(0 if sys.version_info[:2] in {(3,13),(3,14)} and sys.maxsize > 2**32 else 1)' 2>$null
      if ($LASTEXITCODE -eq 0) { $selectedPython = $candidate; break }
    } catch { }
  }
  if (-not $selectedPython) {
    Show-StartupError "出错阶段：Python环境`n`n未找到64位Python3.13或3.14。`n`n请安装包含pip、venv和Tk的完整Python，再双击START.cmd。`n自定义位置可通过FINANCEBP_PYTHON环境变量指定。"
    exit 1
  }
  Push-Location -LiteralPath $projectDirectory
  if ($CheckOnly) {
    Pop-Location
    Write-Output ("PYTHON_READY: " + $selectedPython)
    exit 0
  }
  try {
    if ($Advanced) { & $selectedPython (Join-Path $PSScriptRoot 'manage.py'); exit $LASTEXITCODE }
    $graphicalPython = Join-Path (Split-Path -Parent $selectedPython) 'pythonw.exe'
    if (-not (Test-Path -LiteralPath $graphicalPython)) { $graphicalPython = $selectedPython }
    $launchArguments = '"' + (Join-Path $PSScriptRoot 'desktop_launcher.py') + '"'
    if ($NoBrowser) { $launchArguments += ' --no-browser' }
    $application = Start-Process -FilePath $graphicalPython -ArgumentList $launchArguments -WorkingDirectory $projectDirectory -WindowStyle Normal -PassThru -Wait
    if ($application.ExitCode -ne 0) { exit $application.ExitCode }
  } finally { Pop-Location }
} catch {
  Show-StartupError ("出错阶段：启动入口`n`n" + $_.Exception.Message + "`n`n请完整解压项目，并确认项目文件夹可读写。")
  exit 1
}
