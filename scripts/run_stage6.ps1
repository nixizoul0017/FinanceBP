param(
  [string]$Profile = 'configs/demo_files.json',
  [string]$Month = '2026-09',
  [string[]]$Products,
  [string[]]$Channels,
  [string[]]$Regions,
  [string]$Version = 'B2026_V1'
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先按阶段5指南准备项目Python环境。' }
Push-Location -LiteralPath $projectRoot
try {
  $env:PYTHONUTF8 = '1'
  $arguments = @((Join-Path $PSScriptRoot 'stage6.py'), '--profile', $Profile, '--month', $Month, '--version', $Version)
  if ($Products) { $arguments += @('--products') + $Products }
  if ($Channels) { $arguments += @('--channels') + $Channels }
  if ($Regions) { $arguments += @('--regions') + $Regions }
  & $pythonPath @arguments
  if ($LASTEXITCODE -ne 0) { throw '阶段6执行失败，请查看上方提示。' }
} finally { Pop-Location }
