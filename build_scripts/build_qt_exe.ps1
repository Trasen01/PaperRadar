param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "Building PaperRadar.exe with PySide6..."
$RunningApp = Get-Process -Name "PaperRadar","PaperRadarQt" -ErrorAction SilentlyContinue
if ($RunningApp) {
    Write-Host "Stopping running PaperRadar process before packaging..."
    $RunningApp | Stop-Process -Force
    Start-Sleep -Seconds 1
}
& $Python -m PyInstaller --clean --noconfirm "PaperRadar.qt.spec"

$ExePath = Join-Path $ProjectRoot "dist\PaperRadar\PaperRadar.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build failed: $ExePath was not created."
}

Write-Host "PaperRadar.exe generated at dist\PaperRadar\PaperRadar.exe"
Write-Host "Legacy Tk build remains available through build_exe.ps1."
