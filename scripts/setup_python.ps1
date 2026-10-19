param([string]$PythonPath = '')
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$environmentPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $environmentPython)) {
  if (-not $PythonPath) {
    foreach ($version in @('3.14','3.13')) {
      $pythonRegistry = "HKCU:\Software\Python\PythonCore\$version\InstallPath"
      if (Test-Path -LiteralPath $pythonRegistry) {
        $PythonPath = (Get-ItemProperty -LiteralPath $pythonRegistry).ExecutablePath
      } elseif (Get-Command py -ErrorAction SilentlyContinue) {
        try {
          $candidate = (& py "-$version" -c 'import sys; print(sys.executable)' 2>$null)
          if ($LASTEXITCODE -eq 0) { $PythonPath = $candidate }
        } catch { }
      }
      if ($PythonPath) { break }
    }
    if (-not $PythonPath) { throw '请先准备Python3.13或3.14，并通过-PythonPath指定python.exe位置。' }
  }
  & $PythonPath -m venv (Join-Path $projectRoot '.venv')
  if ($LASTEXITCODE -ne 0) { throw 'Python环境创建失败' }
}
& $environmentPython -c 'import sys; assert sys.version_info[:2] in {(3,13),(3,14)} and sys.maxsize > 2**32'
if ($LASTEXITCODE -ne 0) { throw '需要64位Python3.13或3.14；请检查项目环境版本。' }
& $environmentPython -m pip install -r (Join-Path $projectRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败，请查看安装信息' }
& $environmentPython --version
Write-Output '项目Python环境已准备好。'
