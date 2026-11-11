#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
$repo = Split-Path $PSScriptRoot
$scratch = Join-Path $repo ('.work\owned-build-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $scratch | Out-Null
$previous = $env:OPENCV_OWNED_TEST_ROOT
try {
    foreach ($case in @(
        @{ EnableClServerMode = $true },
        @{ MSBuildStudyPlan = 'fixture'; Generator = 'Ninja' },
        @{ MSBuildStudyPlan = 'fixture'; Profile = $true }
        @{ MSBuildStudyPlan = 'fixture'; MSBuildScheduler = 'MultiToolTask'; SharedCompilerLimit = $true }
        @{ MSBuildStudyPlan = 'fixture'; MSBuildScheduler = 'MultiToolTask'; SharedCompilerLimit = $true;
            EnableClServerMode = $true; CompilerJobs = 8; Parallel = 4 }
        @{ MSBuildScheduler = 'MultiToolTask'; SharedCompilerLimit = $true; EnableClServerMode = $true;
            CompilerJobs = 4; Parallel = 4 }
    )) {
        $caught = $null
        try { & "$repo\scripts\run.ps1" -Root $scratch @case } catch { $caught = $_ }
        if ($null -eq $caught -or $caught.Exception.Message -notmatch 'CL server requires|paired MSBuild study') {
            throw 'Invalid study mode reached source/configure/build work.'
        }
    }
    if (-not ('BuildAccounting' -as [type])) { Add-Type -Path "$repo\scripts\BuildAccounting.cs" }
    $env:OPENCV_OWNED_TEST_ROOT = $scratch
    $fixture = Join-Path $scratch 'parent.ps1'
    @'
$child = Start-Process -FilePath (Get-Process -Id $PID).Path -ArgumentList '-NoProfile -Command "Start-Sleep -Seconds 60"' -PassThru
$child.Id | Set-Content (Join-Path $env:OPENCV_OWNED_TEST_ROOT 'child-pid.txt')
Write-Output 'owned fixture parent finished'
'@ | Set-Content -LiteralPath $fixture
    $shell = (Get-Process -Id $PID).Path
    $result = [BuildAccounting]::RunOwned($shell, "-NoProfile -File `"$fixture`"", $scratch, (Join-Path $scratch 'build.log'))
    if ($result.ExitCode -ne 0) { throw 'Owned fixture failed.' }
    $childId = [int](Get-Content (Join-Path $scratch 'child-pid.txt'))
    if (Get-Process -Id $childId -ErrorAction SilentlyContinue) { throw 'Owned resident descendant survived job drain.' }
    if ((Get-Content (Join-Path $scratch 'build.log') -Raw) -notmatch 'owned fixture parent finished') {
        throw 'Owned combined log missing.'
    }
    $failure = [BuildAccounting]::RunOwned($env:ComSpec, '/d /c exit 7', $scratch, (Join-Path $scratch 'failure.log'))
    if ($failure.ExitCode -ne 7) { throw 'Owned lifecycle masked the failed root exit code.' }
    'PASS: invalid modes fail before build; managed helper compiles; owned parent/descendant drain verified without compiler/PID sampling.'
} finally {
    $env:OPENCV_OWNED_TEST_ROOT = $previous
    Remove-Item -LiteralPath $scratch -Recurse -Force
}
