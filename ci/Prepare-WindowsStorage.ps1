#Requires -Version 7.0
param(
    [Parameter(Mandatory)][ValidateSet('standard', 'devdrive')][string]$Mode
)
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$evidence = Join-Path $env:GITHUB_WORKSPACE 'evidence'
New-Item -ItemType Directory -Force -Path $evidence | Out-Null
$watch = [Diagnostics.Stopwatch]::StartNew()
$record = [ordered]@{
    requested = $Mode
    status = 'running'
    applied = $false
    policy = 'New unused disk only; default Dev Drive protection; no trust/filter/AV overrides.'
}
try {
    if ($env:GITHUB_ACTIONS -ne 'true' -or $env:HOSTING -ne 'github-hosted' -or
        $env:RUNNER_OS -ne 'Windows' -or $env:RUNNER_ARCH -ne 'ARM64' -or
        [Runtime.InteropServices.RuntimeInformation]::OSArchitecture.ToString() -ne 'Arm64') {
        throw ' ERROR - Storage preparation is restricted to GitHub-hosted Windows Arm64.'
    }
    $record['disks_before'] = @(Get-Disk | Select-Object Number, BusType, PartitionStyle,
        IsBoot, IsSystem, IsOffline, IsReadOnly, NumberOfPartitions, Size)
    $partitions = @(Get-Partition)
    $volumes = @(Get-Volume)
    $record['volumes_before'] = @($volumes | Select-Object DriveLetter, FileSystem, Size, SizeRemaining)
    $root = Join-Path $env:RUNNER_TEMP 'opencv-ci'
    if ($Mode -eq 'devdrive') {
        $drives = @(Get-PSDrive -PSProvider FileSystem)
        if (($partitions | Where-Object DriveLetter -EQ 'D') -or
            ($volumes | Where-Object DriveLetter -EQ 'D') -or
            ($drives | Where-Object Name -EQ 'D')) {
            $record.status = 'ineligible'
            $record['reason'] = 'D: is already assigned; existing storage was not changed.'
            Write-Host $record.reason
            return
        }
        $candidates = @(Get-Disk | Where-Object {
            $_.BusType -eq 'NVMe' -and $_.PartitionStyle -eq 'RAW' -and
            -not $_.IsBoot -and -not $_.IsSystem -and
            -not $_.IsOffline -and -not $_.IsReadOnly -and
            $_.NumberOfPartitions -eq 0 -and $_.Size -ge 50GB -and
            $_.Number -notin $partitions.DiskNumber
        })
        if ($candidates.Count -ne 1) {
            $record.status = 'ineligible'
            $record['reason'] = "Found $($candidates.Count) eligible unused disks; no storage changed."
            Write-Host $record.reason
            return
        }
        $partition = Initialize-Disk -InputObject $candidates[0] -PartitionStyle GPT -PassThru |
            New-Partition -UseMaximumSize -DriveLetter D
        $volume = $partition | Format-Volume -DevDrive -FileSystem ReFS `
            -NewFileSystemLabel 'OpenCV-CI' -Confirm:$false
        if ($volume.FileSystem -ne 'ReFS' -or $volume.DriveLetter -ne 'D') {
            throw ' ERROR - New volume is not ReFS on D:.'
        }
        $query = & fsutil devdrv query D: 2>&1
        if ($LASTEXITCODE) { throw ' ERROR - Cannot verify the new Dev Drive.' }
        $query | Set-Content -LiteralPath (Join-Path $evidence 'devdrive-query.txt')
        $root = 'D:\opencv-ci'
    }
    if (Test-Path -LiteralPath $root) { throw ' ERROR - Isolated experiment directory already exists.' }
    New-Item -ItemType Directory -Path $root, (Join-Path $root 'temp') | Out-Null
    $record['root'] = $root
    $record['filesystem'] = (Get-Volume -FilePath $root).FileSystem
    $record['defender'] = Get-MpComputerStatus |
        Select-Object AMRunningMode, AntivirusEnabled, RealTimeProtectionEnabled, AMProductVersion
    $record['defender_performance_preferences'] = Get-MpPreference |
        Select-Object PerformanceModeStatus, DisableDevDriveScanning
    "OPENCV_CI_ROOT=$root" >> $env:GITHUB_ENV
    "TEMP=$(Join-Path $root 'temp')" >> $env:GITHUB_ENV
    "TMP=$(Join-Path $root 'temp')" >> $env:GITHUB_ENV
    $record.status = 'succeeded'
    $record.applied = $true
} catch {
    $record.status = 'failed'
    $record['error'] = $_.Exception.Message
    throw
} finally {
    $watch.Stop()
    $record['prepare_seconds'] = $watch.Elapsed.TotalSeconds
    $record | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $evidence 'storage.json')
    "applied=$($record.applied.ToString().ToLowerInvariant())" >> $env:GITHUB_OUTPUT
}
