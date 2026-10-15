param(
    [string]$Case = 'valve',
    [string]$OutputName = '',
    [ValidateSet('', 'validation', 'v03', 'exploratory', 'hardening')][string]$Study = '',
    [switch]$Tests
)
$ErrorActionPreference = 'Stop'
$monitorPath = Join-Path $PSScriptRoot 'scripts/run_video.ps1'
if (!(Test-Path -LiteralPath $monitorPath)) {
    $monitorPath = Join-Path $PSScriptRoot 'run_video.ps1'
}
& $monitorPath @PSBoundParameters
exit $LASTEXITCODE
