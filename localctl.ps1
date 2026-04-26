param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Command,

    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$ScriptPath = Join-Path $Root "tools\localctl.py"

function Get-PythonCommand {
    $candidates = @(
        @("py", "-3.12"),
        @("py", "-3.11"),
        @("python"),
        @("python3")
    )

    foreach ($candidate in $candidates) {
        $cmd = $candidate[0]
        if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
            continue
        }

        $args = @()
        if ($candidate.Length -gt 1) {
            $args = $candidate[1..($candidate.Length - 1)]
        }

        try {
            & $cmd @args "-c" "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" | Out-Null
            if ($LASTEXITCODE -eq 0) {
                return ,@($cmd) + $args
            }
        } catch {
        }
    }

    throw "未找到可用的 Python 3.11+。请先安装 Python 再重试。"
}

$pythonCmd = Get-PythonCommand
$pythonArgs = @()
if ($pythonCmd.Length -gt 1) {
    $pythonArgs = $pythonCmd[1..($pythonCmd.Length - 1)]
}

& $pythonCmd[0] @pythonArgs $ScriptPath $Command @RemainingArgs
exit $LASTEXITCODE
