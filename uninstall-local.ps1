param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$RemainingArgs
)

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $Root "localctl.ps1") "uninstall" @RemainingArgs
exit $LASTEXITCODE
