param(
    [string]$Case = 'valve',
    [string]$OutputName = '',
    [ValidateSet('', 'validation', 'exploratory', 'hardening')][string]$Study = '',
    [switch]$Tests
)
$ErrorActionPreference = 'Stop'
$enginePath = Join-Path (Split-Path -Parent $PSScriptRoot) '04可复现材料包/run.ps1'
& $enginePath @PSBoundParameters
exit $LASTEXITCODE
