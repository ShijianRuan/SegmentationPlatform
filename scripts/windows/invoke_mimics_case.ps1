[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Doctor", "ProbeRun", "ProbeEvaluate", "Prepare", "Open", "Finalize", "Status")]
    [string]$Action,
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [Parameter(Mandatory = $true)]
    [string]$ConfigPath,
    [string]$CaseRoot = "",
    [string]$RegistryRoot = "",
    [string]$EvidencePath = "",
    [string]$OutputConfigPath = "",
    [string]$ReviewId = "",
    [switch]$RebuildWorkspace
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoRoot = (Resolve-Path $RepoRoot).Path
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python -PathType Leaf)) {
    throw "Platform virtual environment not found. Run setup_mimics_workstation.ps1 first."
}

function Require-Value([string]$Name, [string]$Value) {
    if (-not $Value) {
        throw "$Name is required for action $Action"
    }
}

switch ($Action) {
    "Doctor" {
        & $Python -m segplatform mimics doctor --config $ConfigPath --run-diagnostics
    }
    "ProbeRun" {
        Require-Value "CaseRoot" $CaseRoot
        & $Python -m segplatform mimics probe-run $CaseRoot --config $ConfigPath
    }
    "ProbeEvaluate" {
        Require-Value "CaseRoot" $CaseRoot
        Require-Value "EvidencePath" $EvidencePath
        Require-Value "OutputConfigPath" $OutputConfigPath
        & $Python -m segplatform mimics probe-evaluate $CaseRoot $EvidencePath `
            --config $ConfigPath --output-config $OutputConfigPath
    }
    "Prepare" {
        Require-Value "CaseRoot" $CaseRoot
        & $Python -m segplatform package validate $CaseRoot
        if ($RebuildWorkspace) {
            & $Python -m segplatform mimics prepare $CaseRoot --config $ConfigPath --rebuild-workspace
        } else {
            & $Python -m segplatform mimics prepare $CaseRoot --config $ConfigPath
        }
    }
    "Open" {
        Require-Value "CaseRoot" $CaseRoot
        if ($RegistryRoot) {
            & $Python -m segplatform mimics open $CaseRoot --config $ConfigPath --registry $RegistryRoot
        } else {
            & $Python -m segplatform mimics open $CaseRoot --config $ConfigPath
        }
    }
    "Finalize" {
        Require-Value "CaseRoot" $CaseRoot
        Require-Value "RegistryRoot" $RegistryRoot
        & $Python -m segplatform mimics finalize $CaseRoot --config $ConfigPath --registry $RegistryRoot
    }
    "Status" {
        Require-Value "RegistryRoot" $RegistryRoot
        if ($ReviewId) {
            & $Python -m segplatform review status --registry $RegistryRoot --review-id $ReviewId
        } else {
            & $Python -m segplatform review status --registry $RegistryRoot
        }
    }
}

if ($LASTEXITCODE -ne 0) {
    throw "SegmentationPlatform command failed with exit code $LASTEXITCODE"
}
