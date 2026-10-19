param(
  [ValidateSet('demo','mysql-read','mysql-import','preview')][string]$Mode = 'demo',
  [string]$Profile = ''
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) {
  throw '缺少项目Python环境，请先按docs/USER_GUIDE.md安装依赖。'
}
Push-Location -LiteralPath $projectRoot
try {
  $env:PYTHONUTF8 = '1'
  $arguments = @((Join-Path $PSScriptRoot 'stage5.py'), $Mode)
  if ($Profile) { $arguments += @('--profile', $Profile) }
  & $pythonPath @arguments
  if ($LASTEXITCODE -ne 0) { throw '阶段5执行失败，请查看上方提示及outputs/stage5中的报告。' }
} finally { Pop-Location }
