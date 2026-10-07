param(
    [string]$PythonPath = "",
    [switch]$IncludeTests
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

if (-not $PythonPath) {
    $inventoryPythonCandidate = Join-Path $env:LOCALAPPDATA "Programs\Python\Python314\python.exe"
    if (Test-Path -LiteralPath $inventoryPythonCandidate) {
        $PythonPath = $inventoryPythonCandidate
    } else {
        throw 'Python 3.14 was not found. Run Setup.ps1 -PythonPath "C:\path\to\python.exe".'
    }
}

& $PythonPath -c "import sys; print(sys.version); sys.exit(0 if sys.version_info[:2] == (3, 14) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Use the tested Python 3.14 runtime." }

$inventoryEnvironmentPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $inventoryEnvironmentPython)) {
    & $PythonPath -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Could not create the project environment." }
}

$inventoryRequirements = if ($IncludeTests) { "requirements-dev.txt" } else { "requirements.txt" }
& $inventoryEnvironmentPython -m pip install -r $inventoryRequirements
if ($LASTEXITCODE -ne 0) { throw "Could not install project dependencies." }

Write-Host "Setup complete. Double-click Start Inventory.cmd to open Windowstock."
