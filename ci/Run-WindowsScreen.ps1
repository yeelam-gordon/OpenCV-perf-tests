#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path $PSScriptRoot
. (Join-Path $repo 'scripts\common.ps1')
$root = $env:OPENCV_CI_ROOT
if (-not $root) { throw ' ERROR - Run storage preparation first.' }
$evidence = Join-Path $repo 'evidence'
$source = Join-Path $root 'opencv'
$tools = Join-Path $root 'tools'
New-Item -ItemType Directory -Path $tools | Out-Null
$archive = Join-Path $tools 'cmake.zip'
Invoke-WebRequest 'https://github.com/Kitware/CMake/releases/download/v4.4.4/cmake-4.4.4-windows-arm64.zip' -OutFile $archive
if ((Get-FileHash -LiteralPath $archive).Hash -ne 'ed673bbc4eb7c1e59b0407fd52f1680fc0ae3229a46b9b7b3ea9133764f07f67') {
    throw ' ERROR - Official pinned CMake archive checksum mismatch.'
}
Expand-Archive -LiteralPath $archive -DestinationPath $tools
$cmake = Join-Path $tools 'cmake-4.4.4-windows-arm64\bin\cmake.exe'
Assert-NativeExecutable $cmake 'arm64'
$vs = Get-VisualStudio 18
$compiler = Join-Path $vs.tools 'bin\Hostarm64\arm64\cl.exe'
Assert-NativeExecutable $compiler 'arm64'
$msbuild = Join-Path $vs.path 'MSBuild\Current\Bin\arm64\MSBuild.exe'
Assert-NativeExecutable $msbuild 'arm64'
$msbuildVersion = & $msbuild -nologo -version
if ($LASTEXITCODE) { throw ' ERROR - Native MSBuild version lookup failed.' }
$profile = [ordered]@{
    profile_kind = 'Observed installed CI tools, pinned for this job; not a historical/latest-release claim.'
    visual_studio_build = $vs.version
    msvc_toolset = $vs.toolset
    compiler_version = (Get-Item -LiteralPath $compiler).VersionInfo.FileVersion
    msbuild_version = "$msbuildVersion".Trim()
    cmake_version = '4.4.4'
}
$profile | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $repo 'toolchains\vs2026.json')
$profile | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'observed-vs2026.json')
$build = Get-BuildDirectory $source 'MSBuild' 'MSVC2026'
try {
    & (Join-Path $repo 'scripts\setup.ps1') -Root $source -Generator MSBuild -Toolchain MSVC2026 -CMake $cmake
} finally {
    foreach ($name in @('configure.log', 'CMakeCache.txt', 'msbuild-version.log', 'sdk-properties.json')) {
        $file = Join-Path $build $name
        if (Test-Path -LiteralPath $file) { Copy-Item -LiteralPath $file -Destination $evidence }
    }
}
Copy-Item -LiteralPath (Join-Path $build 'benchmark-setup.json') -Destination $evidence
$order = @('baseline', 'shared', 'shared', 'baseline')
$study = [ordered]@{
    status = 'running'
    order = $order
    warmups = 0
    caveat = 'Screen only: two observations per variant, no excluded full-build warmup; ABBA ordering, 30-second rests, uncontrolled hosted VM.'
    jobs = [Environment]::ProcessorCount
    runner = $env:RUNNER_NAME
    image_os = $env:ImageOS
    image_version = $env:ImageVersion
    workflow_commit = $env:GITHUB_SHA
    run_id = $env:GITHUB_RUN_ID
    runs = @()
}
$frozen = @{}
$inputs = @(Get-ChildItem -LiteralPath $build -Recurse -File -Include *.sln,*.vcxproj,*.props,*.targets) +
    @(Get-Item -LiteralPath (Join-Path $build 'CMakeCache.txt'), (Join-Path $build 'benchmark-setup.json'))
foreach ($file in $inputs) { $frozen[$file.FullName] = (Get-FileHash -LiteralPath $file.FullName).Hash }
$study['frozen_sha256'] = $frozen
$counts = @{ baseline = 0; shared = 0 }
$shell = (Get-Process -Id $PID).Path
try {
    foreach ($variant in $order) {
        foreach ($path in $frozen.Keys) {
            if ((Get-FileHash -LiteralPath $path).Hash -ne $frozen[$path]) { throw " ERROR - Input changed: $path" }
        }
        $counts[$variant]++
        $label = "$($variant)_$($counts[$variant])"
        $options = @()
        if ($variant -eq 'shared') {
            $options = @('-MSBuildScheduler', 'MultiToolTask', '-CompilerJobs', "$($study.jobs)",
                '-SharedCompilerLimit', '-Parallel', "$($study.jobs)")
        }
        Start-Sleep -Seconds 30
        & $shell -NoProfile -File (Join-Path $repo 'scripts\run.ps1') -Root $source `
            -ResultsDir $evidence -Generator MSBuild -Toolchain MSVC2026 -Label $label @options
        if ($LASTEXITCODE) { throw " ERROR - Build failed: $label" }
        $runs = @(Get-ChildItem -LiteralPath $evidence -Directory | Where-Object Name -Like "*_$label")
        if ($runs.Count -ne 1) { throw " ERROR - Expected one run receipt: $label" }
        $run = $runs[0]
        & python (Join-Path $PSScriptRoot 'windows-evidence.py') $build $run.FullName
        if ($LASTEXITCODE) { throw " ERROR - Output/command evidence failed: $label" }
        $receipt = Get-Content -LiteralPath (Join-Path $run.FullName 'metadata.json') -Raw | ConvertFrom-Json
        if ($receipt.status -ne 'succeeded') { throw " ERROR - Incomplete run: $label" }
        $study.runs += @{ label = $label; variant = $variant; directory = $run.Name; seconds = $receipt.build_seconds }
        $study | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'study.json')
    }
    & (Join-Path $repo 'tests\smoke_opencv.ps1') -Root $source -Generator MSBuild -Toolchain MSVC2026
    $smokeDir = Join-Path $repo '.work\smoke_MSVC2026_MSBuild'
    foreach ($run in $study.runs) {
        $directory = Join-Path $evidence $run.directory
        Copy-Item -LiteralPath (Join-Path $directory 'runtime-binaries\opencv_world4100.dll') `
            -Destination (Join-Path $smokeDir 'Release\opencv_world4100.dll') -Force
        Invoke-Logged (Join-Path $smokeDir 'Release\opencv_smoke.exe') @() `
            (Join-Path $directory 'smoke.log') | Out-Null
    }
    $commands = @($study.runs | ForEach-Object {
        (Get-FileHash -LiteralPath (Join-Path $evidence "$($_.directory)\commands.json")).Hash
    } | Select-Object -Unique)
    if ($commands.Count -ne 1) { throw ' ERROR - Effective compile commands differ between schedules.' }
    foreach ($path in $frozen.Keys) {
        if ((Get-FileHash -LiteralPath $path).Hash -ne $frozen[$path]) { throw " ERROR - Input changed: $path" }
    }
    $study['command_manifests_identical'] = $true
    $study.status = 'succeeded'
} catch {
    $study.status = 'failed'
    $study['error'] = $_.Exception.Message
    throw
} finally {
    $study | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath (Join-Path $evidence 'study.json')
    Get-ChildItem -LiteralPath $evidence -Directory | ForEach-Object {
        $binaries = Join-Path $_.FullName 'runtime-binaries'
        $dll = Join-Path $binaries 'opencv_world4100.dll'
        if (Test-Path -LiteralPath $dll) {
            Remove-Item -LiteralPath $dll
        }
    }
}
