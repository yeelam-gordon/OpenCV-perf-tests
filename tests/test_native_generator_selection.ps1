#Requires -Version 7.0
. "$PSScriptRoot\..\scripts\common.ps1"
$source = Join-Path ([IO.Path]::GetTempPath()) 'owned-source'
foreach ($toolchain in @('MSVC2026', 'MSVC2026Latest')) {
    if ((Get-EffectiveGenerator 'Ninja' $toolchain $true) -ne 'Ninja') {
        throw ' ERROR - Explicit Ninja selection was not retained.'
    }
    if ((Get-EffectiveGenerator 'MSBuild' $toolchain $false) -ne 'MSBuild') {
        throw ' ERROR - Original default MSBuild selection changed.'
    }
    $msbuild = Get-BuildDirectory $source 'MSBuild' $toolchain
    $ninja = Get-BuildDirectory $source 'Ninja' $toolchain
    if ($msbuild -eq $ninja -or -not $ninja.EndsWith('_ninja')) {
        throw ' ERROR - Generator build trees must remain isolated.'
    }
}
if ((Get-EffectiveGenerator 'MSBuild' 'Clang' $false) -ne 'Ninja') {
    throw ' ERROR - Existing Clang default changed.'
}
$rejected = $false
try { Get-EffectiveGenerator 'MSBuild' 'Clang' $true | Out-Null }
catch {
    if ($_.Exception.Message -notmatch 'Clang experiment requires') { throw }
    $rejected = $true
}
if (-not $rejected) { throw ' ERROR - Unsupported Clang/MSBuild selection was accepted.' }
'Native generator selection/isolation and existing defaults verified.'
