param(
    [string]$Case = 'valve',
    [ValidateSet('', 'validation', 'v03', 'exploratory', 'hardening')][string]$Study,
    [switch]$Tests,
    [string]$OutputName = ''
)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
if (Test-Path -LiteralPath (Join-Path $root 'environment/runtime.json')) {
    # The same file runs from the delivered engineering project's scripts/.
    $projectPath = $root
} else {
    $projects = @(Get-ChildItem -LiteralPath (Join-Path $root 'submission') -Directory |
        Where-Object { $_.Name -like '04*' })
    if ($projects.Count -ne 1) { throw 'Cannot uniquely locate submission/04 project.' }
    $projectPath = $projects[0].FullName
}
$config = Get-Content -LiteralPath (Join-Path $projectPath 'environment/runtime.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$docker = (Get-Command docker -ErrorAction Stop).Source
$engine = & $docker info --format '{{.OSType}}' 2>$null
if ($LASTEXITCODE -ne 0 -or $engine -ne 'linux') { throw 'Start the Docker Desktop Linux engine first.' }
if (!$OutputName) {
    $kind = if ($Tests) { 'tests' } elseif ($Study) { $Study } else { [IO.Path]::GetFileNameWithoutExtension($Case) }
    $OutputName = 'video-' + $kind + '-' + (Get-Date -Format 'yyyyMMdd-HHmmss-fff')
}
if ($OutputName -notmatch '^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}$') { throw 'Invalid output name.' }
$outputPath = Join-Path $projectPath ('results/' + $OutputName)
if (!$Tests -and (Test-Path -LiteralPath $outputPath)) { throw 'Output already exists; choose a fresh name.' }
$present = & $docker image ls --no-trunc --quiet $config.image
if ($LASTEXITCODE -ne 0) { throw 'Cannot inspect Docker images.' }
if ($present -ne $config.image_id) {
    $archive = Join-Path $projectPath $config.archive
    Write-Host 'Verifying and importing the supplied image...'
    if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash.ToLowerInvariant() -ne $config.archive_sha256) {
        throw 'Image archive checksum mismatch.'
    }
    & $docker load --input $archive
    if ($LASTEXITCODE -ne 0) { throw 'Image import failed.' }
    $present = & $docker image inspect --format '{{.Id}}' $config.image
    if ($LASTEXITCODE -ne 0 -or $present -ne $config.image_id) { throw 'Image identity mismatch.' }
}
$containerName = 'cfd-video-' + [guid]::NewGuid().ToString('N').Substring(0, 12)
$dockerArgs = @('run', '--rm', '--name', $containerName, '--platform', 'linux/amd64',
    '--mount', "type=bind,source=$projectPath,target=/work",
    '-e', 'CFD_RUN_IN_CONTAINER=1', '-e', "CFD_IMAGE_REF=$($config.image)",
    '-e', "CFD_IMAGE_ID=$($config.image_id)", $config.image,
    'python', '-u', '/work/scripts/portable_run.py', '--case', $Case, '--output-name', $OutputName)
if ($Study) {
    # Support both the working-source and delivered names of the validation study.
    $studyArgument = $Study
    if ($Study -in @('validation', 'v03')) {
        $studyArgument = if (Test-Path -LiteralPath (Join-Path $projectPath 'scripts/study_validation.py')) { 'validation' } else { 'v03' }
    }
    $dockerArgs += @('--study', $studyArgument)
}
if ($Tests) { $dockerArgs += '--tests' }
$seen = @{}
function Show-Status {
    if ($Tests -or !(Test-Path -LiteralPath $outputPath)) { return }
    $paths = @(Join-Path $outputPath 'status.json')
    if ($Study) {
        $paths = @(Get-ChildItem -LiteralPath $outputPath -Directory | ForEach-Object {
            Join-Path $_.FullName 'status.json'
        })
    }
    foreach ($path in $paths) {
        if (!(Test-Path -LiteralPath $path)) { continue }
        try { $s = Get-Content -LiteralPath $path -Raw -Encoding UTF8 | ConvertFrom-Json }
        catch { continue } # The solver may be replacing the status file atomically.
        $key = "$($s.state):$($s.accepted_windows)"
        if ($seen[$path] -eq $key) { continue }
        $seen[$path] = $key
        $label = Split-Path -Leaf (Split-Path -Parent $path)
        if ($s.latest) {
            $r = $s.latest
            Write-Host ('[{0}] t={1:F6}/{2:G} s | mdot={3:G6} kg/s | p={4:G6} Pa | T={5:F3} K | alpha={6:F5} | opening={7:F2} | windows={8} | {9}' -f
                $label, $r.time_s, $s.end_time_s, $r.mdot_kg_s, $r.back_pressure_pa,
                $r.temperature_k, $r.phase_fraction, $r.opening, $s.accepted_windows, $s.state)
        } else { Write-Host "[$label] $($s.state): $($s.error)" }
    }
}
Write-Host 'Live monitor: accepted solver windows; time is simulation time.'
Write-Host 'Fields: t [s], mdot [kg/s], p [Pa], T [K], alpha [-], opening [-], windows.'
if (!$Study -and !$Tests -and $Case -eq 'steady') {
    Write-Host 'Steady case: T=300 K and alpha=1 are fixed isothermal single-phase values.'
}
if (!$Tests) { Write-Host "Results: $outputPath" }
$job = $null
$finished = $false
$resultCode = 1
try {
    $job = Start-Job -ArgumentList $docker, $dockerArgs -ScriptBlock {
        param($exe, $arguments)
        & $exe @arguments 2>&1 | ForEach-Object { $_.ToString() }
        if ($LASTEXITCODE -ne 0) { throw "Docker runner exited with code $LASTEXITCODE" }
    }
    while ($job.State -in @('Running', 'NotStarted')) {
        Receive-Job -Job $job -ErrorAction Continue | ForEach-Object { Write-Host $_ }
        Show-Status
        Start-Sleep -Milliseconds 500
    }
    Receive-Job -Job $job -ErrorAction Continue | ForEach-Object { Write-Host $_ }
    Show-Status
    if ($job.State -ne 'Completed') { throw 'Run failed. Inspect the retained logs.' }
    $recordsPath = Join-Path $outputPath 'execution_records.json'
    if ($Study -and (Test-Path -LiteralPath $recordsPath)) {
        $records = @(Get-Content -LiteralPath $recordsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
        $failed = @($records | Where-Object { !$_.verified })
        if ($failed.Count) { throw "Study contains $($failed.Count) unverified run(s); inspect execution_records.json." }
    }
    $finished = $true
    $resultCode = 0
    Write-Host 'RUN AND CHECKS COMPLETED' -ForegroundColor Green
} finally {
    if (!$finished -and $job) {
        # Stop only this wrapper's uniquely named container.
        try { & $docker stop --time 3 $containerName 2>$null | Out-Null } catch { }
        Stop-Job -Job $job -ErrorAction SilentlyContinue
    }
    if ($job) { Remove-Job -Job $job -Force -ErrorAction SilentlyContinue }
}
exit $resultCode
