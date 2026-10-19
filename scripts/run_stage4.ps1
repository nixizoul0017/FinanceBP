param(
    [string]$MySqlPath = 'C:\Program Files\MySQL\MySQL Server 26.7\bin\mysql.exe',
    [string]$ServerHost = '127.0.0.1',
    [int]$Port = 3306,
    [string]$UserName = 'root',
    [string]$DatabaseName = 'finance_bp_stage3',
    [switch]$NoPassword
)

# 密码由MySQL本地提示输入，不保存、不作为命令行值传递。
# 不使用--force；批量模式任何SQL错误均停止。只在已有项目库建立分析视图。
$ErrorActionPreference = 'Stop'
if (-not [regex]::IsMatch($DatabaseName, '^finance_bp_stage3(?:_[a-z0-9_]+)?$')) {
    throw '数据库名必须为finance_bp_stage3或其小写下划线后缀，避免误操作其他库。'
}
if ($Port -lt 1 -or $Port -gt 65535) { throw '端口无效。' }
if (-not (Test-Path -LiteralPath $MySqlPath -PathType Leaf)) { throw "找不到MySQL客户端，请用-MySqlPath指定路径。" }

$taskRoot = Split-Path -Parent $PSScriptRoot
$taskFiles = @(
    'sql\stage4\00_parameters.sql',
    'sql\stage4\01_analysis_views.sql',
    'sql\stage4\02_detail_and_monthly.sql',
    'sql\stage4\03_dimension_analysis.sql',
    'sql\stage4\04_trends.sql',
    'sql\stage4\05_budget_analysis.sql',
    'sql\stage4\06_verify_baseline.sql'
)
$taskSql = ($taskFiles | ForEach-Object {
    Get-Content -LiteralPath (Join-Path $taskRoot $_) -Raw -Encoding UTF8
}) -join "`n"
$taskSql = $taskSql.Replace('finance_bp_stage3', $DatabaseName)
$taskSql += "`nSELECT 'STAGE4_COMPLETED' AS result, VERSION() AS server_version, DATABASE() AS project_database;`n"

$taskOutputDirectory = Join-Path $taskRoot 'outputs\stage4'
New-Item -ItemType Directory -Path $taskOutputDirectory -Force | Out-Null
$taskLog = Join-Path $taskOutputDirectory ("local_run_{0}.log" -f (Get-Date -Format 'yyyyMMdd_HHmmss_fff'))
$taskArguments = @(
    '--no-defaults', '--no-login-paths', '--protocol=TCP',
    "--host=$ServerHost", "--port=$Port", "--user=$UserName",
    '--connect-timeout=5', '--default-character-set=utf8mb4', '--batch', '--raw'
)
if (-not $NoPassword) { $taskArguments += '--password' }

Write-Host "将连接 $ServerHost`:$Port，使用已有练习库 $DatabaseName。"
if (-not $NoPassword) { Write-Host '请在MySQL提示后输入本机账号密码；输入时不显示字符，不要发送到聊天。' }
Write-Host '将建立或更新10个分析视图并查询小样本，不再次建库或导入原始数据。'

$taskPreviousEncoding = $OutputEncoding
$taskPreviousConsoleEncoding = [Console]::OutputEncoding
$taskPreviousNativeErrorPreference = $ErrorActionPreference
try {
    $OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    # 允许捕获并记录原生程序错误，随后按退出码统一判断，不继续执行下一份脚本。
    $ErrorActionPreference = 'Continue'
    $taskSql | & $MySqlPath @taskArguments 2>&1 | Tee-Object -FilePath $taskLog
    $taskExit = $LASTEXITCODE
} finally {
    $OutputEncoding = $taskPreviousEncoding
    [Console]::OutputEncoding = $taskPreviousConsoleEncoding
    $ErrorActionPreference = $taskPreviousNativeErrorPreference
}

if ($taskExit -ne 0) {
    throw "MySQL执行未完成（退出码$taskExit）。结果保存在$taskLog，请保留错误信息后处理。脚本不会删除原始业务数据。"
}
if (-not (Select-String -LiteralPath $taskLog -SimpleMatch 'STAGE4_COMPLETED' -Quiet)) {
    throw "未发现完成标记，请检查$taskLog。"
}
Write-Host "阶段4查询及基准核对通过。练习库：$DatabaseName；日志：$taskLog"
