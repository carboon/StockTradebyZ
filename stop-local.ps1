param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$RunDir = Join-Path $Root "data\run"
$BackendPidFile = Join-Path $RunDir "backend.pid"
$FrontendPidFile = Join-Path $RunDir "frontend.pid"
$DefaultBackendPort = 8000
$DefaultFrontendPort = 5173

if ($RemainingArgs -contains "--help" -or $RemainingArgs -contains "-h") {
    Write-Host "usage: .\stop-local.ps1"
    Write-Host ""
    Write-Host "停止本地后端进程，并清理 pid 文件。"
    exit 0
}

function Write-Log {
    param([string]$Message)
    Write-Host $Message
}

function Read-EnvValue {
    param(
        [string]$Key,
        [string]$DefaultValue
    )

    $envFile = Join-Path $Root ".env"
    if (-not (Test-Path $envFile)) {
        return $DefaultValue
    }

    $line = Get-Content $envFile | Where-Object { $_ -match "^$Key=" } | Select-Object -Last 1
    if (-not $line) {
        return $DefaultValue
    }

    $parts = $line -split "=", 2
    if ($parts.Length -lt 2 -or [string]::IsNullOrWhiteSpace($parts[1])) {
        return $DefaultValue
    }

    return $parts[1].Trim()
}

function Read-Pid {
    param([string]$PidFile)
    if (-not (Test-Path $PidFile)) {
        return $null
    }

    $content = (Get-Content $PidFile -Raw).Trim()
    if (-not $content) {
        return $null
    }

    [int]$pidValue = 0
    if ([int]::TryParse($content, [ref]$pidValue)) {
        return $pidValue
    }

    return $null
}

function Process-Exists {
    param([int]$Pid)
    try {
        $null = Get-Process -Id $Pid -ErrorAction Stop
        return $true
    } catch {
        return $false
    }
}

function Stop-Pid {
    param(
        [int]$Pid,
        [string]$Label
    )

    if (-not (Process-Exists -Pid $Pid)) {
        return $false
    }

    Stop-Process -Id $Pid -Force -ErrorAction SilentlyContinue
    Start-Sleep -Milliseconds 300

    if (Process-Exists -Pid $Pid) {
        Write-Log "$Label 停止失败 (PID=$Pid)"
        return $false
    }

    Write-Log "$Label 已停止 (PID=$Pid)"
    return $true
}

function Get-PortPids {
    param([int]$Port)

    $matches = @()
    $lines = netstat -ano -p tcp | Select-String -Pattern "LISTENING"
    foreach ($line in $lines) {
        $parts = ($line.ToString() -split "\s+") | Where-Object { $_ }
        if ($parts.Length -lt 5) {
            continue
        }

        $localAddress = $parts[1]
        $state = $parts[3]
        $pidText = $parts[4]
        if ($state -ne "LISTENING" -or -not $localAddress.EndsWith(":$Port")) {
            continue
        }

        [int]$pidValue = 0
        if ([int]::TryParse($pidText, [ref]$pidValue)) {
            $matches += $pidValue
        }
    }

    return $matches | Sort-Object -Unique
}

function Stop-Target {
    param(
        [string]$PidFile,
        [string]$Label,
        [int]$Port
    )

    $stopped = $false
    $pid = Read-Pid -PidFile $PidFile
    if ($pid -and (Process-Exists -Pid $pid)) {
        $stopped = Stop-Pid -Pid $pid -Label $Label
    } else {
        foreach ($fallbackPid in Get-PortPids -Port $Port) {
            $stopped = (Stop-Pid -Pid $fallbackPid -Label "$Label:$Port") -or $stopped
        }
    }

    if (-not $stopped) {
        Write-Log "$Label 未运行"
    }

    if (Test-Path $PidFile) {
        Remove-Item $PidFile -Force -ErrorAction SilentlyContinue
    }
}

$backendPort = [int](Read-EnvValue -Key "BACKEND_PORT" -DefaultValue "$DefaultBackendPort")
$frontendPort = [int](Read-EnvValue -Key "FRONTEND_PORT" -DefaultValue "$DefaultFrontendPort")

Stop-Target -PidFile $BackendPidFile -Label "后端" -Port $backendPort
Stop-Target -PidFile $FrontendPidFile -Label "旧前端 dev server" -Port $frontendPort
