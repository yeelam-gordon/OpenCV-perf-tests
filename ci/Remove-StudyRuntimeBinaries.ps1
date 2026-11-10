#Requires -Version 7.0
param([Parameter(Mandatory)][string]$ResultsDir)
$ErrorActionPreference = 'Stop'
foreach ($directory in Get-ChildItem -LiteralPath $ResultsDir -Directory) {
    foreach ($name in @('opencv_world4100.dll', 'opencv_smoke.exe')) {
        $path = Join-Path $directory.FullName "runtime-binaries\$name"
        if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -ErrorAction Stop }
    }
}
