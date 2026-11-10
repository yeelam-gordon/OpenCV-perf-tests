# Copyright (c) Microsoft Corporation. HOBL configuration adapted under the MIT license.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$script:Config = Get-Content (Join-Path $PSScriptRoot '..\benchmark.json') -Raw | ConvertFrom-Json

function Get-SourceRoot([string]$Root) {
    if (-not $Root) { $Root = Join-Path (Split-Path -Qualifier $PSScriptRoot) 'opencv' }
    return [IO.Path]::GetFullPath($Root, (Get-Location).ProviderPath)
}

function Get-NativeArchitecture {
    $arch = [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString().ToLowerInvariant()
    if ($arch -notin @('arm64', 'x64')) { throw " ERROR - Unsupported architecture: $arch" }
    if ([Runtime.InteropServices.RuntimeInformation]::ProcessArchitecture.ToString().ToLowerInvariant() -ne $arch) {
        throw ' ERROR - Run native PowerShell 7 for this OS, not an emulated shell.'
    }
    return $arch
}

function Assert-NoPendingToolchainRestart([string]$Receipt = "$PSScriptRoot\..\.tools\vs2026-installation.json") {
    if (-not (Test-Path -LiteralPath $Receipt)) { return }
    $installation = Get-Content $Receipt -Raw | ConvertFrom-Json
    if ($installation.exit_code -eq 3010) {
        $boot = (Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime().ToString('o')
        if ([datetimeoffset]$installation.boot_time -eq [datetimeoffset]$boot) {
            if ($installation.PSObject.Properties.Name -contains 'restart_assessment' -and
                $installation.restart_assessment.kind -eq 'verified-soft-reboot') {
                $assessment = $installation.restart_assessment
                $vs = Get-VisualStudio 18
                if (-not $vs.complete -or $vs.reboot_required -or $vs.version -ne $assessment.visual_studio_build) {
                    throw ' ERROR - Visual Studio no longer matches the verified soft-reboot assessment.'
                }
                if (-not $assessment.runtime_files.Count) { throw ' ERROR - Soft-reboot assessment has no runtime evidence.' }
                foreach ($runtime in $assessment.runtime_files) {
                    if ((Get-FileHash -LiteralPath $runtime.path).Hash -ne $runtime.sha256) {
                        throw ' ERROR - Runtime changed after soft-reboot verification; review installation before benchmarking.'
                    }
                }
                Write-Warning 'Measuring before the recommended restart: verified soft-reboot assessment and runtime hashes match.'
                return
            }
            throw ' ERROR - Restart Windows to finish VS 2026 installation before benchmarking.'
        }
    }
}

function Get-ToolchainCMakeVersion([string]$Toolchain) {
    if ($Toolchain -in @('MSVC2026', 'MSVC2026Latest')) {
        return (Get-Content "$PSScriptRoot\..\toolchains\vs2026.json" -Raw | ConvertFrom-Json).cmake_version
    }
    return $script:Config.cmake_version
}

function Get-CMake([string]$CMake, [string]$Version = $script:Config.cmake_version) {
    if (-not $CMake) {
        $portable = Join-Path $PSScriptRoot "..\.tools\cmake-$Version-windows-$(Get-NativeArchitecture)\bin\cmake.exe"
        $CMake = if (Test-Path $portable) { $portable } else { 'cmake' }
    }
    $exe = (Get-Command $CMake -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
    $versionOutput = & $exe --version
    if ($LASTEXITCODE -ne 0 -or $versionOutput[0] -ne "cmake version $Version") {
        throw " ERROR - CMake $Version required; found $($versionOutput[0]). Supply -CMake or install the pinned portable release."
    }
    Write-Host "CMake: $exe"
    return $exe
}

function Get-VisualStudio([ValidateSet(17, 18)][int]$MajorVersion = 17) {
    $command = Get-Command vswhere.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    $vswhere = if ($command) { $command.Source } else {
        Join-Path ${env:ProgramFiles(x86)} 'Microsoft Visual Studio\Installer\vswhere.exe'
    }
    if (-not (Test-Path $vswhere)) { throw ' ERROR - vswhere.exe not found; install Visual Studio C++ tools.' }
    $range = "[$MajorVersion.0,$($MajorVersion + 1).0)"
    $instances = & $vswhere -version $range -products '*' -format json | ConvertFrom-Json
    if ($LASTEXITCODE -ne 0) { throw ' ERROR - vswhere failed.' }
    $arch = Get-NativeArchitecture
    foreach ($instance in ($instances | Sort-Object { [version]$_.installationVersion } -Descending)) {
        $versionFile = Join-Path $instance.installationPath 'VC\Auxiliary\Build\Microsoft.VCToolsVersion.default.txt'
        if (-not (Test-Path $versionFile)) { continue }
        $toolset = (Get-Content $versionFile -Raw).Trim()
        $tools = Join-Path $instance.installationPath "VC\Tools\MSVC\$toolset"
        if (Test-Path "$tools\bin\Host$arch\$arch\cl.exe") {
            Write-Host "Visual Studio: $($instance.installationPath); MSVC: $toolset"
            return [pscustomobject]@{
                path = $instance.installationPath
                version = $instance.installationVersion
                tools = $tools
                toolset = $toolset
                complete = [bool]$instance.isComplete
                reboot_required = [bool]$instance.isRebootRequired
            }
        }
    }
    throw " ERROR - Visual Studio $MajorVersion with native $arch C++ tools was not found."
}

function Assert-WindowsSDKRestart([string]$Receipt = "$PSScriptRoot\..\.tools\windows-sdk-installation.json") {
    if (-not (Test-Path -LiteralPath $Receipt)) { return }
    $installation = Get-Content $Receipt -Raw | ConvertFrom-Json
    if ($installation.exit_code -notin @(0, 3010)) {
        throw " ERROR - Windows SDK installation failed with code $($installation.exit_code); review its log."
    }
    if ($installation.exit_code -eq 3010 -and
        [datetimeoffset]$installation.boot_time -eq
        [datetimeoffset](Get-CimInstance Win32_OperatingSystem).LastBootUpTime.ToUniversalTime()) {
        throw ' ERROR - Restart Windows to finish Windows SDK installation before benchmarking.'
    }
}

function Get-WindowsSDK([string]$Toolchain = 'MSVC') {
    $arch = Get-NativeArchitecture
    $key = [Microsoft.Win32.RegistryKey]::OpenBaseKey(
        [Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry32)
    try {
        $roots = $key.OpenSubKey('SOFTWARE\Microsoft\Windows Kits\Installed Roots')
        if (-not $roots) { throw ' ERROR - Windows SDK is not registered.' }
        try { $sdk = $roots.GetValue('KitsRoot10') } finally { $roots.Dispose() }
    } finally { $key.Dispose() }
    if (-not $sdk -or -not (Test-Path "$sdk\Include")) { throw ' ERROR - Windows SDK includes not found.' }
    $spec = Get-Content "$PSScriptRoot\..\toolchains\windows-sdk.json" -Raw | ConvertFrom-Json
    $sdkVersion = if ($Toolchain -eq 'MSVC2026Latest') { $spec.latest_target_version } else { $spec.baseline_target_version }
    $files = @(
        "bin\$sdkVersion\$arch\rc.exe", "bin\$sdkVersion\$arch\mt.exe",
        "Include\$sdkVersion\um\Windows.h", "Include\$sdkVersion\shared\sdkddkver.h",
        "Include\$sdkVersion\ucrt\stdio.h", "Lib\$sdkVersion\um\$arch\kernel32.lib",
        "Lib\$sdkVersion\ucrt\$arch\ucrt.lib"
    )
    $hashes = [ordered]@{}
    foreach ($file in $files) {
        $path = Join-Path $sdk $file
        if (-not (Test-Path $path)) { throw " ERROR - Required Windows SDK file missing: $path" }
        $hashes[$path] = (Get-FileHash $path).Hash
    }
    $rc = "$sdk\bin\$sdkVersion\$arch\rc.exe"
    $mt = "$sdk\bin\$sdkVersion\$arch\mt.exe"
    Assert-NativeExecutable $rc $arch
    Assert-NativeExecutable $mt $arch
    $releaseVersion = ((Get-Item $rc).VersionInfo.FileVersion -split ' ')[0]
    $manifestVersion = ((Get-Item $mt).VersionInfo.FileVersion -split ' ')[0]
    if ($Toolchain -eq 'MSVC2026Latest' -and
        ($releaseVersion -ne $spec.latest_release_version -or $manifestVersion -ne $spec.latest_release_version)) {
        throw ' ERROR - Latest Windows SDK tools differ from the release pin.'
    }
    return [pscustomobject]@{
        root = $sdk
        target_version = $sdkVersion
        release_version = $releaseVersion
        manifest_tool_version = $manifestVersion
        files_sha256 = [pscustomobject]$hashes
    }
}

function Assert-WindowsSDK($Receipt, [string]$Toolchain) {
    if ($null -eq $Receipt.PSObject.Properties['windows_sdk']) {
        throw ' ERROR - Setup receipt has no explicit Windows SDK selection; rerun setup.'
    }
    $current = Get-WindowsSDK $Toolchain
    if ($Receipt.windows_sdk.target_version -ne $current.target_version -or
        $Receipt.windows_sdk.release_version -ne $current.release_version) {
        throw ' ERROR - Windows SDK selection changed since setup; rerun setup.'
    }
    foreach ($file in $current.files_sha256.PSObject.Properties) {
        if ($Receipt.windows_sdk.files_sha256.PSObject.Properties.Name -notcontains $file.Name -or
            $Receipt.windows_sdk.files_sha256.($file.Name) -ne $file.Value) {
            throw ' ERROR - Windows SDK file changed since setup; rerun setup.'
        }
    }
}

function Set-NativeToolchain($VisualStudio, $WindowsSDK = (Get-WindowsSDK)) {
    $arch = Get-NativeArchitecture
    $sdk = $WindowsSDK.root
    $sdkVersion = $WindowsSDK.target_version
    $tools = $VisualStudio.tools
    $env:PATH = "$tools\bin\Host$arch\$arch;$sdk\bin\$sdkVersion\$arch;$env:PATH"
    $env:INCLUDE = "$tools\include;$sdk\Include\$sdkVersion\ucrt;$sdk\Include\$sdkVersion\um;$sdk\Include\$sdkVersion\shared"
    $env:LIB = "$tools\lib\$arch;$sdk\Lib\$sdkVersion\ucrt\$arch;$sdk\Lib\$sdkVersion\um\$arch"
    Write-Host "Windows SDK: $sdk ($sdkVersion); compiler host/target: $arch/$arch"
}

function Get-EffectiveGenerator([string]$Generator, [string]$Toolchain, [bool]$ExplicitGenerator) {
    if ($Toolchain -in @('MSVC2026', 'MSVC2026Latest')) {
        return $Generator
    }
    if ($Toolchain -eq 'Clang') {
        if ($ExplicitGenerator -and $Generator -ne 'Ninja') {
            throw ' ERROR - The Clang experiment requires the Ninja generator.'
        }
        return 'Ninja'
    }
    return $Generator
}

function Assert-NativeExecutable([string]$Path, [string]$Architecture) {
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw " ERROR - Executable not found: $Path" }
    $reader = [IO.BinaryReader]::new([IO.File]::OpenRead($Path))
    try {
        if ($reader.BaseStream.Length -lt 64 -or $reader.ReadUInt16() -ne 0x5A4D) {
            throw " ERROR - Not a PE executable: $Path"
        }
        $reader.BaseStream.Position = 0x3C
        $offset = $reader.ReadInt32()
        if ($offset -lt 64 -or $offset + 6 -gt $reader.BaseStream.Length) { throw " ERROR - Invalid PE header: $Path" }
        $reader.BaseStream.Position = $offset
        if ($reader.ReadUInt32() -ne 0x4550) { throw " ERROR - Invalid PE signature: $Path" }
        $machine = $reader.ReadUInt16()
        $expected = switch ($Architecture) {
            'arm64' { 0xAA64 }
            'x64' { 0x8664 }
            default { throw " ERROR - Unsupported PE architecture: $Architecture" }
        }
        if ($machine -ne $expected) { throw " ERROR - $Path is not native $Architecture (PE machine $machine)." }
    } finally { $reader.Dispose() }
}

function Get-ClangToolchain([string]$LLVMRoot) {
    $spec = Get-Content "$PSScriptRoot\..\toolchains\clang-arm64.json" -Raw | ConvertFrom-Json
    $usePinned = -not $LLVMRoot
    $arch = Get-NativeArchitecture
    if ($usePinned) {
        if ($arch -ne $spec.architecture) { throw ' ERROR - Supply -LLVMRoot for a native compiler on this architecture.' }
        $LLVMRoot = Join-Path $PSScriptRoot "..\.tools\$($spec.directory)"
    }
    $LLVMRoot = [IO.Path]::GetFullPath($LLVMRoot, (Get-Location).ProviderPath)
    $tools = [ordered]@{
        root = $LLVMRoot
        c = "$LLVMRoot\bin\clang.exe"
        cxx = "$LLVMRoot\bin\clang++.exe"
        linker = "$LLVMRoot\bin\lld-link.exe"
        ar = "$LLVMRoot\bin\llvm-ar.exe"
        ranlib = "$LLVMRoot\bin\llvm-ranlib.exe"
    }
    foreach ($name in @('c', 'cxx', 'linker', 'ar', 'ranlib')) { Assert-NativeExecutable $tools[$name] $arch }
    $version = & $tools.cxx --version
    if ($LASTEXITCODE -ne 0) { throw ' ERROR - Clang version check failed.' }
    $text = $version -join "`n"
    if ($text -notmatch 'clang version ([^\s]+)') { throw ' ERROR - Cannot determine Clang version.' }
    $tools['version'] = $Matches[1]
    if ($usePinned -and $tools.version -ne $spec.version) { throw ' ERROR - Portable Clang does not match the pinned release.' }
    $triple = if ($arch -eq 'arm64') { 'aarch64' } else { 'x86_64' }
    if ($text -notmatch "(?m)^Target: ($triple-[^\s]*windows-msvc[^\s]*)") {
        throw ' ERROR - Clang must target the native Windows MSVC ABI.'
    }
    $tools['target'] = $Matches[1]
    $tools['version_output'] = $text
    $tools['c_sha256'] = (Get-FileHash $tools.c).Hash
    $tools['cxx_sha256'] = (Get-FileHash $tools.cxx).Hash
    $tools['linker_sha256'] = (Get-FileHash $tools.linker).Hash
    $tools['ar_sha256'] = (Get-FileHash $tools.ar).Hash
    $tools['ranlib_sha256'] = (Get-FileHash $tools.ranlib).Hash
    Write-Host "Clang $($tools.version): $LLVMRoot; target $($tools.target)"
    return [pscustomobject]$tools
}

function Get-BuildDirectory([string]$Root, [string]$Generator, [string]$Toolchain = 'MSVC') {
    if ($Generator -eq 'Ninja' -and $Toolchain -in @('MSVC2026', 'MSVC2026Latest')) {
        $suffix = if ($Toolchain -eq 'MSVC2026Latest') { 'latest_ninja' } else { 'ninja' }
        return Join-Path $Root "build_hobl_msvc2026_$suffix"
    }
    if ($Toolchain -eq 'MSVC2026Latest') { return Join-Path $Root 'build_hobl_msvc2026_latest' }
    if ($Toolchain -eq 'MSVC2026') { return Join-Path $Root 'build_hobl_msvc2026' }
    if ($Toolchain -eq 'Clang') { return Join-Path $Root 'build_hobl_clang_ninja' }
    $suffix = if ($Generator -eq 'Ninja') { 'ninja' } else { 'msvc' }
    return Join-Path $Root "build_hobl_$suffix"
}

function Get-InstalledOpenCVFile([string]$BuildDirectory, [string]$Name) {
    $manifest = Join-Path $BuildDirectory 'install_manifest.txt'
    if (-not (Test-Path $manifest)) { throw ' ERROR - OpenCV install manifest is missing; run installation first.' }
    $install = [IO.Path]::GetFullPath("$BuildDirectory\install").TrimEnd('\') + '\'
    $files = @(Get-Content $manifest | Where-Object { [IO.Path]::GetFileName($_) -eq $Name } |
        ForEach-Object {
            $path = [IO.Path]::GetFullPath($_)
            if (-not $path.StartsWith($install, [StringComparison]::OrdinalIgnoreCase)) {
                throw " ERROR - Install manifest entry is outside the benchmark install directory: $path"
            }
            Get-Item -LiteralPath $path -ErrorAction Stop
        })
    if ($Name -eq 'OpenCVConfig.cmake') {
        $files = @($files | Where-Object { Test-Path "$($_.DirectoryName)\OpenCVModules.cmake" })
    }
    if ($files.Count -ne 1) { throw " ERROR - Expected one current installed $Name; found $($files.Count)." }
    return $files[0]
}

function Invoke-Logged([string]$Executable, [string[]]$Arguments, [string]$Log) {
    $watch = [Diagnostics.Stopwatch]::StartNew()
    & $Executable @Arguments *> $Log
    $code = $LASTEXITCODE
    $watch.Stop()
    if ($code -ne 0) { throw " ERROR - $Executable exited $code; see $Log" }
    return [math]::Round($watch.Elapsed.TotalSeconds, 4)
}

function Assert-Source([string]$Root) {
    $commit = & git -C $Root rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $commit -ne $script:Config.opencv_commit) {
        throw " ERROR - OpenCV checkout must be $($script:Config.opencv_commit). Run setup first."
    }
    $dirty = & git -C $Root status --porcelain --untracked-files=no
    if ($LASTEXITCODE -ne 0 -or $dirty) { throw ' ERROR - Tracked OpenCV source modifications invalidate this benchmark.' }
}
