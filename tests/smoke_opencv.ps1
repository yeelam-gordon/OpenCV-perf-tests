#Requires -Version 7.0
param(
    [string]$Root = '',
    [ValidateSet('MSVC', 'Clang', 'MSVC2026', 'MSVC2026Latest')][string]$Toolchain = 'MSVC',
    [ValidateSet('MSBuild', 'Ninja')][string]$Generator = 'Ninja',
    [string]$BuildDirectory = ''
)
. "$PSScriptRoot\..\scripts\common.ps1"
$Root = Get-SourceRoot $Root
$Generator = Get-EffectiveGenerator $Generator $Toolchain ($PSBoundParameters.ContainsKey('Generator'))
$buildDir = Resolve-BuildDirectory $Root $Generator $Toolchain $BuildDirectory
$receipt = Get-Content "$buildDir\benchmark-setup.json" -Raw | ConvertFrom-Json
Assert-WindowsSDK $receipt $Toolchain
$cmake = Get-CMake $receipt.cmake (Get-ToolchainCMakeVersion $Toolchain)
Set-NativeToolchain $receipt.visual_studio $receipt.windows_sdk
$output = [IO.Path]::GetFullPath("$PSScriptRoot\..\.work\smoke_${Toolchain}_$Generator")
New-Item -ItemType Directory -Force $output | Out-Null
$package = Get-InstalledOpenCVFile $buildDir 'OpenCVConfig.cmake'
$argsList = @('--fresh', '-S', $PSScriptRoot, '-B', $output,
    '-DCMAKE_BUILD_TYPE=Release', "-DOpenCV_DIR=$($package.DirectoryName)",
    '-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreadedDLL')
if ($Generator -eq 'MSBuild') {
    $vsGenerator = if ($Toolchain -in @('MSVC2026', 'MSVC2026Latest')) { 'Visual Studio 18 2026' } else { 'Visual Studio 17 2022' }
    $platform = if ($receipt.architecture -eq 'arm64') { 'ARM64' } else { 'x64' }
    $argsList += @('-G', $vsGenerator, '-A', "$platform,version=$($receipt.windows_sdk.target_version)",
        "-DCMAKE_GENERATOR_INSTANCE=$($receipt.visual_studio.path)",
        "-DCMAKE_VS_GLOBALS=UCRTVersion=$($receipt.windows_sdk.target_version)")
} else {
    $ninja = (Get-Command ninja -CommandType Application | Select-Object -First 1).Source
    $argsList += @('-G', 'Ninja', "-DCMAKE_CXX_COMPILER=$($receipt.compiler)", "-DCMAKE_MAKE_PROGRAM=$ninja")
}
if ($Toolchain -eq 'Clang') {
    $env:PATH = "$($receipt.llvm.root)\bin;$env:PATH"
    $argsList += @("-DCMAKE_LINKER=$($receipt.llvm.linker)", '-DCMAKE_LINKER_TYPE=LLD',
        '-DCMAKE_CXX_FLAGS=-fno-delayed-template-parsing')
}
Invoke-Logged $cmake $argsList "$output\configure.log" | Out-Null
Invoke-Logged $cmake @('--build', $output, '--config', 'Release') "$output\build.log" | Out-Null
$versionExe = Get-InstalledOpenCVFile $buildDir 'opencv_version.exe'
$env:PATH = "$($versionExe.DirectoryName);$env:PATH"
$exe = if ($Generator -eq 'MSBuild') { "$output\Release\opencv_smoke.exe" } else { "$output\opencv_smoke.exe" }
Assert-NativeExecutable $exe $receipt.architecture
Invoke-Logged $exe @() "$output\smoke.log" | Out-Null
Get-Content "$output\smoke.log"
