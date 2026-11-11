#Requires -Version 7.0
param([Parameter(Mandatory)][string]$ResultsDir)
$ErrorActionPreference = 'Stop'
& "$PSScriptRoot\Run-QualifiedGeneratorStudy.ps1" -ResultsDir $ResultsDir -ClServerStudy -CombinedPch
