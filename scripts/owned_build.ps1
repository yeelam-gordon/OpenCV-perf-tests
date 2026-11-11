function Invoke-OwnedBuild([string]$Executable, [string[]]$Arguments, [string]$Directory, [string]$RunDirectory) {
    $quoted = @($Arguments | ForEach-Object {
        if ($_ -match '["\r\n]') { throw ' ERROR - Unsupported owned-build argument.' }
        '"' + $_ + '"'
    })
    $result = [BuildAccounting]::RunOwned($Executable, ($quoted -join ' '), $Directory, "$RunDirectory\build.log")
    @{
        exit_code = $result.ExitCode; build_seconds = $result.WallSeconds
        started_at = $result.StartedAt; finished_at = $result.FinishedAt
        descendants_drained_after_clock = $true
        scope = 'Suspended owned job, wall clock only; no PID sampler, residency/busy cap or profiling claim.'
    } | ConvertTo-Json | Set-Content "$RunDirectory\owned-build.json"
    if ($result.ExitCode) { throw " ERROR - Owned build exited $($result.ExitCode)." }
    return [math]::Round($result.WallSeconds, 4)
}
