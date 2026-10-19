param(
  [ValidateSet('Menu','Start','Install','Verify','Package','Check','Reports')][string]$Action = 'Menu',
  [ValidateRange(1024,65535)][int]$Port = 8501,
  [string]$PythonPath = '',
  [switch]$NoBrowser
)
$ErrorActionPreference = 'Stop'
$projectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$environmentPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
$env:PYTHONUTF8 = '1'
function Install-Environment {
  & (Join-Path $PSScriptRoot 'setup_python.ps1') -PythonPath $PythonPath
}
function Ensure-Environment {
  if (-not (Test-Path -LiteralPath $environmentPython)) {
    Write-Host '首次使用：正在创建Python环境并安装依赖。需要Python 3.13/3.14及可用的包源。'
    Install-Environment
  }
  & $environmentPython -c 'import sys, streamlit, openpyxl, pandas, sqlalchemy, plotly; assert sys.version_info[:2] in {(3,13),(3,14)}'
  if ($LASTEXITCODE -ne 0) { throw '运行环境未准备好。请返回菜单选择2，安装/更新依赖。' }
}
function Test-PortBusy([int]$Value) {
  $client = New-Object Net.Sockets.TcpClient
  try {
    $task = $client.ConnectAsync('127.0.0.1',$Value)
    if (-not $task.Wait(400)) { return $false }
    return $client.Connected
  } catch { return $false } finally { $client.Dispose() }
}
function Invoke-ProjectAction([string]$Choice) {
  switch ($Choice) {
    'Install' { Install-Environment }
    'Check' {
      if (-not (Test-Path -LiteralPath $environmentPython)) { throw '尚未安装：请双击START.cmd并选择2。' }
      Ensure-Environment
      foreach ($file in @('app.py','requirements.txt','configs/demo_files.json','tests/fixtures/sample_sql_reference.json','tests/fixtures/monthly_reference.json','tests/fixtures/report_reference.json')) {
        if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $file))) { throw "项目文件缺失：$file" }
      }
      Write-Output 'PROJECT_READY'
    }
    'Start' {
      Ensure-Environment
      $startArguments = @((Join-Path $PSScriptRoot 'manage.py'), '--action', 'Start', '--port', "$Port")
      if ($NoBrowser) { $startArguments += '--no-browser' }
      & $environmentPython @startArguments
      if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 130) { throw '网页启动未完成，请查看上方错误。' }
    }
    'Verify' {
      Ensure-Environment
      & (Join-Path $PSScriptRoot 'run_stage11.ps1')
      Write-Host '验收结果：outputs\validation'
    }
    'Package' {
      Ensure-Environment
      & $environmentPython (Join-Path $PSScriptRoot 'check_project.py')
      if ($LASTEXITCODE -ne 0) { throw '项目路径或文档检查未通过，请先修复再打包。' }
      & $environmentPython (Join-Path $PSScriptRoot 'package_project.py')
      if ($LASTEXITCODE -ne 0) { throw '项目打包失败。' }
      Write-Host '整体项目包已放入dist文件夹。'
    }
    'Reports' {
      $directory = Join-Path $projectRoot 'outputs\reports'
      New-Item -ItemType Directory -Path $directory -Force | Out-Null
      if (-not $NoBrowser) { Start-Process explorer.exe -ArgumentList ('"'+$directory+'"') }
      Write-Output $directory
    }
  }
}
Push-Location -LiteralPath $projectRoot
try {
  if ($Action -ne 'Menu') { Invoke-ProjectAction $Action; exit 0 }
  while ($true) {
    Write-Host "`n===== 财务经营分析工作台 ====="
    Write-Host '1  打开程序（首次使用自动准备环境）'
    Write-Host '2  安装/更新依赖'
    Write-Host '3  运行整体验收（文件模式）'
    Write-Host '4  生成完整项目ZIP'
    Write-Host '5  打开本地报告目录'
    Write-Host '0  退出'
    $selection = Read-Host '请选择'
    if ($selection -eq '0') { break }
    $choices = @{'1'='Start';'2'='Install';'3'='Verify';'4'='Package';'5'='Reports'}
    if (-not $choices.ContainsKey($selection)) { Write-Host '请输入0至5。'; continue }
    try { Invoke-ProjectAction $choices[$selection] }
    catch { Write-Host ("未完成："+$_.Exception.Message) -ForegroundColor Red }
  }
} catch {
  Write-Error $_.Exception.Message
  exit 1
} finally { Pop-Location }
