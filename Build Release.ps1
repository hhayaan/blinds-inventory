param(
    [switch]$SkipInstall,
    [switch]$SkipTests
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$inventoryProjectRoot = [IO.Path]::GetFullPath($PSScriptRoot)
$inventoryReleaseRoot = Join-Path $inventoryProjectRoot "release"
$inventoryWorkRoot = Join-Path $inventoryReleaseRoot "work"
$inventoryOutputRoot = Join-Path $inventoryReleaseRoot "Windowstock"
$inventoryArchivePath = Join-Path $inventoryReleaseRoot "Windowstock.zip"
$inventoryBuildPython = Join-Path $inventoryProjectRoot ".venv\Scripts\python.exe"

function Assert-GeneratedPath([string]$Path) {
    $inventoryAbsoluteTarget = [IO.Path]::GetFullPath($Path)
    $inventoryAllowedPrefix = $inventoryReleaseRoot.TrimEnd('\', '/') + [IO.Path]::DirectorySeparatorChar
    if (-not $inventoryAbsoluteTarget.StartsWith($inventoryAllowedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Generated target must be inside $inventoryReleaseRoot : $inventoryAbsoluteTarget"
    }
    # Refuse junctions/symlinks before recursive removal or moving build output.
    $inventoryAncestor = $inventoryAbsoluteTarget
    while ($inventoryAncestor.Length -ge $inventoryReleaseRoot.Length) {
        if (Test-Path -LiteralPath $inventoryAncestor) {
            $inventoryEntry = Get-Item -LiteralPath $inventoryAncestor -Force
            if ($inventoryEntry.Attributes -band [IO.FileAttributes]::ReparsePoint) {
                throw "Build paths cannot contain junctions or symbolic links: $inventoryAncestor"
            }
        }
        if ($inventoryAncestor -eq $inventoryReleaseRoot) { break }
        $inventoryAncestor = Split-Path -Parent $inventoryAncestor
    }
    if (Test-Path -LiteralPath $inventoryAbsoluteTarget -PathType Container) {
        $inventoryLinkedEntry = Get-ChildItem -LiteralPath $inventoryAbsoluteTarget -Recurse -Force |
            Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint } |
            Select-Object -First 1
        if ($inventoryLinkedEntry) {
            throw "Build output contains a junction or symbolic link: $($inventoryLinkedEntry.FullName)"
        }
    }
}

function Remove-GeneratedPath([string]$Path) {
    Assert-GeneratedPath $Path
    if ([IO.Path]::GetFullPath($Path) -eq $inventoryOutputRoot -and
        (Test-Path -LiteralPath (Join-Path $inventoryOutputRoot "data"))) {
        throw "Inventory data appeared in release\Windowstock during the build. Back it up and move that folder out of release before rebuilding."
    }
    if (Test-Path -LiteralPath $Path) { Remove-Item -LiteralPath $Path -Recurse -Force }
}

if (-not (Test-Path -LiteralPath $inventoryBuildPython -PathType Leaf)) {
    throw "Run Setup.ps1 first to create the project's Python environment."
}
& $inventoryBuildPython -c "import sys, struct; sys.exit(0 if sys.platform == 'win32' and sys.version_info[:2] == (3, 14) and struct.calcsize('P') == 8 else 1)"
if ($LASTEXITCODE -ne 0) { throw "Build using the tested Windows 64-bit Python 3.14 environment." }

Assert-GeneratedPath $inventoryOutputRoot
if (Test-Path -LiteralPath (Join-Path $inventoryOutputRoot "data")) {
    throw "release\Windowstock contains inventory data. Back it up and move that application folder out of release before rebuilding; the build will not erase it."
}

Push-Location -LiteralPath $inventoryProjectRoot
try {
    if (-not $SkipInstall) {
        & $inventoryBuildPython -m pip install -r requirements-build.txt
        if ($LASTEXITCODE -ne 0) { throw "Could not install release build dependencies." }
    }
    if (-not $SkipTests) {
        & $inventoryBuildPython -m pytest
        if ($LASTEXITCODE -ne 0) { throw "Tests failed; no new release was published." }
    }

    Remove-GeneratedPath $inventoryWorkRoot
    New-Item -ItemType Directory -Path $inventoryWorkRoot -Force | Out-Null
    & $inventoryBuildPython -m PyInstaller --noconfirm --clean --log-level WARN `
        --workpath (Join-Path $inventoryWorkRoot "pyinstaller") `
        --distpath (Join-Path $inventoryWorkRoot "dist") `
        packaging\windowstock.spec
    if ($LASTEXITCODE -ne 0) { throw "Packaging failed; inspect release\work for diagnostics." }

    $inventoryStagedBundle = Join-Path $inventoryWorkRoot "dist\Windowstock"
    $inventoryStagedArchive = Join-Path $inventoryWorkRoot "Windowstock.zip"
    Assert-GeneratedPath $inventoryStagedBundle
    if (-not (Test-Path -LiteralPath (Join-Path $inventoryStagedBundle "Windowstock.exe"))) {
        throw "The packaged executable is missing."
    }
    $inventoryUnexpectedData = Get-ChildItem -LiteralPath $inventoryStagedBundle -Recurse -File |
        Where-Object { $_.Name -match '\.sqlite3(?:-wal|-shm)?$' }
    if ($inventoryUnexpectedData) { throw "A database was unexpectedly included in the release." }

    & $inventoryBuildPython packaging\smoke_release.py $inventoryStagedBundle
    if ($LASTEXITCODE -ne 0) { throw "The packaged application smoke test failed; the previous release was retained." }

    Copy-Item -LiteralPath (Join-Path $inventoryProjectRoot "packaging\START HERE.txt") `
        -Destination (Join-Path $inventoryStagedBundle "START HERE.txt")
    & $inventoryBuildPython packaging\release_manifest.py $inventoryStagedBundle
    if ($LASTEXITCODE -ne 0) { throw "Could not write release build information." }
    # Store the bundle's contents at the ZIP root, without a Windowstock wrapper.
    Compress-Archive -Path (Join-Path $inventoryStagedBundle "*") -DestinationPath $inventoryStagedArchive -CompressionLevel Optimal

    # Publish only after tests, packaging, and ZIP creation have succeeded.
    Assert-GeneratedPath $inventoryStagedArchive
    Assert-GeneratedPath $inventoryArchivePath
    Remove-GeneratedPath $inventoryOutputRoot
    Move-Item -LiteralPath $inventoryStagedBundle -Destination $inventoryOutputRoot
    if (Test-Path -LiteralPath $inventoryArchivePath) { Remove-Item -LiteralPath $inventoryArchivePath -Force }
    Move-Item -LiteralPath $inventoryStagedArchive -Destination $inventoryArchivePath
    Remove-GeneratedPath $inventoryWorkRoot

    Write-Host "Release ready: $inventoryArchivePath"
    Write-Host "Extract the ZIP, then double-click Windowstock.exe. No Python installation is required."
} finally {
    Pop-Location
}
