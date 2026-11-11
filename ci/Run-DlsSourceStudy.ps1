#Requires -Version 7.0
param([Parameter(Mandatory)][string]$ResultsDir)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$harness = Split-Path $PSScriptRoot
. (Join-Path $harness 'scripts\common.ps1')
if ($env:GITHUB_ACTIONS -ne 'true' -or [Environment]::ProcessorCount -ne 4 -or
    (Get-NativeArchitecture) -ne 'arm64') { throw ' ERROR - Expected hosted four-job native Windows Arm.' }
$source = Join-Path $env:RUNNER_TEMP 'opencv-qualified-source'
$table = Join-Path $env:RUNNER_TEMP 'opencv-dls-table'
$tableHarness = Join-Path $env:RUNNER_TEMP 'opencv-dls-harness'
$python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$shell = (Get-Process -Id $PID).Path
Assert-Source $source
if (Test-Path -LiteralPath $ResultsDir) { throw ' ERROR - Choose a fresh study directory.' }
if (@(Get-Process | Where-Object ProcessName -Match '^(cl|MSBuild|cmake|link|ninja)$').Count) {
    throw ' ERROR - Another build tool is active.'
}
New-Item -ItemType Directory -Path $ResultsDir | Out-Null
$temp = Join-Path $env:RUNNER_TEMP 'opencv-dls-compiler-temp'
if (Test-Path -LiteralPath $temp) { throw ' ERROR - Compiler temp must be fresh.' }
New-Item -ItemType Directory -Path $temp | Out-Null
$env:TEMP = $temp
$env:TMP = $temp
$env:PYTHONDONTWRITEBYTECODE = '1'
$cases = @{
    original = @{ source = $source; harness = $harness; generator = 'MSBuild' }
    current = @{ source = $source; harness = $harness; generator = 'Ninja' }
    table = @{ source = $table; harness = $tableHarness; generator = 'Ninja' }
}
$frozen = @{}
foreach ($case in $cases.Values) {
    $case.build = Get-BuildDirectory $case.source $case.generator 'MSVC2026'
    $inputs = @(Get-Item -LiteralPath (Join-Path $case.build 'CMakeCache.txt'),
        (Join-Path $case.build 'benchmark-setup.json'))
    $patterns = if ($case.generator -eq 'MSBuild') { @('*.vcxproj', '*.props', '*.targets', '*.sln', '*.slnx') } else { @('*.ninja') }
    $inputs += @(Get-ChildItem -LiteralPath $case.build -File -Recurse -Include $patterns)
    foreach ($directory in @('scripts', 'tests', 'toolchains')) {
        $inputs += @(Get-ChildItem -LiteralPath (Join-Path $case.harness $directory) -File -Recurse |
            Where-Object Extension -NotIn @('.pyc'))
    }
    $inputs += Get-Item -LiteralPath (Join-Path $case.harness 'benchmark.json')
    foreach ($file in $inputs) { $frozen[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName).Hash }
}
foreach ($file in Get-ChildItem -LiteralPath $PSScriptRoot -File -Recurse) {
    if ($file.Extension -ne '.pyc') { $frozen[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName).Hash }
}
$power = (& powercfg /getactivescheme | Out-String).Trim()
if ($LASTEXITCODE) { throw ' ERROR - Power scheme query failed.' }
$study = [ordered]@{
    status = 'running'; jobs = 4; power_scheme = $power
    scope = 'Same-VM original MSBuild/current compiler, aligned Ninja, aligned Ninja plus DLS table.'
    order = @('warmup_original', 'warmup_current', 'warmup_table',
        'original_1', 'current_1', 'table_1', 'table_2', 'current_2', 'original_2')
    warmups_excluded = $true; pause_seconds = 30; runs = @(); frozen_sha256 = $frozen
    boundary = 'Release build invocation only; clean/configure/install/provision/version/capture/smoke excluded.'
    limitations = 'Two scored runs per case; source candidate only. No Debug, numerical-equivalence, runtime-performance or parity claim. Uploaded hashes are not retained-binary proof.'
}
$primaryFailure = $null
try {
    foreach ($label in $study.order) {
        Assert-Source $source
        foreach ($path in $frozen.Keys) {
            if ((Get-FileHash -LiteralPath $path).Hash -ne $frozen[$path]) { throw " ERROR - Frozen input changed: $path" }
        }
        if ((& powercfg /getactivescheme | Out-String).Trim() -ne $power) { throw ' ERROR - Power scheme changed.' }
        $name = ($label -replace '^warmup_', '') -replace '_[12]$', ''
        $case = $cases[$name]
        $options = if ($name -eq 'original') { @() } else { @('-Parallel', '4') }
        $study | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath (Join-Path $ResultsDir 'study.json')
        Start-Sleep -Seconds $study.pause_seconds
        & $shell -NoProfile -File (Join-Path $case.harness 'scripts\run.ps1') -Root $case.source `
            -ResultsDir $ResultsDir -Generator $case.generator -Toolchain MSVC2026 -Label $label @options
        if ($LASTEXITCODE) { throw " ERROR - Source study failed: $label" }
        $runs = @(Get-ChildItem -LiteralPath $ResultsDir -Directory | Where-Object Name -Like "*_$label")
        if ($runs.Count -ne 1) { throw " ERROR - Expected one receipt: $label" }
        $run = $runs[0]
        $receipt = Get-Content -LiteralPath (Join-Path $run.FullName 'metadata.json') -Raw | ConvertFrom-Json
        if ($receipt.status -ne 'succeeded') { throw " ERROR - Incomplete run: $label" }
        $dll = Get-InstalledOpenCVFile $case.build 'opencv_world4100.dll'
        & $python (Join-Path $PSScriptRoot 'generator-evidence.py') $case.build $run.FullName $dll.FullName --generator $case.generator
        if ($LASTEXITCODE) { throw " ERROR - Output capture failed: $label" }
        & $python (Join-Path $PSScriptRoot 'dls-source-evidence.py') capture --source $case.source --build $case.build `
            --run $run.FullName --generator $case.generator
        if ($LASTEXITCODE) { throw " ERROR - Source/object capture failed: $label" }
        $study.runs += @{
            label = $label; configuration = $name; generator = $case.generator
            warmup = $label.StartsWith('warmup_'); directory = $run.Name; build_seconds = $receipt.build_seconds
        }
        $study | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath (Join-Path $ResultsDir 'study.json')
        & $python (Join-Path $PSScriptRoot 'dls-source-evidence.py') compare --results $ResultsDir
        if ($LASTEXITCODE) { throw " ERROR - Workload parity failed: $label" }
    }
    & (Join-Path $harness 'tests\smoke_opencv.ps1') -Root $source -Generator MSBuild -Toolchain MSVC2026
    & $python (Join-Path $PSScriptRoot 'confirm-generator-outputs.py') $ResultsDir
    if ($LASTEXITCODE) { throw ' ERROR - Captured-output smoke failed.' }
    foreach ($path in $frozen.Keys) {
        if ((Get-FileHash -LiteralPath $path).Hash -ne $frozen[$path]) { throw " ERROR - Frozen input changed: $path" }
    }
    $study.status = 'succeeded-awaiting-local-evidence-audit'
} catch {
    $primaryFailure = $_
    $study.status = 'failed'
    $study['error'] = $_.Exception.Message
    throw
} finally {
    try {
        & (Join-Path $PSScriptRoot 'Remove-StudyRuntimeBinaries.ps1') -ResultsDir $ResultsDir
        foreach ($directory in Get-ChildItem -LiteralPath $ResultsDir -Directory) {
            $binaries = Join-Path $directory.FullName 'runtime-binaries'
            if (Test-Path -LiteralPath $binaries) { Remove-Item -LiteralPath $binaries -Recurse -Force }
        }
    } catch {
        $study.status = 'failed'
        $study['cleanup_error'] = $_.Exception.Message
        if ($null -eq $primaryFailure) { throw }
    } finally {
        $study | ConvertTo-Json -Depth 9 | Set-Content -LiteralPath (Join-Path $ResultsDir 'study.json')
    }
}
