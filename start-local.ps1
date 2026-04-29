param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $Root "tools\localctl.py"

function Test-PythonCommand {
    param(
        [string]$Command,
        [string[]]$Args = @()
    )

    try {
        & $Command @Args "-c" "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)" | Out-Null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

function Get-BootstrapPythonCommand {
    $venvPython = Join-Path $Root ".venv\Scripts\python.exe"
    $localAppData = [Environment]::GetFolderPath("LocalApplicationData")
    $programFiles = [Environment]::GetFolderPath("ProgramFiles")
    $candidates = @(
        @($venvPython),
        @(Join-Path $localAppData "Programs\Python\Python312\python.exe"),
        @(Join-Path $localAppData "Programs\Python\Python311\python.exe"),
        @(Join-Path $localAppData "Programs\Python\Python310\python.exe"),
        @(Join-Path $programFiles "Python312\python.exe"),
        @(Join-Path $programFiles "Python311\python.exe"),
        @(Join-Path $programFiles "Python310\python.exe"),
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("py", "-3.10"),
        @("python"),
        @("python3")
    )

    foreach ($candidate in $candidates) {
        $cmd = $candidate[0]
        $args = @()
        if ($candidate.Length -gt 1) {
            $args = $candidate[1..($candidate.Length - 1)]
        }

        if (($cmd -like "*.exe") -and (Test-Path $cmd)) {
            if (Test-PythonCommand -Command $cmd -Args $args) {
                return ,@($cmd) + $args
            }
            continue
        }

        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
            continue
        }

        if (Test-PythonCommand -Command $cmd -Args $args) {
            return ,@($cmd) + $args
        }
    }

    return $null
}

function Ensure-WinGet {
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        return
    }

    Write-Host "未检测到 winget，开始自动修复..."

    if (-not (Get-PackageProvider -Name NuGet -ListAvailable -ErrorAction SilentlyContinue)) {
        Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force | Out-Null
    }

    Set-PSRepository -Name PSGallery -InstallationPolicy Trusted
    Install-Module -Name Microsoft.WinGet.Client -Force -Repository PSGallery -Scope CurrentUser -AllowClobber | Out-Null
    Import-Module Microsoft.WinGet.Client -Force
    Repair-WinGetPackageManager -Force -Latest | Out-Null

    if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
        throw "WinGet 修复完成后仍未检测到 winget。"
    }
}

function Ensure-BootstrapPythonCommand {
    $pythonCmd = Get-BootstrapPythonCommand
    if ($pythonCmd) {
        return ,$pythonCmd
    }

    Ensure-WinGet
    Write-Host "未检测到可用于引导的 Python，开始自动安装系统 Python..."
    & winget install --id Python.Python.3.12 --exact --source winget --accept-source-agreements --accept-package-agreements --scope machine --silent
    if ($LASTEXITCODE -ne 0) {
        throw "winget 安装 Python 失败，退出码 $LASTEXITCODE"
    }

    $pythonCmd = Get-BootstrapPythonCommand
    if (-not $pythonCmd) {
        throw "系统 Python 安装后仍未检测到可用解释器。"
    }

    return ,$pythonCmd
}

$pythonCmd = Ensure-BootstrapPythonCommand
$pythonArgs = @()
if ($pythonCmd.Length -gt 1) {
    $pythonArgs = $pythonCmd[1..($pythonCmd.Length - 1)]
}

& $pythonCmd[0] @pythonArgs $ScriptPath "start" @RemainingArgs
exit $LASTEXITCODE
