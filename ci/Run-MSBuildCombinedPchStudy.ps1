#Requires -Version 7.0
param(
    [Parameter(Mandatory)][string]$ResultsDir,
    [ValidateSet('six', 'ten')][string]$PchHeaderSet = 'six'
)
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\Run-QualifiedGeneratorStudy.ps1" -ResultsDir $ResultsDir -ClServerStudy -CombinedPch -PchHeaderSet $PchHeaderSet
