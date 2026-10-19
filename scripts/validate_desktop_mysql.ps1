param([int]$Port=33326)
# Only a new, isolated test instance. Never connects to the user's port 3306.
$ErrorActionPreference='Stop'
$projectRoot=[IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$validation=[IO.Path]::GetFullPath((Join-Path $projectRoot '.desktop_validation'))
$alias='C:\Users\Public\Documents\FinanceBP_Desktop_01a12dd5'
$mysql='C:\Program Files\MySQL\MySQL Server 26.7'
$serverPath=Join-Path $mysql 'bin\mysqld.exe'
$admin=Join-Path $mysql 'bin\mysqladmin.exe'
$application=Join-Path $projectRoot 'outputs\desktop_build\installed\FinanceBP.exe'
$server=$null
$madeDirectory=$false
$madeAlias=$false
if ($validation -ne (Join-Path $projectRoot '.desktop_validation')) { throw 'Unexpected test directory' }
if ((Test-Path -LiteralPath $validation) -or (Test-Path -LiteralPath $alias)) { throw 'Existing test directory; refusing to overwrite' }
if (Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue) { throw 'Test port in use' }
if (-not (Test-Path -LiteralPath $application)) { throw 'Installed application missing' }
try {
  New-Item -ItemType Directory -Path $validation | Out-Null
  $madeDirectory=$true
  New-Item -ItemType Directory -Path (Join-Path $validation 'data'),(Join-Path $validation 'tmp') | Out-Null
  New-Item -ItemType Junction -Path $alias -Target $validation | Out-Null
  $madeAlias=$true
  & $serverPath '--no-defaults' '--initialize-insecure' "--basedir=$mysql" "--datadir=$alias\data" "--log-error=$alias\initialize.log"
  if ($LASTEXITCODE -ne 0) { throw 'Isolated MySQL initialization failed' }
  $arguments=@('--no-defaults',"--basedir=`"$mysql`"","--datadir=$alias\data","--tmpdir=$alias\tmp",'--bind-address=127.0.0.1',"--port=$Port",'--mysqlx=OFF','--skip-log-bin',"--log-error=$alias\server.log")
  $server=Start-Process -FilePath $serverPath -ArgumentList $arguments -WindowStyle Hidden -PassThru
  $ready=$false
  for ($attempt=0;$attempt -lt 60;$attempt++) {
    Start-Sleep -Milliseconds 250
    if ($server.HasExited) { throw 'Isolated MySQL exited' }
    & $admin '--no-defaults' '--no-login-paths' '--host=127.0.0.1' "--port=$Port" '--user=root' '--silent' 'ping' 2>$null
    if ($LASTEXITCODE -eq 0) { $ready=$true;break }
  }
  if (-not $ready) { throw 'Isolated MySQL startup timed out' }
  & (Join-Path $PSScriptRoot 'run_stage3.ps1') -Port $Port -NoPassword -DatabaseName 'finance_bp_stage3'
  if ($LASTEXITCODE -ne 0) { throw 'Sample SQL failed' }
  $output=Join-Path $projectRoot 'outputs\desktop_build\installed-mysql-selftest.json'
  $data=Join-Path $projectRoot 'outputs\desktop_build\mysql_personal_data'
  $process=Start-Process -FilePath $application -ArgumentList '--self-test',('"'+$output+'"'),'--data-dir',('"'+$data+'"'),'--mysql-port',"$Port" -WindowStyle Hidden -Wait -PassThru
  if ($process.ExitCode -ne 0) { throw "Packaged MySQL self-test failed. See $output" }
  $result=Get-Content -LiteralPath $output -Raw -Encoding UTF8 | ConvertFrom-Json
  if (-not $result.passed -or [decimal]$result.mysql.net_revenue -ne 3240) { throw 'Packaged MySQL result mismatch' }
  Write-Host "PACKAGED_MYSQL_PASS: isolated port $Port; sample net revenue 3240"
} finally {
  if ($server -and -not $server.HasExited) {
    & $admin '--no-defaults' '--no-login-paths' '--host=127.0.0.1' "--port=$Port" '--user=root' 'shutdown' 2>$null
    if (-not $server.WaitForExit(5000)) { Stop-Process -Id $server.Id -Force }
  }
  if ($madeAlias) {
    $item=Get-Item -LiteralPath $alias -Force
    if ($item.LinkType -ne 'Junction' -or [IO.Path]::GetFullPath(@($item.Target)[0]) -ne $validation) { throw 'Alias target changed; cleanup stopped' }
    [IO.Directory]::Delete($alias)
  }
  if ($madeDirectory) {
    $item=Get-Item -LiteralPath $validation -Force
    if ($item.FullName -ne (Join-Path $projectRoot '.desktop_validation') -or $item.LinkType) { throw 'Test directory changed; cleanup stopped' }
    Remove-Item -LiteralPath $validation -Recurse -Force
  }
}
