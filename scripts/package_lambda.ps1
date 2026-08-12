# Build Lambda deployment zip from rcs/ (core) + web/backend/lambda_function.py (adapter).
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$PackageDir = Join-Path $RepoRoot "dist\package"
$ZipPath = Join-Path $RepoRoot "dist\lambda.zip"
$CachePath = Join-Path $RepoRoot "rcs\generator_cache.pkl"

function Invoke-GeneratorCacheBuild {
    $DockerImage = "public.ecr.aws/lambda/python:3.14"
    $DockerArgs = @(
        "run", "--rm",
        "-v", "${RepoRoot}:/repo",
        "-w", "/repo",
        $DockerImage,
        "python", "scripts/build_generator_cache.py"
    )

    try {
        docker info *> $null
        Write-Host "Building generator cache with Docker ($DockerImage) ..."
        & docker @DockerArgs
        if ($LASTEXITCODE -ne 0) {
            throw "Docker cache build failed with exit code $LASTEXITCODE"
        }
        return
    } catch {
        Write-Warning "Docker unavailable or cache build failed; using local Python."
    }

    Write-Host "Building generator cache with local Python ..."
    python (Join-Path $RepoRoot "scripts\build_generator_cache.py")
    if ($LASTEXITCODE -ne 0) {
        throw "Local cache build failed with exit code $LASTEXITCODE"
    }
}

Invoke-GeneratorCacheBuild

if (-not (Test-Path $CachePath)) {
    throw "Missing generator cache: $CachePath"
}

if (Test-Path (Join-Path $RepoRoot "dist")) {
    Remove-Item -Recurse -Force (Join-Path $RepoRoot "dist")
}
New-Item -ItemType Directory -Path $PackageDir -Force | Out-Null

Copy-Item (Join-Path $RepoRoot "web\backend\lambda_function.py") $PackageDir
Copy-Item (Join-Path $RepoRoot "web\backend\ai_pipeline.py") $PackageDir
Copy-Item -Recurse (Join-Path $RepoRoot "rcs") (Join-Path $PackageDir "rcs")

# CLI scripts and playground output are not needed in Lambda.
Remove-Item (Join-Path $PackageDir "rcs\rcs_test_list.py") -ErrorAction SilentlyContinue
Remove-Item (Join-Path $PackageDir "rcs\rcs_test_interactive.py") -ErrorAction SilentlyContinue
Get-ChildItem -Path (Join-Path $PackageDir "rcs") -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

Compress-Archive -Path (Join-Path $PackageDir "*") -DestinationPath $ZipPath -Force
Write-Host "Built $ZipPath"
