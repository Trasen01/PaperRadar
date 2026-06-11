param(
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "Building PaperRadar.exe..."
$RunningApp = Get-Process -Name "PaperRadar" -ErrorAction SilentlyContinue
if ($RunningApp) {
    Write-Host "Stopping running PaperRadar process before packaging..."
    $RunningApp | Stop-Process -Force
    Start-Sleep -Seconds 1
}
& $Python -m PyInstaller --clean --noconfirm "PaperRadar.release.spec"

$ExePath = Join-Path $ProjectRoot "dist\PaperRadar\PaperRadar.exe"
if (-not (Test-Path $ExePath)) {
    throw "Build failed: $ExePath was not created."
}

Write-Host "PaperRadar.exe generated at dist\PaperRadar\PaperRadar.exe"
Write-Host "User data is not bundled. Runtime data is stored in %APPDATA%\PaperRadar."
