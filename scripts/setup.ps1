#Requires -Version 7.0
param(
    [string]$Root = '',
    [ValidateSet('MSBuild', 'Ninja')][string]$Generator = 'MSBuild',
    [ValidateSet('MSVC', 'Clang', 'MSVC2026', 'MSVC2026Latest')][string]$Toolchain = 'MSVC',
    [string]$LLVMRoot = '',
    [string]$InitialCache = '',
    [string]$CMake = '',
    [string]$BuildDirectory = ''
)
. "$PSScriptRoot\common.ps1"
$Root = Get-SourceRoot $Root
$Generator = Get-EffectiveGenerator $Generator $Toolchain ($PSBoundParameters.ContainsKey('Generator'))
if ($LLVMRoot -and $Toolchain -ne 'Clang') { throw ' ERROR - LLVMRoot is only valid with -Toolchain Clang.' }
$cmakeVersion = Get-ToolchainCMakeVersion $Toolchain
$cmakeExe = Get-CMake $CMake $cmakeVersion
$vsMajor = if ($Toolchain -in @('MSVC2026', 'MSVC2026Latest')) { 18 } else { 17 }
$vs = Get-VisualStudio $vsMajor
if ($vsMajor -eq 18) {
    $spec = Get-Content "$PSScriptRoot\..\toolchains\vs2026.json" -Raw | ConvertFrom-Json
    if ($vs.version -ne $spec.visual_studio_build) {
        throw " ERROR - Expected VS $($spec.visual_studio_build), found $($vs.version). Review release pins before using another release."
    }
    if ($vs.toolset -ne $spec.msvc_toolset) { throw ' ERROR - VS 2026 default toolset differs from the release pin.' }
}
$arch = Get-NativeArchitecture
Assert-WindowsSDKRestart
$sdk = Get-WindowsSDK $Toolchain
if (-not (Test-Path $Root)) {
    & git clone --depth 1 --branch $script:Config.opencv_tag https://github.com/opencv/opencv.git $Root
    if ($LASTEXITCODE -ne 0) { throw ' ERROR - OpenCV clone failed.' }
}
Assert-Source $Root
$buildDir = Resolve-BuildDirectory $Root $Generator $Toolchain $BuildDirectory
$llvm = if ($Toolchain -eq 'Clang') { Get-ClangToolchain $LLVMRoot } else { $null }
New-Item -ItemType Directory -Force $buildDir | Out-Null
$argsList = @('--fresh', '-S', $Root, '-B', $buildDir) + @($script:Config.cmake_flags)
$initialCacheReceipt = $null
if ($InitialCache) {
    $InitialCache = (Get-Item -LiteralPath $InitialCache -ErrorAction Stop).FullName
    $argsList += @('-C', $InitialCache)
    $initialCacheReceipt = @{ path = $InitialCache; sha256 = (Get-FileHash -LiteralPath $InitialCache).Hash }
}
if ($Generator -eq 'MSBuild') {
    $vsGenerator = if ($vsMajor -eq 18) { 'Visual Studio 18 2026' } else { 'Visual Studio 17 2022' }
    $platform = if ($arch -eq 'arm64') { 'ARM64' } else { 'x64' }
    $argsList += @('-G', $vsGenerator, '-A', "$platform,version=$($sdk.target_version)",
        "-DCMAKE_GENERATOR_INSTANCE=$($vs.path)", "-DCMAKE_VS_GLOBALS=UCRTVersion=$($sdk.target_version)")
} else {
    Set-NativeToolchain $vs $sdk
    $ninja = (Get-Command ninja -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $argsList += @('-G', 'Ninja', "-DCMAKE_MAKE_PROGRAM=$ninja")
    if ($llvm) {
        $env:PATH = "$($llvm.root)\bin;$env:PATH"
        # Standard lookup avoids cv::float32_t shadowing Clang's NEON typedef inside delayed templates.
        $argsList += @("-DCMAKE_C_COMPILER=$($llvm.c)", "-DCMAKE_CXX_COMPILER=$($llvm.cxx)",
            "-DCMAKE_LINKER=$($llvm.linker)", '-DCMAKE_LINKER_TYPE=LLD',
            "-DCMAKE_AR=$($llvm.ar)", "-DCMAKE_RANLIB=$($llvm.ranlib)",
            '-DCMAKE_CXX_FLAGS=-fno-delayed-template-parsing')
    } else {
        $argsList += @('-DCMAKE_C_COMPILER=cl', '-DCMAKE_CXX_COMPILER=cl')
    }
}
$configureTime = Invoke-Logged $cmakeExe $argsList "$buildDir\configure.log"
if ($Generator -eq 'MSBuild') {
    $projects = @(Get-ChildItem $buildDir -Recurse -Filter *.vcxproj -File |
        Where-Object { -not $_.FullName.StartsWith("$buildDir\CMakeFiles\", [StringComparison]::OrdinalIgnoreCase) })
    if (-not $projects.Count) { throw ' ERROR - No generated MSBuild projects found.' }
    foreach ($project in $projects) {
        $text = Get-Content $project.FullName -Raw
        if ($text -notmatch "<WindowsTargetPlatformVersion>$([regex]::Escape($sdk.target_version))</WindowsTargetPlatformVersion>" -or
            $text -notmatch "<UCRTVersion>$([regex]::Escape($sdk.target_version))</UCRTVersion>") {
            throw " ERROR - Generated project does not pin the expected SDK/UCRT: $($project.FullName)"
        }
    }
}
$compilerFile = "$buildDir\CMakeFiles\$cmakeVersion\CMakeCXXCompiler.cmake"
$compilerInfo = Get-Content $compilerFile -Raw
if ($compilerInfo -notmatch 'set\(CMAKE_CXX_COMPILER "([^"]+)"\)') { throw ' ERROR - Cannot determine configured C++ compiler.' }
$compiler = $Matches[1]
$compilerFacts = @{}
foreach ($key in @('ID', 'VERSION', 'FRONTEND_VARIANT')) {
    if ($compilerInfo -notmatch ('set\(CMAKE_CXX_COMPILER_' + $key + ' "([^"]*)"\)')) {
        throw " ERROR - Cannot read CMake compiler $key."
    }
    $compilerFacts[$key] = $Matches[1]
}
if ($llvm -and ($compilerFacts.ID -ne 'Clang' -or $compilerFacts.FRONTEND_VARIANT -ne 'GNU')) {
    throw ' ERROR - Expected Clang with the GNU-style frontend.'
}
if ($vsMajor -eq 18 -and $compilerFacts.VERSION -ne $spec.compiler_version) {
    throw ' ERROR - VS 2026 compiler version differs from the release pin.'
}
if ($Toolchain -ne 'Clang' -and
    [IO.Path]::GetFullPath($compiler) -ne [IO.Path]::GetFullPath("$($vs.tools)\bin\Host$arch\$arch\cl.exe")) {
    throw " ERROR - Expected native MSVC compiler; got $compiler"
}
if ($llvm -and [IO.Path]::GetFullPath($compiler) -ne [IO.Path]::GetFullPath($llvm.cxx)) {
    throw " ERROR - CMake selected a different Clang executable: $compiler"
}
Assert-NativeExecutable $compiler $arch
$compilerHash = (Get-FileHash $compiler -Algorithm SHA256).Hash
$buildEngine = $null
if ($Generator -eq 'MSBuild') {
    $hostDir = if ($arch -eq 'arm64') { 'arm64' } else { 'amd64' }
    $msbuild = "$($vs.path)\MSBuild\Current\Bin\$hostDir\MSBuild.exe"
    Assert-NativeExecutable $msbuild $arch
    $engineVersion = & $msbuild -nologo -version
    if ($LASTEXITCODE -ne 0) { throw ' ERROR - MSBuild version lookup failed.' }
    if ($vsMajor -eq 18 -and "$engineVersion".Trim() -ne $spec.msbuild_version) {
        throw ' ERROR - MSBuild version differs from the VS 2026 release pin.'
    }
    Invoke-Logged $cmakeExe @('--build', $buildDir, '--config', 'Release', '--', '-nologo', '-version') `
        "$buildDir\msbuild-version.log" | Out-Null
    if ((Get-Content "$buildDir\msbuild-version.log" -Raw).Trim() -ne "$engineVersion".Trim()) {
        throw ' ERROR - CMake invoked an unexpected MSBuild version.'
    }
    $linker = "$($vs.tools)\bin\Host$arch\$arch\link.exe"
    Assert-NativeExecutable $linker $arch
    $buildEngine = @{
        path = $msbuild
        version = "$engineVersion".Trim()
        sha256 = (Get-FileHash $msbuild).Hash
        linker = $linker
        linker_sha256 = (Get-FileHash $linker).Hash
    }
    Invoke-Logged $msbuild @("$buildDir\ALL_BUILD.vcxproj", '-nologo', '-p:Configuration=Release',
        "-p:Platform=$platform",
        '-getProperty:WindowsTargetPlatformVersion,UCRTVersion,WindowsSDK_IncludePath,UniversalCRT_IncludePath,LibraryPath') `
        "$buildDir\sdk-properties.json" | Out-Null
    $properties = (Get-Content "$buildDir\sdk-properties.json" -Raw | ConvertFrom-Json).Properties
    if ($properties.WindowsTargetPlatformVersion -ne $sdk.target_version -or
        $properties.UCRTVersion -ne $sdk.target_version) {
        throw ' ERROR - Evaluated MSBuild SDK/UCRT versions differ from the requested profile.'
    }
    foreach ($name in @('WindowsSDK_IncludePath', 'UniversalCRT_IncludePath', 'LibraryPath')) {
        $pattern = '(?i)' + [regex]::Escape($sdk.root.TrimEnd('\')) + '\\(?:Include|Lib)\\(10\.0\.\d+\.0)'
        $versions = [regex]::Matches($properties.$name, $pattern)
        if (-not $versions.Count -or @($versions | Where-Object { $_.Groups[1].Value -ne $sdk.target_version }).Count) {
            throw " ERROR - Evaluated MSBuild $name selects a different Windows SDK."
        }
    }
    $sdk | Add-Member -NotePropertyName evaluated_properties -NotePropertyValue $properties
}
$receipt = [ordered]@{
    hobl_commit = $script:Config.hobl_commit
    opencv_commit = $script:Config.opencv_commit
    cmake_version = $cmakeVersion
    cmake = $cmakeExe
    cmake_sha256 = (Get-FileHash $cmakeExe).Hash
    build_engine = $buildEngine
    generator = $Generator
    toolchain = $Toolchain
    llvm = $llvm
    architecture = $arch
    configure_seconds = $configureTime
    configure_arguments = $argsList
    compiler = $compiler
    compiler_id = $compilerFacts.ID
    compiler_version = $compilerFacts.VERSION
    compiler_frontend = $compilerFacts.FRONTEND_VARIANT
    compiler_sha256 = $compilerHash
    visual_studio = $vs
    windows_sdk = $sdk
    config_sha256 = (Get-FileHash "$PSScriptRoot\..\benchmark.json").Hash
    initial_cache = $initialCacheReceipt
}
$receipt | ConvertTo-Json -Depth 6 | Set-Content "$buildDir\benchmark-setup.json"
Write-Host "Configured $buildDir in ${configureTime}s (excluded from benchmark)."
