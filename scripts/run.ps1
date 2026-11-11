#Requires -Version 7.0
param(
    [string]$Root = '',
    [string]$ResultsDir = "$PSScriptRoot\..\results\local",
    [ValidatePattern('^[A-Za-z0-9_-]+$')][string]$Label = 'hobl_baseline',
    [ValidateSet('MSBuild', 'Ninja')][string]$Generator = 'MSBuild',
    [ValidateSet('MSVC', 'Clang', 'MSVC2026', 'MSVC2026Latest')][string]$Toolchain = 'MSVC',
    [ValidateRange(0, 256)][int]$Parallel = 0,
    [switch]$Profile,
    [switch]$MeasureCpu,
    [switch]$Trace,
    [switch]$BinaryLog,
    [ValidateSet('Default', 'MultiToolTask')][string]$MSBuildScheduler = 'Default',
    [ValidateRange(1, 256)][int]$CompilerJobs = 12,
    [switch]$SharedCompilerLimit,
    [switch]$EnableClServerMode,
    [string]$MSBuildStudyPlan = ''
)
. "$PSScriptRoot\common.ps1"
Assert-NoPendingToolchainRestart
Assert-WindowsSDKRestart
if ($Trace) { $MeasureCpu = $true }
if ($MeasureCpu -and $Profile) { throw ' ERROR - Keep CPU accounting and MSBuild PerformanceSummary runs separate.' }
if ($MeasureCpu) { . "$PSScriptRoot\measure_build.ps1" }
if ($Toolchain -eq 'Clang' -and -not $PSBoundParameters.ContainsKey('Label')) { $Label = 'clang_experiment' }
if ($Toolchain -eq 'MSVC2026' -and -not $PSBoundParameters.ContainsKey('Label')) { $Label = 'vs2026_experiment' }
if ($Toolchain -eq 'MSVC2026Latest' -and -not $PSBoundParameters.ContainsKey('Label')) { $Label = 'vs2026_latest_experiment' }
$Root = Get-SourceRoot $Root
$Generator = Get-EffectiveGenerator $Generator $Toolchain ($PSBoundParameters.ContainsKey('Generator'))
if (($BinaryLog -or $MSBuildScheduler -ne 'Default') -and $Generator -ne 'MSBuild') {
    throw ' ERROR - BinaryLog and MSBuildScheduler require MSBuild.'
}
if ($PSBoundParameters.ContainsKey('CompilerJobs') -and $MSBuildScheduler -eq 'Default') {
    throw ' ERROR - CompilerJobs is only used with the MultiToolTask scheduler.'
}
if ($SharedCompilerLimit -and $MSBuildScheduler -ne 'MultiToolTask') {
    throw ' ERROR - SharedCompilerLimit requires the MultiToolTask scheduler.'
}
if ($EnableClServerMode -and (-not $SharedCompilerLimit -or $MSBuildScheduler -ne 'MultiToolTask')) {
    throw ' ERROR - CL server requires the explicit shared MultiToolTask candidate.'
}
if ($MSBuildStudyPlan -and ($Generator -ne 'MSBuild' -or $Profile -or $MeasureCpu -or $BinaryLog)) {
    throw ' ERROR - The paired MSBuild study uses owned wall timing without profiling.'
}
if ($EnableClServerMode -and -not $MSBuildStudyPlan) {
    throw ' ERROR - CL server requires the paired owned-lifecycle plan.'
}
if ($MSBuildStudyPlan) {
    if ($EnableClServerMode) {
        if ($Parallel -ne 4 -or $CompilerJobs -ne 4) {
            throw ' ERROR - The paired MSBuild study candidate requires budget4 settings.'
        }
    } elseif ($MSBuildScheduler -ne 'Default' -or $Parallel -ne 0 -or $SharedCompilerLimit) {
        throw ' ERROR - The paired MSBuild study original must keep scheduling defaults.'
    }
}
$schedulerArguments = @()
if ($MSBuildScheduler -eq 'MultiToolTask') {
    $schedulerArguments = @('/p:MultiProcCL=true', "/p:MultiProcMaxCount=$CompilerJobs")
    if (-not $PSBoundParameters.ContainsKey('Label')) { $Label = 'msbuild_multitool_experiment' }
    if ($SharedCompilerLimit) {
        # Fresh worker nodes keep CPU attribution and subsequent runs isolated.
        $schedulerArguments += @('/p:EnforceProcessCountAcrossBuilds=true', '/nr:false')
        if (-not $PSBoundParameters.ContainsKey('Label')) { $Label = 'msbuild_multitool_shared_experiment' }
    }
    if ($EnableClServerMode) { $schedulerArguments += '/p:EnableClServerMode=true' }
}
Assert-Source $Root
$buildDir = Get-BuildDirectory $Root $Generator $Toolchain
if (-not (Test-Path "$buildDir\benchmark-setup.json")) { throw ' ERROR - Run setup.ps1 for this generator first.' }
$receipt = Get-Content "$buildDir\benchmark-setup.json" -Raw | ConvertFrom-Json
Assert-WindowsSDK $receipt $Toolchain
$receiptToolchain = if ($receipt.PSObject.Properties.Name -contains 'toolchain') { $receipt.toolchain } else { 'MSVC' }
if ($receiptToolchain -ne $Toolchain) { throw ' ERROR - Toolchain does not match the configured build directory.' }
if ($receipt.config_sha256 -ne (Get-FileHash "$PSScriptRoot\..\benchmark.json").Hash) {
    throw ' ERROR - Benchmark configuration changed; rerun setup.'
}
if ($receipt.compiler_sha256 -ne (Get-FileHash $receipt.compiler).Hash) {
    throw ' ERROR - Compiler changed since setup; rerun setup.'
}
if ($Generator -eq 'MSBuild') {
    $vsMajor = if ($Toolchain -in @('MSVC2026', 'MSVC2026Latest')) { 18 } else { 17 }
    $currentVS = Get-VisualStudio $vsMajor
    foreach ($field in @('path', 'version', 'tools', 'toolset')) {
        if ($currentVS.$field -ne $receipt.visual_studio.$field) {
            throw ' ERROR - Visual Studio instance or default toolset changed since setup; rerun setup.'
        }
    }
}
foreach ($name in @('CL', '_CL_', 'CMAKE_BUILD_PARALLEL_LEVEL', 'CMAKE_GENERATOR', 'CXXFLAGS', 'CFLAGS')) {
    if ([Environment]::GetEnvironmentVariable($name)) { throw " ERROR - Unset $name before benchmarking." }
}
$cmakeExe = Get-CMake $receipt.cmake (Get-ToolchainCMakeVersion $Toolchain)
if ($receipt.PSObject.Properties.Name -contains 'cmake_sha256' -and
    (Get-FileHash $cmakeExe).Hash -ne $receipt.cmake_sha256) {
    throw ' ERROR - CMake changed since setup; rerun setup.'
}
if ($receipt.PSObject.Properties.Name -contains 'build_engine' -and $receipt.build_engine) {
    if ((Get-FileHash $receipt.build_engine.path).Hash -ne $receipt.build_engine.sha256 -or
        (Get-FileHash $receipt.build_engine.linker).Hash -ne $receipt.build_engine.linker_sha256) {
        throw ' ERROR - MSBuild or linker changed since setup; rerun setup.'
    }
}
if ($Generator -eq 'Ninja') {
    if ($Profile) { throw ' ERROR - Profile uses MSBuild PerformanceSummary; Ninja already records per-step timings.' }
    Set-NativeToolchain $receipt.visual_studio $receipt.windows_sdk
    if ($Toolchain -eq 'Clang') {
        foreach ($name in @('c', 'cxx', 'linker', 'ar', 'ranlib')) {
            Assert-NativeExecutable $receipt.llvm.$name $receipt.architecture
            if ((Get-FileHash $receipt.llvm.$name).Hash -ne $receipt.llvm."${name}_sha256") {
                throw " ERROR - Clang tool changed since setup: $name"
            }
        }
        $env:PATH = "$($receipt.llvm.root)\bin;$env:PATH"
    }
}
$ResultsDir = [IO.Path]::GetFullPath($ResultsDir, (Get-Location).ProviderPath)
$runDir = Join-Path $ResultsDir ("{0}_{1}" -f (Get-Date -Format 'yyyyMMdd_HHmmss_fff'), $Label)
New-Item -ItemType Directory -Force $runDir | Out-Null
$metadata = [ordered]@{
    status = 'running'
    label = $Label
    started_at = (Get-Date).ToString('o')
    generator = $Generator
    toolchain = $Toolchain
    parallel = $Parallel
    profile = [bool]$Profile
    measure_cpu = [bool]$MeasureCpu
    wpr_trace = [bool]$Trace
    binary_log = [bool]$BinaryLog
    msbuild_scheduler = $MSBuildScheduler
    compiler_jobs = if ($MSBuildScheduler -ne 'Default') { $CompilerJobs } else { $null }
    shared_compiler_limit = [bool]$SharedCompilerLimit
    enable_cl_server_mode = [bool]$EnableClServerMode
    setup = $receipt
    cpu = (Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors)
    memory_gib = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)
    os = (Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture)
    power_scheme = (& powercfg /getactivescheme | Out-String).Trim()
    runner_sha256 = (Get-FileHash $PSCommandPath).Hash
}
$installationReceipt = "$PSScriptRoot\..\.tools\vs2026-installation.json"
if (Test-Path $installationReceipt) {
    $metadata['tool_installation'] = Get-Content $installationReceipt -Raw | ConvertFrom-Json
    $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()
    $metadata['rebooted_since_tool_installation'] =
        [datetimeoffset]$boot -ne [datetimeoffset]$metadata.tool_installation.boot_time
}
$sdkInstallationReceipt = "$PSScriptRoot\..\.tools\windows-sdk-installation.json"
if (Test-Path $sdkInstallationReceipt) {
    $metadata['sdk_installation'] = Get-Content $sdkInstallationReceipt -Raw | ConvertFrom-Json
}
$metadata | ConvertTo-Json -Depth 8 | Set-Content "$runDir\metadata.json"
$lock = $null
if ($MSBuildStudyPlan) {
    . "$PSScriptRoot\owned_build.ps1"
    if (-not ('BuildAccounting' -as [type])) { Add-Type -Path "$PSScriptRoot\BuildAccounting.cs" }
}
try {
    # Exclusive per-source lock prevents our MSBuild and Ninja experiments overlapping.
    $lock = [IO.File]::Open("$Root\.hobl-benchmark.lock", 'OpenOrCreate', 'ReadWrite', 'None')
    Push-Location $buildDir
    try {
        $cleanArguments = @('--build', '.', '--target', 'clean', '--config', 'Release')
        if ($schedulerArguments.Count) { $cleanArguments += @('--') + $schedulerArguments }
        $clean = Invoke-Logged $cmakeExe $cleanArguments "$runDir\clean.log"
        if ($MSBuildStudyPlan) {
            & python "$PSScriptRoot\..\ci\msbuild-clserver-evidence.py" clean --source $Root --build $buildDir --run $runDir --plan $MSBuildStudyPlan
            if ($LASTEXITCODE) { throw ' ERROR - Required native outputs remain before the build clock.' }
        }
        if ($Generator -eq 'Ninja' -and (Test-Path "$buildDir\.ninja_log")) {
            # Ninja clean preserves historical log entries. Each run must have an isolated log.
            Remove-Item -LiteralPath "$buildDir\.ninja_log"
        }
        $argsList = @('--build', '.', '--config', 'Release')
        if ($Parallel -gt 0) { $argsList += @('--parallel', "$Parallel") }
        $nativeArguments = @($schedulerArguments)
        if ($Profile) { $nativeArguments += @('/clp:PerformanceSummary;Summary', '/v:minimal') }
        if ($BinaryLog) { $nativeArguments += "/bl:$runDir\build.binlog;ProjectImports=None" }
        if ($nativeArguments.Count) { $argsList += @('--') + $nativeArguments }
        $metadata['build_arguments'] = $argsList
        if ($MSBuildStudyPlan) {
            $build = Invoke-OwnedBuild $cmakeExe $argsList $buildDir $runDir
            & python "$PSScriptRoot\..\ci\msbuild-clserver-evidence.py" capture --source $Root --build $buildDir --run $runDir --plan $MSBuildStudyPlan
            if ($LASTEXITCODE) { throw ' ERROR - Timed source/output proof failed before direct install.' }
        } elseif ($MeasureCpu) {
            $accounting = Invoke-MeasuredBuild $cmakeExe $argsList $buildDir $runDir -Trace:$Trace
            $build = [math]::Round($accounting.WallSeconds, 4)
            $metadata['cpu_accounting'] = $accounting
            $metadata['accounting_source_sha256'] = (Get-FileHash "$PSScriptRoot\BuildAccounting.cs").Hash
            $metadata['measurement_helper_sha256'] = (Get-FileHash "$PSScriptRoot\measure_build.ps1").Hash
        } else {
            $build = Invoke-Logged $cmakeExe $argsList "$runDir\build.log"
        }
        if ($Generator -eq 'Ninja') { Copy-Item "$buildDir\.ninja_log" "$runDir\ninja_log.txt" }
        $installTarget = if ($Generator -eq 'MSBuild') { 'INSTALL' } else { 'install' }
        $installArguments = @('--build', '.', '--target', $installTarget, '--config', 'Release')
        if ($MSBuildStudyPlan) { $installArguments = @('--install', '.', '--config', 'Release') }
        elseif ($schedulerArguments.Count) { $installArguments += @('--') + $schedulerArguments }
        $install = Invoke-Logged $cmakeExe $installArguments "$runDir\install.log"
        $versionExe = Get-InstalledOpenCVFile $buildDir 'opencv_version.exe'
        Assert-NativeExecutable $versionExe.FullName $receipt.architecture
        $version = & $versionExe.FullName
        if ($LASTEXITCODE -ne 0 -or "$version".Trim() -ne $script:Config.opencv_tag) {
            throw " ERROR - Installed executable validation failed: $version"
        }
        $version | Set-Content "$runDir\opencv_version.txt"
        & $versionExe.FullName --verbose *> "$runDir\opencv_build_info.txt"
        if ($LASTEXITCODE -ne 0) { throw ' ERROR - opencv_version --verbose failed.' }
        Copy-Item "$buildDir\CMakeCache.txt", "$buildDir\configure.log" $runDir
        $format = [Globalization.CultureInfo]::InvariantCulture
        $elapsed = ([datetimeoffset]::Now - [datetimeoffset]$metadata.started_at).TotalSeconds
        @(
            "scenario_runtime,$($build.ToString('F2', $format))"
            "build_time,$($build.ToString('F2', $format))"
            "architecture,$($receipt.architecture.ToUpperInvariant())"
            "clean_time,$($clean.ToString('F2', $format))"
            "install_time,$($install.ToString('F2', $format))"
        ) | Set-Content "$runDir\opencv_build_results.csv"
        @('Timestamp,opencv_build_time', "$($elapsed.ToString('F2', $format)),$($build.ToString('F2', $format))") |
            Set-Content "$runDir\opencv_build_results.trace"
        $metadata['status'] = 'succeeded'
        $metadata['build_seconds'] = $build
        $metadata['clean_seconds'] = $clean
        $metadata['install_seconds'] = $install
        $metadata['validated_version'] = "$version".Trim()
        Write-Host "scenario_runtime = build_time = ${build}s; clean = ${clean}s; install = ${install}s"
        Write-Host "Results: $runDir"
    } finally { Pop-Location }
} catch {
    $metadata['status'] = 'failed'
    $metadata['error'] = $_.Exception.Message
    throw
} finally {
    if ($lock) { $lock.Dispose() }
    $metadata['finished_at'] = (Get-Date).ToString('o')
    $metadata | ConvertTo-Json -Depth 8 | Set-Content "$runDir\metadata.json"
}
