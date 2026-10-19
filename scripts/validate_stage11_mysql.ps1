param(
  [int]$Port = 33324,
  [string]$MySqlDirectory = 'C:\Program Files\MySQL\MySQL Server 26.7'
)
# 开发验收入口：创建独立临时实例、运行测试、关闭并清理；无需用户密码。
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$validationPath = [IO.Path]::GetFullPath((Join-Path $projectRoot '.stage11_validation'))
$aliasPath = 'C:\Users\Public\Documents\FinanceBP_Stage11_01a12dd5'
$serverPath = Join-Path $MySqlDirectory 'bin\mysqld.exe'
$adminPath = Join-Path $MySqlDirectory 'bin\mysqladmin.exe'
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
$server = $null
$aliasCreated = $false
$directoryCreated = $false
if ($validationPath -ne (Join-Path $projectRoot '.stage11_validation')) { throw '临时目录范围不正确' }
if (Test-Path -LiteralPath $validationPath) { throw '已有临时验证目录，停止以免覆盖' }
if (Test-Path -LiteralPath $aliasPath) { throw '已有目录别名，停止以免覆盖' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw '验证端口正在使用' }
try {
  New-Item -ItemType Directory -Path $validationPath | Out-Null
  $directoryCreated = $true
  New-Item -ItemType Directory -Path (Join-Path $validationPath 'data'),(Join-Path $validationPath 'tmp') | Out-Null
  New-Item -ItemType Junction -Path $aliasPath -Target $validationPath | Out-Null
  $aliasCreated = $true
  & $serverPath '--no-defaults' '--initialize-insecure' "--basedir=$MySqlDirectory" "--datadir=$aliasPath\data" "--log-error=$aliasPath\initialize.log"
  if ($LASTEXITCODE -ne 0) { throw '临时MySQL初始化失败' }
  $serverArgs = @('--no-defaults', "--basedir=`"$MySqlDirectory`"", "--datadir=$aliasPath\data", "--tmpdir=$aliasPath\tmp", '--bind-address=127.0.0.1', "--port=$Port", '--mysqlx=OFF', '--skip-log-bin', "--log-error=$aliasPath\server.log")
  $server = Start-Process -FilePath $serverPath -ArgumentList $serverArgs -WindowStyle Hidden -PassThru
  $ready = $false
  for ($attempt=0; $attempt -lt 60; $attempt++) {
    Start-Sleep -Milliseconds 250
    if ($server.HasExited) { throw '临时MySQL提前退出' }
    & $adminPath '--no-defaults' '--no-login-paths' '--host=127.0.0.1' "--port=$Port" '--user=root' '--silent' 'ping' 2>$null
    if ($LASTEXITCODE -eq 0) { $ready=$true; break }
  }
  if (-not $ready) { throw '临时MySQL启动超时' }
  $env:PYTHONUTF8 = '1'
  & (Join-Path $PSScriptRoot 'run_stage3.ps1') -Port $Port -NoPassword -DatabaseName 'finance_bp_stage3_stage11'
  & (Join-Path $PSScriptRoot 'run_stage4.ps1') -Port $Port -NoPassword -DatabaseName 'finance_bp_stage3_stage11'
  foreach ($testFile in @('stage5_mysql_integration.py','validate_stage6.py','validate_stage8_mysql.py','validate_stage9_mysql.py','validate_stage11_mysql.py','validate_dynamic_mysql.py')) {
    & $pythonPath (Join-Path $projectRoot "tests\$testFile") "$Port"
    if ($LASTEXITCODE -ne 0) { throw "独立数据库验收失败：$testFile" }
  }
} finally {
  if ($server -and -not $server.HasExited) {
    & $adminPath '--no-defaults' '--no-login-paths' '--host=127.0.0.1' "--port=$Port" '--user=root' 'shutdown' 2>$null
    if (-not $server.WaitForExit(5000)) { Stop-Process -Id $server.Id -Force }
  }
  if ($aliasCreated) {
    $aliasItem = Get-Item -LiteralPath $aliasPath -Force
    $aliasTarget = @($aliasItem.Target)[0]
    if ($aliasItem.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath($aliasTarget) -ne $validationPath) { throw '目录别名目标不匹配，停止清理' }
    # Windows PowerShell 5.1的Remove-Item可能对junction抛NullReference。
    # 已核对目标后只移除链接本身；不递归访问它指向的目录。
    [IO.Directory]::Delete($aliasPath)
  }
  if ($directoryCreated) {
    $directoryItem = Get-Item -LiteralPath $validationPath -Force
    if ($directoryItem.FullName -ne (Join-Path $projectRoot '.stage11_validation') -or $directoryItem.LinkType) { throw '临时目录范围不匹配，停止清理' }
    Remove-Item -LiteralPath $validationPath -Recurse -Force
  }
}


