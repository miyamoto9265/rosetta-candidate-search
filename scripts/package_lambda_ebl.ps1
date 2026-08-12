# Build Lambda zip for RCS_EBL (BNA lookup test API).
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PackageDir = Join-Path $RepoRoot "dist\package_ebl"
$ZipPath = Join-Path $RepoRoot "dist\lambda_ebl.zip"
$ReadyDir = Join-Path $RepoRoot "ebl_for_rcs_v1.0_20260722\rcs_ready"

if (-not (Test-Path (Join-Path $ReadyDir "bna_name_candidates.csv"))) {
    throw "Missing EBL rcs_ready tables. Run: python scripts/build_rcs_bna_tables.py"
}

if (Test-Path $PackageDir) {
    Remove-Item -Recurse -Force $PackageDir
}
New-Item -ItemType Directory -Path $PackageDir -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "ebl_data") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $PackageDir "rcs") -Force | Out-Null

Copy-Item (Join-Path $RepoRoot "web\backend\lambda_function_ebl.py") (Join-Path $PackageDir "lambda_function.py")
Copy-Item -Recurse (Join-Path $RepoRoot "rcs_ebl") (Join-Path $PackageDir "rcs_ebl")

# Matcher + rules only (no HOMBA ontology / cache).
Copy-Item (Join-Path $RepoRoot "rcs\rosetta_candidate_generator.py") (Join-Path $PackageDir "rcs\")
Copy-Item (Join-Path $RepoRoot "rcs\homba_token_rules.csv") (Join-Path $PackageDir "rcs\")
Copy-Item (Join-Path $RepoRoot "rcs\homba_alias_rules.csv") (Join-Path $PackageDir "rcs\")
Copy-Item (Join-Path $RepoRoot "rcs\homba_abbrev_rules.csv") (Join-Path $PackageDir "rcs\")
# Package marker so `import rcs...` works as a namespace package.
Set-Content -Path (Join-Path $PackageDir "rcs\__init__.py") -Value "" -Encoding utf8

Copy-Item (Join-Path $ReadyDir "bna_name_index.csv") (Join-Path $PackageDir "ebl_data\")
Copy-Item (Join-Path $ReadyDir "bna_name_candidates.csv") (Join-Path $PackageDir "ebl_data\")
Copy-Item (Join-Path $ReadyDir "bna_name_l2_candidates.csv") (Join-Path $PackageDir "ebl_data\")

Get-ChildItem -Path $PackageDir -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force
Get-ChildItem -Path $PackageDir -Recurse -Filter "*.pyc" | Remove-Item -Force

if (Test-Path $ZipPath) { Remove-Item -Force $ZipPath }
Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -Force
$sizeMb = [math]::Round((Get-Item $ZipPath).Length / 1MB, 2)
Write-Host "Built $ZipPath ($sizeMb MB)"
