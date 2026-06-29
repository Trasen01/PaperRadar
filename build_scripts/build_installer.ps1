$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Get-Process -Name "PaperRadar", "paperradar", "paperradar-backend" -ErrorAction SilentlyContinue | Stop-Process -Force

$Python = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $Python)) {
    $Python = "python"
}

Write-Host "Building Python sidecar..."
& $Python -m PyInstaller --clean --noconfirm "packaging\paperradar-backend.spec"
if ($LASTEXITCODE -ne 0) {
    throw "Python sidecar build failed with exit code $LASTEXITCODE."
}

$SidecarSource = Join-Path $ProjectRoot "dist\paperradar-backend-x86_64-pc-windows-msvc.exe"
$SidecarTarget = Join-Path $ProjectRoot "desktop\src-tauri\binaries\paperradar-backend-x86_64-pc-windows-msvc.exe"
if (-not (Test-Path $SidecarSource)) {
    throw "Python sidecar output not found: $SidecarSource"
}
Copy-Item -LiteralPath $SidecarSource -Destination $SidecarTarget -Force

Write-Host "Building PaperRadar with the current Tauri desktop flow..."
Push-Location "desktop"
try {
    npm run desktop:build
} finally {
    Pop-Location
}

$ReleaseDir = Join-Path $ProjectRoot "desktop\src-tauri\target\release"
$BundleInstaller = Join-Path $ReleaseDir "bundle\nsis\PaperRadar_0.4.0_x64-setup.exe"
$AppExe = Join-Path $ReleaseDir "paperradar.exe"
$BackendExe = Join-Path $ReleaseDir "paperradar-backend.exe"

foreach ($Path in @($BundleInstaller, $AppExe, $BackendExe)) {
    if (-not (Test-Path $Path)) {
        throw "Build output not found: $Path"
    }
}

$PortableDir = Join-Path $ProjectRoot "dist\PaperRadar-v0.4.0"
$InstallerDir = Join-Path $ProjectRoot "dist\installer"
New-Item -ItemType Directory -Force -Path $PortableDir, $InstallerDir | Out-Null
Copy-Item -LiteralPath $AppExe -Destination (Join-Path $PortableDir "PaperRadar.exe") -Force
Copy-Item -LiteralPath $BackendExe -Destination (Join-Path $PortableDir "paperradar-backend.exe") -Force
Copy-Item -LiteralPath $BundleInstaller -Destination (Join-Path $InstallerDir "PaperRadar_Setup_v0.4.0.exe") -Force
Remove-Item -LiteralPath $SidecarSource -Force -ErrorAction SilentlyContinue

Write-Host "Portable app staged at dist\PaperRadar-v0.4.0"
Write-Host "Installer staged at dist\installer\PaperRadar_Setup_v0.4.0.exe"
