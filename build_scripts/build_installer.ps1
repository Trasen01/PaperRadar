param(
    [string]$Python = "python",
    [string]$InnoSetupCompiler = "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

if (-not (Test-Path "dist\PaperRadar\PaperRadar.exe")) {
    & "$PSScriptRoot\build_exe.ps1" -Python $Python
}

if (-not (Test-Path $InnoSetupCompiler)) {
    throw "Inno Setup compiler not found: $InnoSetupCompiler. Install Inno Setup 6 or pass -InnoSetupCompiler."
}

New-Item -ItemType Directory -Force -Path "dist\installer" | Out-Null
& $InnoSetupCompiler "installer\PaperRadar.iss"

if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

Write-Host "Installer generated under dist\installer"
