param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "Building PaperRadar.exe..."
& $Python -m PyInstaller --clean --noconfirm "PaperRadar.release.spec"

$ExePath = Join-Path $ProjectRoot "dist\PaperRadar\PaperRadar.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build failed: $ExePath was not created."
}

Write-Host "PaperRadar.exe generated at dist\PaperRadar\PaperRadar.exe"
Write-Host "User data is not bundled. Runtime data is stored in %APPDATA%\PaperRadar."
