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
    $candidates = @(
        (Get-Command "ISCC.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source -First 1),
        "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
        "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
        "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
    ) | Where-Object { $_ -and (Test-Path $_) }

    $candidates = @($candidates)
    if ($candidates.Count -gt 0) {
        $InnoSetupCompiler = $candidates[0]
    }
}

if (-not (Test-Path $InnoSetupCompiler)) {
    throw "Inno Setup compiler not found. Install Inno Setup 6 or pass -InnoSetupCompiler."
}

New-Item -ItemType Directory -Force -Path "dist\installer" | Out-Null
& $InnoSetupCompiler "installer\PaperRadar.iss"

if ($LASTEXITCODE -ne 0) {
    throw "Inno Setup failed with exit code $LASTEXITCODE."
}

Write-Host "Installer generated under dist\installer"
