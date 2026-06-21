# Build Lambda deployment zip from rcs/ (core) + web/backend/lambda_function.py (adapter).
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PackageDir = Join-Path $RepoRoot "dist\package"
$ZipPath = Join-Path $RepoRoot "dist\lambda.zip"

if (Test-Path (Join-Path $RepoRoot "dist")) {
    Remove-Item -Recurse -Force (Join-Path $RepoRoot "dist")
}
New-Item -ItemType Directory -Path $PackageDir -Force | Out-Null

Copy-Item (Join-Path $RepoRoot "web\backend\lambda_function.py") $PackageDir
Copy-Item -Recurse (Join-Path $RepoRoot "rcs") (Join-Path $PackageDir "rcs")

# CLI scripts and playground output are not needed in Lambda.
Remove-Item (Join-Path $PackageDir "rcs\rcs_test_list.py") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $PackageDir "rcs\rcs_test_interactive.py") -ErrorAction SilentlyContinue
Get-ChildItem -Path (Join-Path $PackageDir "rcs") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -Force
Write-Host "Built $ZipPath"
