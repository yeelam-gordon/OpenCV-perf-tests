#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path $PSScriptRoot
. (Join-Path $repo 'scripts\common.ps1')
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:HOSTING -ne 'github-hosted' -or
    (Get-NativeArchitecture) -ne 'arm64') {
    throw ' ERROR - This workload setup requires a GitHub-hosted native Arm64 job.'
}
$evidence = Join-Path $repo 'evidence'
New-Item -ItemType Directory -Path $evidence | Out-Null
$tools = Join-Path $env:RUNNER_TEMP 'opencv-qualified-tools'
if (Test-Path -LiteralPath $tools) { throw ' ERROR - Isolated tool directory already exists.' }
New-Item -ItemType Directory -Path $tools | Out-Null
$assets = @(
    @{ name = 'cmake.zip'; url = 'https://github.com/Kitware/CMake/releases/download/v4.4.4/cmake-4.4.4-windows-arm64.zip'
       hash = 'ed673bbc4eb7c1e59b0407fd52f1680fc0ae3229a46b9b7b3ea9133764f07f67'; destination = $tools },
    @{ name = 'ninja.zip'; url = 'https://github.com/ninja-build/ninja/releases/download/v1.13.2/ninja-winarm64.zip'
       hash = 'e52f0bdef9dfb1003229dbd6508a508c4073fd017247002adc66e5e806cb0391'; destination = (Join-Path $tools 'ninja') }
)
foreach ($asset in $assets) {
    $path = Join-Path $tools $asset.name
    Invoke-WebRequest $asset.url -OutFile $path
    if ((Get-FileHash -LiteralPath $path).Hash -ine $asset.hash) { throw ' ERROR - Official tool archive digest mismatch.' }
    Expand-Archive -LiteralPath $path -DestinationPath $asset.destination
}
$cmake = Join-Path $tools 'cmake-4.4.4-windows-arm64\bin\cmake.exe'
$ninja = Join-Path $tools 'ninja\ninja.exe'
Assert-NativeExecutable $cmake 'arm64'
Assert-NativeExecutable $ninja 'arm64'
$vs = Get-VisualStudio 18
$compiler = Join-Path $vs.tools 'bin\Hostarm64\arm64\cl.exe'
$msbuild = Join-Path $vs.path 'MSBuild\Current\Bin\arm64\MSBuild.exe'
Assert-NativeExecutable $compiler 'arm64'
Assert-NativeExecutable $msbuild 'arm64'
$python = (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
$pythonVersion = & $python -c 'import json,sys; print(json.dumps({"executable":sys.executable,"version":sys.version}))'
if ($LASTEXITCODE) { throw ' ERROR - Python evidence-tool readiness failed before any build.' }
$engine = & $msbuild -nologo -version
if ($LASTEXITCODE) { throw ' ERROR - Native MSBuild version lookup failed.' }
$profile = [ordered]@{
    profile_kind = 'Observed installed native hosted tools; not a historical/latest-release claim.'
    visual_studio_build = $vs.version
    msvc_toolset = $vs.toolset
    compiler_version = (Get-Item -LiteralPath $compiler).VersionInfo.FileVersion
    msbuild_version = "$engine".Trim()
    cmake_version = '4.4.4'
}
$profile | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $repo 'toolchains\vs2026.json')
$profile | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $evidence 'observed-tools.json')
$env:PATH = "$(Split-Path $ninja);$env:PATH"
$source = Join-Path $env:RUNNER_TEMP 'opencv-qualified-source'
if (Test-Path -LiteralPath $source) { throw ' ERROR - Isolated source directory already exists.' }
foreach ($generator in @('MSBuild', 'Ninja')) {
    $options = if ($generator -eq 'Ninja') { @{ InitialCache = (Join-Path $PSScriptRoot 'ninja-dispatch-targets.cmake') } } else { @{} }
    & (Join-Path $repo 'scripts\setup.ps1') -Root $source -Generator $generator `
        -Toolchain MSVC2026 -CMake $cmake @options
    $build = Get-BuildDirectory $source $generator 'MSVC2026'
    if (-not (Test-Path -LiteralPath (Join-Path $build 'benchmark-setup.json'))) { throw ' ERROR - Native setup receipt missing.' }
}
$msbuildDir = Get-BuildDirectory $source 'MSBuild' 'MSVC2026'
$ninjaDir = Get-BuildDirectory $source 'Ninja' 'MSVC2026'
foreach ($name in @('cvconfig.h', 'opencv2\opencv_modules.hpp')) {
    if ((Get-FileHash -LiteralPath (Join-Path $msbuildDir $name)).Hash -ne
        (Get-FileHash -LiteralPath (Join-Path $ninjaDir $name)).Hash) {
        throw ' ERROR - Generator feature headers differ before timing.'
    }
}
@{
    cpu = @(Get-CimInstance Win32_Processor | Select-Object Name, NumberOfCores, NumberOfLogicalProcessors)
    memory_gib = [math]::Round((Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory / 1GB, 2)
    os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture
    image_os = $env:ImageOS; image_version = $env:ImageVersion
    filesystem = ([IO.DriveInfo]::new([IO.Path]::GetPathRoot($source))).DriveFormat
    source = $source; ninja = $ninja; ninja_sha256 = (Get-FileHash -LiteralPath $ninja).Hash
    python = ($pythonVersion | ConvertFrom-Json)
    score = 'Build invocation only; provisioning/configure/clean/install/version/smoke excluded.'
} | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence 'runner-environment.json')
