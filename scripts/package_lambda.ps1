# Build Lambda deployment zip shared by rcs-api and rcs-mcp:
# rcs/ (core) + web/backend adapters, plus rcs_ebl/ + EBL tables for the MCP BNA tool.
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PackageDir = Join-Path $RepoRoot "dist\package"
$ZipPath = Join-Path $RepoRoot "dist\lambda.zip"
$CachePath = Join-Path $RepoRoot "rcs\generator_cache.pkl"
$EblCachePath = Join-Path $RepoRoot "rcs_ebl\ebl_generator_cache.pkl"
$EblReadyDir = Join-Path $RepoRoot "ebl_for_rcs_v1.0_20260722\rcs_ready"

function Invoke-CacheBuild([string]$Script) {
    $DockerImage = "public.ecr.aws/lambda/python:3.14"
    $DockerArgs = @(
        "run", "--rm",
        "-v", "${RepoRoot}:/repo",
        "-w", "/repo",
        $DockerImage,
        "python", $Script
    )

    try {
        docker info *> $null
        Write-Host "Running $Script with Docker ($DockerImage) ..."
        & docker @DockerArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Docker cache build failed with exit code $LASTEXITCODE"
        }
        return
    } catch {
        Write-Warning "Docker unavailable or cache build failed; using local Python."
    }

    Write-Host "Running $Script with local Python ..."
    python (Join-Path $RepoRoot $Script)
    if ($LASTEXITCODE -ne 0) {
        throw "Local cache build failed with exit code $LASTEXITCODE"
    }
}

Invoke-CacheBuild "scripts/build_generator_cache.py"
Invoke-CacheBuild "scripts/build_ebl_generator_cache.py"

foreach ($path in @($CachePath, $EblCachePath)) {
    if (-not (Test-Path $path)) {
        throw "Missing generator cache: $path"
    }
}

if (Test-Path (Join-Path $RepoRoot "dist")) {
    Remove-Item -Recurse -Force (Join-Path $RepoRoot "dist")
}
New-Item -ItemType Directory -Path $PackageDir -Force | Out-Null

Copy-Item (Join-Path $RepoRoot "web\backend\lambda_function.py") $PackageDir
Copy-Item (Join-Path $RepoRoot "web\backend\ai_pipeline.py") $PackageDir
Copy-Item (Join-Path $RepoRoot "web\backend\mcp_function.py") $PackageDir
Copy-Item (Join-Path $RepoRoot "web\backend\lambda_function_ebl.py") $PackageDir
Copy-Item -Recurse (Join-Path $RepoRoot "rcs") (Join-Path $PackageDir "rcs")
Copy-Item -Recurse (Join-Path $RepoRoot "rcs_ebl") (Join-Path $PackageDir "rcs_ebl")
New-Item -ItemType Directory -Path (Join-Path $PackageDir "ebl_data") -Force | Out-Null
foreach ($name in @("bna_name_index.csv", "bna_name_candidates.csv", "bna_name_l2_candidates.csv")) {
    Copy-Item (Join-Path $EblReadyDir $name) (Join-Path $PackageDir "ebl_data\")
}

# CLI scripts and playground output are not needed in Lambda.
Remove-Item (Join-Path $PackageDir "rcs\rcs_test_list.py") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $PackageDir "rcs\rcs_test_interactive.py") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $PackageDir "rcs_ebl\local_server.py") -ErrorAction SilentlyContinue
Get-ChildItem -Path $PackageDir -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -Force
Write-Host "Built $ZipPath"
