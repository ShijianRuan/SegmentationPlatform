[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path,
    [string]$PythonCommand = "py",
    [string]$PythonSelector = "-3.11",
    [Parameter(Mandatory = $true)]
    [string]$MimicsExecutable,
    [string]$WorkRoot = "D:\SegmentationPlatform\work",
    [string]$ConfigPath = "",
    [string]$RegistryRoot = "",
    [string]$Assignee = "",
    [bool]$ClaimUnassigned = $true,
    [switch]$AutoFinalize
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Quote-Yaml([string]$Value) {
    return "'" + $Value.Replace("'", "''") + "'"
}

function Assert-NativeSuccess([string]$Step) {
    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE"
    }
}

$RepoRoot = (Resolve-Path $RepoRoot).Path
if (-not (Test-Path $MimicsExecutable -PathType Leaf)) {
    throw "Mimics executable not found: $MimicsExecutable"
}
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $RepoRoot "config\mimics_workstation.local.yaml"
}
$ConfigPath = [System.IO.Path]::GetFullPath($ConfigPath)
if ($RegistryRoot) {
    $RegistryRoot = [System.IO.Path]::GetFullPath($RegistryRoot)
}

$VenvRoot = Join-Path $RepoRoot ".venv"
if (-not (Test-Path $VenvRoot -PathType Container)) {
    if ($PythonSelector) {
        & $PythonCommand $PythonSelector -m venv $VenvRoot
    } else {
        & $PythonCommand -m venv $VenvRoot
    }
    Assert-NativeSuccess "Creating the virtual environment"
}
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
if (-not (Test-Path $VenvPython -PathType Leaf)) {
    throw "Virtual environment Python was not created: $VenvPython"
}

& $VenvPython -m pip install --upgrade pip
Assert-NativeSuccess "Upgrading pip"
& $VenvPython -m pip install -e $RepoRoot
Assert-NativeSuccess "Installing SegmentationPlatform"

New-Item -ItemType Directory -Force -Path $WorkRoot | Out-Null
$RuntimeDir = Join-Path $RepoRoot "adapters\mimics\runtime_py35"
$ScriptingLibraryDir = Join-Path $RepoRoot "adapters\mimics\scripting_library"
$ProbeDir = Join-Path $RepoRoot "adapters\mimics\probes"
$ConfigDir = Split-Path -Parent $ConfigPath
New-Item -ItemType Directory -Force -Path $ConfigDir | Out-Null
New-Item -ItemType Directory -Force -Path $ScriptingLibraryDir | Out-Null

$Yaml = @(
    "schema_version: mimics_workstation.v1"
    ""
    "expected_product: Mimics Research"
    'expected_version: "21.0"'
    "edition: Research"
    "license_modules: [Scripting]"
    ""
    "executable: $(Quote-Yaml $MimicsExecutable)"
    "runtime_script_dir: $(Quote-Yaml $RuntimeDir)"
    "probe_script_dir: $(Quote-Yaml $ProbeDir)"
    "work_root: $(Quote-Yaml $WorkRoot)"
    "doctor_timeout_seconds: 180"
    ""
    "predefined_dialog_answers: {}"
    ""
    "buffer_mapping:"
    "  schema_version: mimics_buffer_mapping.v1"
    "  status: unverified"
    '  evidence_id: ""'
    "  platform_to_mimics_axes: [0, 1, 2]"
    "  platform_to_mimics_flips: [false, false, false]"
)
[System.IO.File]::WriteAllLines($ConfigPath, $Yaml, [System.Text.UTF8Encoding]::new($false))

Write-Host "Workstation configuration written to: $ConfigPath"

if ($RegistryRoot -and $Assignee) {
    $ConsoleConfigPath = Join-Path $ScriptingLibraryDir "sp_review_console.local.json"
    $ConsoleConfig = [ordered]@{
        platform_python = $VenvPython
        registry_root = $RegistryRoot
        workstation_config = $ConfigPath
        assignee = $Assignee
        claim_unassigned = [bool]$ClaimUnassigned
        auto_finalize = [bool]$AutoFinalize
        checkpoint_keep_count = 3
    }
    $ConsoleConfig | ConvertTo-Json -Depth 4 | Set-Content -Path $ConsoleConfigPath -Encoding UTF8
    Write-Host "Mimics labeling configuration written to: $ConsoleConfigPath"
} else {
    Write-Host "Mimics labeling configuration was not written. Pass -RegistryRoot and -Assignee, or copy config\mimics_review_console.example.json manually."
}

& $VenvPython -m segplatform mimics doctor --config $ConfigPath
Assert-NativeSuccess "Running the static workstation doctor"
Write-Host ""
Write-Host "Setup completed. Run diagnostics next:"
Write-Host "  $VenvPython -m segplatform mimics doctor --config `"$ConfigPath`" --run-diagnostics"
Write-Host "Set Mimics File > Preferences > Scripting library path to:"
Write-Host "  $ScriptingLibraryDir"
