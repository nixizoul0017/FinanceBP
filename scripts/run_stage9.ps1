param(
  [string]$Profile = 'configs/demo_files.json',
  [string]$Cutoff = '2026-09',
  [ValidateSet('auto','last_year_same_month','recent_mean','driver_based')][string]$Method = 'auto',
  [ValidateSet(1,3,6)][int]$Window = 3,
  [string]$Version = 'B2026_V1',
  [ValidateSet('net_revenue','gross_margin','operating_profit')][string]$Objective = 'net_revenue',
  [string[]]$Products,
  [string[]]$Channels,
  [string[]]$Regions,
  [decimal]$QuantityChange = 0,
  [decimal]$PriceChange = 0,
  [decimal]$UnitCostChange = 0,
  [decimal]$RefundRateChange = 0,
  [decimal]$CostReversalChange = 0,
  [decimal]$MarketingChange = 0,
  [decimal]$ExpenseChange = 0
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请先准备项目Python环境。' }
Push-Location -LiteralPath $projectRoot
try {
  $env:PYTHONUTF8 = '1'
  $arguments = @((Join-Path $PSScriptRoot 'stage9.py'), '--profile', $Profile, '--cutoff', $Cutoff, '--method', $Method, '--window', "$Window", '--version', $Version, '--objective', $Objective)
  if ($Products) { $arguments += @('--products') + $Products }
  if ($Channels) { $arguments += @('--channels') + $Channels }
  if ($Regions) { $arguments += @('--regions') + $Regions }
  $culture = [Globalization.CultureInfo]::InvariantCulture
  foreach ($pair in @(@('quantity-change',$QuantityChange),@('price-change',$PriceChange),@('unit-cost-change',$UnitCostChange),@('refund-rate-change',$RefundRateChange),@('cost-reversal-change',$CostReversalChange),@('marketing-change',$MarketingChange),@('expense-change',$ExpenseChange))) {
    $arguments += @("--$($pair[0])", ($pair[1].ToString($culture)))
  }
  & $pythonPath @arguments
  if ($LASTEXITCODE -ne 0) { throw '阶段9执行失败，请核对上方提示。' }
} finally { Pop-Location }

