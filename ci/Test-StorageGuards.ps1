#Requires -Version 7.0
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest
$state = @{ disks = @(); volumes = @(); partitions = @(); drives = @(); mutations = 0 }
Set-Item Function:Get-Disk -Value { $state.disks }.GetNewClosure()
Set-Item Function:Get-Volume -Value { param($FilePath) $state.volumes }.GetNewClosure()
Set-Item Function:Get-Partition -Value { $state.partitions }.GetNewClosure()
Set-Item Function:Get-PSDrive -Value { param($PSProvider) $state.drives }.GetNewClosure()
Set-Item Function:Initialize-Disk -Value {
    param($InputObject, $PartitionStyle, [switch]$PassThru)
    $state.mutations++
    throw 'Test intercepted initialization; no disk was touched.'
}.GetNewClosure()
function New-Partition { throw 'Unexpected partition operation in a guard test.' }
function Format-Volume { throw 'Unexpected format operation in a guard test.' }
function Get-MpComputerStatus { [pscustomobject]@{ RealTimeProtectionEnabled = $true } }
function Get-MpPreference { [pscustomobject]@{ PerformanceModeStatus = 1 } }

$names = @('GITHUB_ACTIONS', 'HOSTING', 'RUNNER_OS', 'RUNNER_ARCH',
    'GITHUB_WORKSPACE', 'RUNNER_TEMP', 'GITHUB_ENV', 'GITHUB_OUTPUT')
$saved = @{}
foreach ($name in $names) { $saved[$name] = [Environment]::GetEnvironmentVariable($name) }
$temporary = Join-Path ([IO.Path]::GetTempPath()) ("opencv-ci-storage-guards-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $temporary | Out-Null
$cases = @(
    @{ name = 'self-hosted'; hosting = 'self-hosted'; expected = 'failed'; mutations = 0 },
    @{ name = 'wrong-architecture'; arch = 'X64'; expected = 'failed'; mutations = 0 },
    @{ name = 'standard'; mode = 'standard'; expected = 'succeeded'; mutations = 0 },
    @{ name = 'no-disks'; expected = 'ineligible'; mutations = 0 },
    @{ name = 'two-disks'; count = 2; expected = 'ineligible'; mutations = 0 },
    @{ name = 'existing-d-partition'; existing = 'partition'; expected = 'ineligible'; mutations = 0 },
    @{ name = 'existing-d-volume'; existing = 'volume'; expected = 'ineligible'; mutations = 0 },
    @{ name = 'existing-d-psdrive'; existing = 'psdrive'; expected = 'ineligible'; mutations = 0 },
    @{ name = 'formatted-disk'; field = 'PartitionStyle'; value = 'GPT'; expected = 'ineligible'; mutations = 0 },
    @{ name = 'boot-disk'; field = 'IsBoot'; value = $true; expected = 'ineligible'; mutations = 0 },
    @{ name = 'system-disk'; field = 'IsSystem'; value = $true; expected = 'ineligible'; mutations = 0 },
    @{ name = 'offline-disk'; field = 'IsOffline'; value = $true; expected = 'ineligible'; mutations = 0 },
    @{ name = 'readonly-disk'; field = 'IsReadOnly'; value = $true; expected = 'ineligible'; mutations = 0 },
    @{ name = 'partitioned-disk'; field = 'NumberOfPartitions'; value = 1; expected = 'ineligible'; mutations = 0 },
    @{ name = 'small-disk'; field = 'Size'; value = 49GB; expected = 'ineligible'; mutations = 0 },
    @{ name = 'non-nvme'; field = 'BusType'; value = 'SATA'; expected = 'ineligible'; mutations = 0 },
    @{ name = 'disk-in-inventory'; inventory = $true; expected = 'ineligible'; mutations = 0 },
    @{ name = 'eligible-error-surfaces'; expected = 'failed'; mutations = 1 }
)
try {
    foreach ($case in $cases) {
        $directory = Join-Path $temporary $case.name
        New-Item -ItemType Directory -Path $directory | Out-Null
        $env:GITHUB_ACTIONS = 'true'
        $env:HOSTING = if ($case.ContainsKey('hosting')) { $case.hosting } else { 'github-hosted' }
        $env:RUNNER_OS = 'Windows'
        $env:RUNNER_ARCH = if ($case.ContainsKey('arch')) { $case.arch } else { 'ARM64' }
        $env:GITHUB_WORKSPACE = $directory
        $env:RUNNER_TEMP = $directory
        $env:GITHUB_ENV = Join-Path $directory 'env.txt'
        $env:GITHUB_OUTPUT = Join-Path $directory 'output.txt'
        $state.mutations = 0
        $state.partitions = @([pscustomobject]@{ DriveLetter = 'C'; DiskNumber = 0 })
        $state.volumes = @([pscustomobject]@{ DriveLetter = 'C'; FileSystem = 'NTFS'; Size = 100GB; SizeRemaining = 60GB })
        $state.drives = @([pscustomobject]@{ Name = 'C' })
        $disk = [ordered]@{
            Number = 1; BusType = 'NVMe'; PartitionStyle = 'RAW'; IsBoot = $false
            IsSystem = $false; IsOffline = $false; IsReadOnly = $false
            NumberOfPartitions = 0; Size = 100GB
        }
        if ($case.ContainsKey('field')) { $disk[$case.field] = $case.value }
        $state.disks = @([pscustomobject]$disk)
        if ($case.name -eq 'no-disks') { $state.disks = @() }
        if ($case.ContainsKey('count')) { $state.disks += [pscustomobject]$disk }
        if ($case.ContainsKey('inventory')) {
            $state.partitions += [pscustomobject]@{ DriveLetter = 'E'; DiskNumber = 1 }
        }
        if ($case.ContainsKey('existing')) {
            switch ($case.existing) {
                partition { $state.partitions += [pscustomobject]@{ DriveLetter = 'D'; DiskNumber = 2 } }
                volume { $state.volumes += [pscustomobject]@{ DriveLetter = 'D'; FileSystem = 'NTFS'; Size = 100GB; SizeRemaining = 60GB } }
                psdrive { $state.drives += [pscustomobject]@{ Name = 'D' } }
            }
        }
        $mode = if ($case.ContainsKey('mode')) { $case.mode } else { 'devdrive' }
        $failure = $null
        try { & "$PSScriptRoot\Prepare-WindowsStorage.ps1" -Mode $mode }
        catch { $failure = $_ }
        $record = Get-Content -LiteralPath (Join-Path $directory 'evidence\storage.json') -Raw | ConvertFrom-Json
        if ($record.status -ne $case.expected -or $state.mutations -ne $case.mutations -or
            (($null -ne $failure) -ne ($case.expected -eq 'failed'))) {
            throw "Guard case failed: $($case.name); status=$($record.status), mutations=$($state.mutations); record=$($record | ConvertTo-Json -Compress)"
        }
    }
    "Passed $($cases.Count) non-destructive storage guard cases."
} finally {
    foreach ($name in $names) { [Environment]::SetEnvironmentVariable($name, $saved[$name]) }
    Remove-Item -LiteralPath $temporary -Recurse -Force
}
