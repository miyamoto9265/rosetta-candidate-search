#!/usr/bin/env bash
# Build Lambda deployment zip shared by rcs-api and rcs-mcp:
# rcs/ (core) + web/backend adapters, plus rcs_ebl/ + EBL tables for the MCP BNA tool.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE_DIR="$REPO_ROOT/dist/package"
ZIP_PATH="$REPO_ROOT/dist/lambda.zip"
CACHE_PATH="$REPO_ROOT/rcs/generator_cache.pkl"
EBL_CACHE_PATH="$REPO_ROOT/rcs_ebl/ebl_generator_cache.pkl"
EBL_READY_DIR="$REPO_ROOT/ebl_for_rcs_v1.0_20260722/rcs_ready"
DOCKER_IMAGE="public.ecr.aws/lambda/python:3.14"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"

# RCS_USE_DOCKER=0 forces local Python even when Docker is available.
run_cache_build() {
  local script="$1"
  if [[ "${RCS_USE_DOCKER:-1}" != "0" ]] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "Running $script with Docker ($DOCKER_IMAGE) ..."
    # The Lambda image's default entrypoint only accepts a handler name.
    docker run --rm \
      --entrypoint python \
      --user "$(id -u):$(id -g)" \
      -e PYTHONDONTWRITEBYTECODE=1 \
      -v "$REPO_ROOT:/repo" \
      -w /repo \
      "$DOCKER_IMAGE" \
      "$script"
  else
    echo "Running $script with local Python ($PYTHON) ..."
    "$PYTHON" "$REPO_ROOT/$script"
  fi
}

run_cache_build scripts/build_generator_cache.py
run_cache_build scripts/build_ebl_generator_cache.py

for path in "$CACHE_PATH" "$EBL_CACHE_PATH"; do
  if [[ ! -f "$path" ]]; then
    echo "Missing generator cache: $path" >&2
    exit 1
  fi
done

rm -rf "$PACKAGE_DIR" "$ZIP_PATH"
mkdir -p "$PACKAGE_DIR/ebl_data"

cp "$REPO_ROOT/web/backend/lambda_function.py" "$PACKAGE_DIR/"
cp "$REPO_ROOT/web/backend/ai_pipeline.py" "$PACKAGE_DIR/"
cp "$REPO_ROOT/web/backend/mcp_function.py" "$PACKAGE_DIR/"
cp "$REPO_ROOT/web/backend/lambda_function_ebl.py" "$PACKAGE_DIR/"
cp -r "$REPO_ROOT/rcs" "$PACKAGE_DIR/rcs"
cp -r "$REPO_ROOT/rcs_ebl" "$PACKAGE_DIR/rcs_ebl"
cp "$EBL_READY_DIR"/bna_name_index.csv "$EBL_READY_DIR"/bna_name_candidates.csv \
  "$EBL_READY_DIR"/bna_name_l2_candidates.csv "$PACKAGE_DIR/ebl_data/"
rm -f "$PACKAGE_DIR/rcs/rcs_test_list.py" "$PACKAGE_DIR/rcs/rcs_test_interactive.py" \
  "$PACKAGE_DIR/rcs_ebl/local_server.py"
find "$PACKAGE_DIR" -type d -name __pycache__ -exec rm -rf {} +

(cd "$PACKAGE_DIR" && zip -qr "$ZIP_PATH" .)
echo "Built $ZIP_PATH"
