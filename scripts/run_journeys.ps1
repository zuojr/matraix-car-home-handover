param(
    [Parameter(Mandatory=$true)][string]$Plan,
    [Parameter(Mandatory=$true)][string]$Output,
    [string]$Config,
    [string]$KeyFile,
    [string]$Python = "python",
    [string]$NativeRoot,
    [switch]$Execute
)

$ErrorActionPreference = "Stop"
$taskRepo = Split-Path -Parent $PSScriptRoot
if (-not $Config) { $Config = Join-Path $taskRepo "configs/journeys/sol61-8.example.json" }
if (-not $NativeRoot) {
    $NativeRoot = $env:SIMUHOME_ROOT
    if (-not $NativeRoot) { $NativeRoot = Join-Path $taskRepo "journey-runs/native/SimuHome" }
}
if (-not (Test-Path -LiteralPath $NativeRoot)) {
    throw "Pinned native source missing. Run: python -m matraix.journeys setup-native --directory journey-runs/native/SimuHome"
}
$env:SIMUHOME_ROOT = (Resolve-Path -LiteralPath $NativeRoot).Path
$env:PYTHONUTF8 = "1"
$taskArguments = @("-m", "matraix.journeys", "execute", "--plan", $Plan, "--config", $Config, "--out", $Output)
if ($KeyFile) { $taskArguments += @("--key-file", $KeyFile) }
if ($Execute) { $taskArguments += "--execute" }
& $Python @taskArguments
exit $LASTEXITCODE
