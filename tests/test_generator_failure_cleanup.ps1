#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$repo = Split-Path $PSScriptRoot
$tokens = $null
$errors = $null
$ast = [Management.Automation.Language.Parser]::ParseFile(
    (Join-Path $repo 'ci\Run-QualifiedGeneratorStudy.ps1'), [ref]$tokens, [ref]$errors)
if ($errors.Count) { throw ($errors | Out-String) }
$blocks = @($ast.FindAll({
    param($node)
    $node -is [Management.Automation.Language.TryStatementAst] -and
    $null -ne $node.Finally -and $node.Finally.Extent.Text.Contains('$cleanupScript -ResultsDir')
}, $true))
if ($blocks.Count -ne 1) { throw 'Expected one actual study failure/cleanup boundary.' }
$catchText = $blocks[0].CatchClauses[0].Body.Extent.Text
$finallyText = $blocks[0].Finally.Extent.Text
$boundary = [scriptblock]::Create(
    "try { throw 'fixture post-copy evidence failure' } catch $catchText finally $finallyText")
$temp = Join-Path ([IO.Path]::GetTempPath()) ("qualified-ci-cleanup-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temp | Out-Null
try {
    foreach ($cleanupFails in @($false, $true)) {
        $ResultsDir = Join-Path $temp "case-$cleanupFails"
        $binaries = Join-Path $ResultsDir 'unregistered-run\runtime-binaries'
        New-Item -ItemType Directory -Path $binaries | Out-Null
        foreach ($name in @('opencv_world4100.dll', 'opencv_smoke.exe')) {
            [IO.File]::WriteAllText((Join-Path $binaries $name), 'fixture')
        }
        $log = Join-Path $ResultsDir 'unregistered-run\build.log'
        [IO.File]::WriteAllText($log, 'original failure evidence')
        $cleanupScript = Join-Path $repo 'ci\Remove-StudyRuntimeBinaries.ps1'
        if ($cleanupFails) {
            $cleanupScript = Join-Path $temp 'failing-cleanup.ps1'
            [IO.File]::WriteAllText($cleanupScript, "throw 'fixture cleanup failure'")
        }
        $study = [ordered]@{ status = 'running'; runs = @() }
        $primaryFailure = $null
        $caught = $null
        try { . $boundary } catch { $caught = $_ }
        if ($null -eq $caught -or $caught.Exception.Message -ne 'fixture post-copy evidence failure') {
            $message = if ($null -eq $caught) { 'no exception' } else { $caught.Exception.Message }
            throw "Cleanup masked the original evidence failure: $message"
        }
        $receipt = Get-Content -LiteralPath (Join-Path $ResultsDir 'study.json') -Raw | ConvertFrom-Json
        if ($receipt.status -ne 'failed' -or $receipt.error -ne 'fixture post-copy evidence failure' -or
            (Get-Content -LiteralPath $log -Raw) -ne 'original failure evidence') {
            throw 'Original failure state/log was not retained.'
        }
        if (-not $cleanupFails -and
            ((Test-Path -LiteralPath (Join-Path $binaries 'opencv_world4100.dll')) -or
             (Test-Path -LiteralPath (Join-Path $binaries 'opencv_smoke.exe')))) {
            throw 'Unregistered partial-run binaries were not removed.'
        }
        if ($cleanupFails -and $receipt.cleanup_error -ne 'fixture cleanup failure') {
            throw 'Cleanup failure diagnostics were not retained.'
        }
    }
    'Passed post-copy failure cleanup and primary-error preservation against actual catch/finally blocks.'
} finally {
    Remove-Item -LiteralPath $temp -Recurse -Force
}
