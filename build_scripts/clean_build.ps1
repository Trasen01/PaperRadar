$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot

$Targets = @(
    (Join-Path $ProjectRoot "build"),
    (Join-Path $ProjectRoot "dist"),
    (Join-Path $ProjectRoot "__pycache__")
)

foreach ($Target in $Targets) {
    $ResolvedProject = (Resolve-Path $ProjectRoot).Path
    if (Test-Path $Target) {
        $ResolvedTarget = (Resolve-Path $Target).Path
        if (-not $ResolvedTarget.StartsWith($ResolvedProject, [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Refusing to remove path outside project: $ResolvedTarget"
        }
        Remove-Item -LiteralPath $ResolvedTarget -Recurse -Force
        Write-Host "Removed $ResolvedTarget"
    }
}

Write-Host "Build artifacts cleaned. User data in %APPDATA%\PaperRadar was not touched."
