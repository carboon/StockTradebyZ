param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root "localctl.ps1") "bootstrap" @RemainingArgs
exit $LASTEXITCODE
