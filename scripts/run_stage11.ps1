param()
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先运行scripts/setup_python.ps1创建项目环境。' }
Push-Location -LiteralPath $projectRoot
try {
  $env:PYTHONUTF8 = '1'
  & $pythonPath (Join-Path $PSScriptRoot 'stage11.py')
  if ($LASTEXITCODE -ne 0) { throw '阶段11验收失败，请查看结果。' }
} finally { Pop-Location }
