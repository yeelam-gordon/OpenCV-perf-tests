#Requires -Version 7.0
param(
    [Parameter(Mandatory)][string]$ResultsDir,
    [string]$SourceRoot = '',
    [switch]$IncludeOriginal,
    [switch]$ClServerStudy
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$root = Split-Path $PSScriptRoot
$harness = $root
$source = if ($SourceRoot) { [IO.Path]::GetFullPath($SourceRoot) } else {
    Join-Path $env:RUNNER_TEMP 'opencv-qualified-source'
}
$python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
. (Join-Path $harness 'scripts\common.ps1')
Assert-Source $source
if ($ClServerStudy) {
    if ($env:GITHUB_ACTIONS -ne 'true' -or [Environment]::ProcessorCount -ne 4 -or
        (Get-NativeArchitecture) -ne 'arm64') { throw ' ERROR - Expected hosted four-core Windows Arm.' }
    foreach ($name in @('EnableClServerMode', 'MultiProcCL', 'MultiProcMaxCount', 'EnforceProcessCountAcrossBuilds')) {
        if ([Environment]::GetEnvironmentVariable($name)) { throw " ERROR - Unset inherited MSBuild profile $name." }
    }
}
if (Test-Path -LiteralPath $ResultsDir) { throw ' ERROR - Choose a fresh study directory.' }
$competing = @(Get-Process | Where-Object ProcessName -Match '^(cl|MSBuild|cmake|link|ninja)$')
if ($competing.Count) { throw ' ERROR - Another build tool is active.' }
New-Item -ItemType Directory -Path $ResultsDir | Out-Null
$previousTemp = $env:TEMP
$previousTmp = $env:TMP
$temp = if ($ClServerStudy) {
    $owned = Join-Path $env:RUNNER_TEMP ("opencv-clserver-" + [guid]::NewGuid().ToString('N'))
    if ($owned -match '\s') { throw ' ERROR - Runner-owned compiler TEMP must be whitespace-free.' }
    $owned
} else { Join-Path (Split-Path $source) ('compiler-temp-' + [IO.Path]::GetFileName($ResultsDir.TrimEnd('\'))) }
if (Test-Path -LiteralPath $temp) { throw ' ERROR - Study temp path already exists.' }
New-Item -ItemType Directory -Path $temp | Out-Null
$env:TEMP = $temp
$env:TMP = $temp
$env:PYTHONDONTWRITEBYTECODE = '1'
$shell = (Get-Process -Id $PID).Path
$study = [ordered]@{
    status = 'running'
    scope = 'Same-host original HOBL payload: native MSVC/Ninja versus shared-MSBuild; no compiler migration.'
    source = $source
    toolchain = 'MSVC2026'
    jobs = [Environment]::ProcessorCount
    order = if ($IncludeOriginal) {
        @('warmup_original', 'warmup_shared', 'warmup_ninja',
            'original_1', 'shared_1', 'ninja_1', 'ninja_2', 'shared_2', 'original_2')
    } else {
        @('warmup_shared', 'warmup_ninja', 'shared_1', 'ninja_1', 'ninja_2', 'shared_2')
    }
    original_reference_included = [bool]$IncludeOriginal
    warmups_excluded = $true
    pause_seconds = 30
    compiler_temp = $temp
    runs = @()
}
if ($ClServerStudy) {
    $study.scope = 'New same-VM native MSVC/MSBuild cohort: original default MP versus shared budget4 plus CL-server.'
    $study.order = @('warmup_original', 'warmup_server', 'original_1', 'server_1', 'server_2', 'original_2')
    $study.original_reference_included = $true
    $study['limitations'] = 'Different-residency resource profile; not a four-resident/busy/global cap. Two scored observations per case; no historical/local transfer, forecast or adoption.'
}
$frozen = @{}
$builds = @{}
$cleanupScript = Join-Path $PSScriptRoot 'Remove-StudyRuntimeBinaries.ps1'
$primaryFailure = $null
try {
    $generators = if ($ClServerStudy) { @('MSBuild') } else { @('MSBuild', 'Ninja') }
    foreach ($generator in $generators) {
        $build = Get-BuildDirectory $source $generator 'MSVC2026'
        $builds[$generator] = $build
        $inputs = @(Get-Item -LiteralPath (Join-Path $build 'CMakeCache.txt'),
            (Join-Path $build 'benchmark-setup.json'))
        $setup = Get-Content -LiteralPath (Join-Path $build 'benchmark-setup.json') -Raw | ConvertFrom-Json
        if ($setup.initial_cache) {
            $cacheFile = Get-Item -LiteralPath $setup.initial_cache.path
            if ((Get-FileHash -LiteralPath $cacheFile.FullName).Hash -ne $setup.initial_cache.sha256) {
                throw ' ERROR - Initial cache changed since configuration.'
            }
            $inputs += $cacheFile
        }
        if ($generator -eq 'MSBuild') {
            $inputs += @(Get-ChildItem -LiteralPath $build -Recurse -File -Include *.sln,*.slnx,*.vcxproj,*.props,*.targets)
        } else {
            $inputs += @(Get-Item -LiteralPath (Join-Path $build 'build.ninja'), (Join-Path $build 'CMakeFiles\rules.ninja'))
        }
        foreach ($file in $inputs) { $frozen[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName).Hash }
    }
    foreach ($path in @($PSCommandPath,     (Join-Path $PSScriptRoot 'generator-evidence.py'),
    (Join-Path $PSScriptRoot 'confirm-generator-outputs.py'),
    $cleanupScript,
        (Join-Path $harness 'scripts\run.ps1'), (Join-Path $harness 'scripts\common.ps1'),
        (Join-Path $harness 'benchmark.json'), (Join-Path $harness 'toolchains\vs2026.json'))) {
        $frozen[$path] = (Get-FileHash -LiteralPath $path).Hash
    }
    if ($ClServerStudy) {
        if (-not ('BuildAccounting' -as [type])) { Add-Type -Path (Join-Path $harness 'scripts\BuildAccounting.cs') }
        $plan = Join-Path $ResultsDir 'native-plan.json'
        & $python (Join-Path $PSScriptRoot 'msbuild-clserver-evidence.py') plan --source $source --build $builds.MSBuild --plan $plan
        if ($LASTEXITCODE) { throw ' ERROR - Native MSBuild source/profile plan failed.' }
        $nativePlan = Get-Content -LiteralPath $plan -Raw | ConvertFrom-Json
        $setup = Get-Content -LiteralPath (Join-Path $builds.MSBuild 'benchmark-setup.json') -Raw | ConvertFrom-Json
        $inputs = @(Get-Item -LiteralPath $plan, $nativePlan.stock_server_targets,
            $setup.compiler, $setup.cmake, $setup.build_engine.path, $setup.build_engine.linker)
        $inputs += @(Get-ChildItem -LiteralPath $builds.MSBuild -Recurse -File -Include *.cmake)
        foreach ($name in @('cvconfig.h', 'opencv2\opencv_modules.hpp', 'cv_cpu_config.h')) {
            $inputs += Get-Item -LiteralPath (Join-Path $builds.MSBuild $name)
        }
        foreach ($directory in @('scripts', 'ci', 'tests', 'toolchains')) {
            $inputs += @(Get-ChildItem -LiteralPath (Join-Path $harness $directory) -Recurse -File |
                Where-Object Extension -NotIn @('.pyc'))
        }
        foreach ($file in $inputs) { $frozen[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName).Hash }
        $study['native_plan'] = $plan
    }
    $power = (& powercfg /getactivescheme | Out-String).Trim()
    if ($LASTEXITCODE) { throw ' ERROR - Power scheme query failed.' }
    $study['power_scheme'] = $power
    $study['frozen_sha256'] = $frozen
    foreach ($label in $study.order) {
        Assert-Source $source
        foreach ($path in $frozen.Keys) {
            if ((Get-FileHash -LiteralPath $path).Hash -ne $frozen[$path]) { throw " ERROR - Frozen input changed: $path" }
        }
        if ((& powercfg /getactivescheme | Out-String).Trim() -ne $power) { throw ' ERROR - Power scheme changed.' }
        $generator = if ($label -match 'ninja') { 'Ninja' } else { 'MSBuild' }
        $options = @()
        if ($label -notmatch 'original') { $options += @('-Parallel', "$($study.jobs)") }
        if ($label -match 'shared') {
            $options += @('-MSBuildScheduler', 'MultiToolTask', '-CompilerJobs', "$($study.jobs)", '-SharedCompilerLimit')
        }
        if ($ClServerStudy) {
            $options = @('-MSBuildStudyPlan', $plan)
            if ($label -match 'server') {
                $options += @('-Parallel', '4', '-MSBuildScheduler', 'MultiToolTask', '-CompilerJobs', '4',
                    '-SharedCompilerLimit', '-EnableClServerMode')
            }
        }
        $study | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ResultsDir 'study.json')
        Start-Sleep -Seconds $study.pause_seconds
        & $shell -NoProfile -File (Join-Path $harness 'scripts\run.ps1') -Root $source `
            -ResultsDir $ResultsDir -Generator $generator -Toolchain MSVC2026 -Label $label @options
        if ($LASTEXITCODE) { throw " ERROR - Generator study failed: $label" }
        $runs = @(Get-ChildItem -LiteralPath $ResultsDir -Directory | Where-Object Name -Like "*_$label")
        if ($runs.Count -ne 1) { throw " ERROR - Expected one run receipt: $label" }
        $run = $runs[0]
        $receipt = Get-Content -LiteralPath (Join-Path $run.FullName 'metadata.json') -Raw | ConvertFrom-Json
        if ($receipt.status -ne 'succeeded') { throw " ERROR - Incomplete run: $label" }
        $dll = Get-InstalledOpenCVFile $builds[$generator] 'opencv_world4100.dll'
        if ($ClServerStudy) {
            $proof = Get-Content -LiteralPath (Join-Path $run.FullName 'native-output.json') -Raw | ConvertFrom-Json
            $library = Get-InstalledOpenCVFile $builds.MSBuild 'opencv_world4100.lib'
            foreach ($binding in @(@($dll.FullName, 'bin/Release/opencv_world4100.dll'),
                                   @($library.FullName, 'lib/Release/opencv_world4100.lib'))) {
                if ((Get-FileHash -LiteralPath $binding[0]).Hash.ToLowerInvariant() -ne
                    $proof.binaries.($binding[1])) { throw ' ERROR - Direct install changed retained native outputs.' }
            }
            $smokeArguments = "-NoProfile -File `"$(Join-Path $harness 'tests\smoke_opencv.ps1')`" -Root `"$source`" -Generator MSBuild -Toolchain MSVC2026"
            $smoke = [BuildAccounting]::RunOwned($shell, $smokeArguments, $harness, (Join-Path $run.FullName 'native-smoke.log'))
            if ($smoke.ExitCode) { throw ' ERROR - Untimed owned native smoke failed.' }
            @{
                status = 'passed'; dll_sha256 = (Get-FileHash -LiteralPath $dll.FullName).Hash
                import_library_sha256 = (Get-FileHash -LiteralPath $library.FullName).Hash
                scope = 'Direct install matched pre-install timed outputs; untimed common native link/execution smoke passed.'
            } | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $run.FullName 'installed-output.json')
        } else {
            & $python (Join-Path $PSScriptRoot 'generator-evidence.py') $builds[$generator] $run.FullName `
                $dll.FullName --generator $generator
            if ($LASTEXITCODE) { throw " ERROR - Evidence retention failed: $label" }
        }
        $study.runs += @{
            label = $label; generator = $generator; warmup = $label.StartsWith('warmup_')
            configuration = if ($label -match 'original') { 'original' } elseif ($ClServerStudy) { 'server' } elseif ($label -match 'shared') { 'shared' } else { 'ninja' }
            directory = $run.Name; build_seconds = $receipt.build_seconds
        }
        $study | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ResultsDir 'study.json')
        if ($ClServerStudy) {
            & $python (Join-Path $PSScriptRoot 'msbuild-clserver-evidence.py') compare --results $ResultsDir
            if ($LASTEXITCODE) { throw ' ERROR - Paired native workload parity failed.' }
        }
    }
    foreach ($path in $frozen.Keys) {
        if ((Get-FileHash -LiteralPath $path).Hash -ne $frozen[$path]) { throw " ERROR - Frozen input changed: $path" }
    }
    if ((& powercfg /getactivescheme | Out-String).Trim() -ne $power) { throw ' ERROR - Power scheme changed.' }
    if (-not $ClServerStudy) {
        & (Join-Path $harness 'tests\smoke_opencv.ps1') -Root $source -Generator MSBuild -Toolchain MSVC2026
    }
    $study | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ResultsDir 'study.json')
    & $python (Join-Path $PSScriptRoot 'confirm-generator-outputs.py') $ResultsDir
    if ($LASTEXITCODE) { throw ' ERROR - Captured retained-output smoke verification failed.' }
    $study.status = 'succeeded-awaiting-input-and-statistical-audit'
} catch {
    $primaryFailure = $_
    $study.status = 'failed'
    $study['error'] = $_.Exception.Message
    throw
} finally {
    $cleanupFailure = $null
    try {
        if (-not (Test-Path variable:ClServerStudy) -or -not $ClServerStudy) { & $cleanupScript -ResultsDir $ResultsDir }
        else {
            $env:TEMP = $previousTemp
            $env:TMP = $previousTmp
            Remove-Item -LiteralPath $temp -Recurse -Force
        }
    }
    catch {
        $cleanupFailure = $_
        $study.status = 'failed'
        $study['cleanup_error'] = $_.Exception.Message
        if ($null -eq $primaryFailure) { $study['error'] = $_.Exception.Message }
    }
    $study | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $ResultsDir 'study.json')
    if ($null -ne $cleanupFailure -and $null -eq $primaryFailure) { throw $cleanupFailure }
}
