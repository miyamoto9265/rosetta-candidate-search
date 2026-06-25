#!/usr/bin/env bash
# Build Lambda deployment zip from rcs/ (core) + web/backend/lambda_function.py (adapter).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE_DIR="$REPO_ROOT/dist/package"
ZIP_PATH="$REPO_ROOT/dist/lambda.zip"
CACHE_PATH="$REPO_ROOT/rcs/generator_cache.pkl"
DOCKER_IMAGE="public.ecr.aws/lambda/python:3.14"

build_generator_cache() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "Building generator cache with Docker ($DOCKER_IMAGE) ..."
    docker run --rm \
      -v "$REPO_ROOT:/repo" \
      -w /repo \
      "$DOCKER_IMAGE" \
      python scripts/build_generator_cache.py
  else
    echo "Building generator cache with local Python ..."
    python "$REPO_ROOT/scripts/build_generator_cache.py"
  fi
}

build_generator_cache

if [[ ! -f "$CACHE_PATH" ]]; then
  echo "Missing generator cache: $CACHE_PATH" >&2
  exit 1
fi

rm -rf "$REPO_ROOT/dist"
mkdir -p "$PACKAGE_DIR"

cp "$REPO_ROOT/web/backend/lambda_function.py" "$PACKAGE_DIR/"
cp -r "$REPO_ROOT/rcs" "$PACKAGE_DIR/rcs"
rm -f "$PACKAGE_DIR/rcs/rcs_test_list.py" "$PACKAGE_DIR/rcs/rcs_test_interactive.py"
find "$PACKAGE_DIR/rcs" -type d -name __pycache__ -exec rm -rf {} +

(cd "$PACKAGE_DIR" && zip -r "$ZIP_PATH" .)
echo "Built $ZIP_PATH"
