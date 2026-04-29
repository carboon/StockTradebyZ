param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path

if ($RemainingArgs -contains "--help" -or $RemainingArgs -contains "-h") {
    Write-Host "usage: .\uninstall-local.ps1"
    Write-Host ""
    Write-Host "停止本地服务，并清理当前项目生成的配置、依赖、构建产物和数据。"
    exit 0
}

function Write-Log {
    param([string]$Message)
    Write-Host $Message
}

function Remove-PathSafe {
    param([string]$Target)
    if (Test-Path $Target) {
        Remove-Item $Target -Recurse -Force
        Write-Log "已删除: $Target"
    }
}

Write-Log "开始卸载本地内容"
Write-Log "- 停止本地服务"
Write-Log "- 清理本目录生成的配置、依赖、构建产物和数据"

& (Join-Path $Root "stop-local.ps1") @RemainingArgs

$targets = @(
    (Join-Path $Root ".env"),
    (Join-Path $Root ".venv"),
    (Join-Path $Root ".pytest_cache"),
    (Join-Path $Root "frontend\.env.local"),
    (Join-Path $Root "frontend\node_modules"),
    (Join-Path $Root "frontend\dist"),
    (Join-Path $Root "frontend\coverage"),
    (Join-Path $Root ".coverage"),
    (Join-Path $Root "htmlcov"),
    (Join-Path $Root "data"),
    (Join-Path $Root "deploy")
)

foreach ($target in $targets) {
    Remove-PathSafe -Target $target
}

Get-ChildItem -Path $Root -Filter "__pycache__" -Directory -Recurse -ErrorAction SilentlyContinue |
    ForEach-Object {
        Remove-PathSafe -Target $_.FullName
    }

Write-Log "卸载完成"
