param([ValidateRange(1024,65535)][int]$Port = 8501, [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $projectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $pythonPath)) { throw '请双击根目录START.cmd准备环境，或查看docs/USER_GUIDE.md。' }
Push-Location -LiteralPath $projectRoot
try {
  $env:PYTHONUTF8 = '1'
  Write-Output "经营分析看板：http://127.0.0.1:$Port"
  Write-Output '保持此窗口运行；结束时按Ctrl+C。默认模拟文件无需MySQL密码。'
  $headless = if ($NoBrowser) { 'true' } else { 'false' }
  & $pythonPath -m streamlit run (Join-Path $projectRoot 'app.py') '--server.address=127.0.0.1' "--server.port=$Port" "--server.headless=$headless" '--browser.gatherUsageStats=false'
  if ($LASTEXITCODE -ne 0 -and $LASTEXITCODE -ne 130) { throw '看板启动失败，请查看上方提示。端口占用时可用-Port指定其他端口。' }
} finally { Pop-Location }
