#!/usr/bin/env bash
# Build Lambda zip for RCS_EBL (BNA lookup test API; the BNA side of SABRA).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE_DIR="$REPO_ROOT/dist/package_ebl"
ZIP_PATH="$REPO_ROOT/dist/lambda_ebl.zip"
READY_DIR="$REPO_ROOT/ebl_for_rcs_v1.0_20260722/rcs_ready"
EBL_CACHE_PATH="$REPO_ROOT/rcs_ebl/ebl_generator_cache.pkl"
DOCKER_IMAGE="public.ecr.aws/lambda/python:3.14"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"

if [[ ! -f "$READY_DIR/bna_name_candidates.csv" ]]; then
  echo "Missing EBL rcs_ready tables. Run: python scripts/build_rcs_bna_tables.py" >&2
  exit 1
fi

# RCS_USE_DOCKER=0 forces local Python even when Docker is available.
if [[ "${RCS_USE_DOCKER:-1}" != "0" ]] && command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
  echo "Running scripts/build_ebl_generator_cache.py with Docker ($DOCKER_IMAGE) ..."
  # The Lambda image's default entrypoint only accepts a handler name.
  docker run --rm \
    --entrypoint python \
    --user "$(id -u):$(id -g)" \
    -e PYTHONDONTWRITEBYTECODE=1 \
    -v "$REPO_ROOT:/repo" \
    -w /repo \
    "$DOCKER_IMAGE" \
    scripts/build_ebl_generator_cache.py
else
  echo "Running scripts/build_ebl_generator_cache.py with local Python ($PYTHON) ..."
  "$PYTHON" "$REPO_ROOT/scripts/build_ebl_generator_cache.py"
fi

if [[ ! -f "$EBL_CACHE_PATH" ]]; then
  echo "Missing EBL generator cache: $EBL_CACHE_PATH" >&2
  exit 1
fi

rm -rf "$PACKAGE_DIR" "$ZIP_PATH"
mkdir -p "$PACKAGE_DIR/ebl_data" "$PACKAGE_DIR/rcs"

cp "$REPO_ROOT/web/backend/lambda_function_ebl.py" "$PACKAGE_DIR/lambda_function.py"
# Includes rcs_ebl/ebl_generator_cache.pkl built above.
cp -r "$REPO_ROOT/rcs_ebl" "$PACKAGE_DIR/rcs_ebl"

# Matcher + rules only (no HOMBA ontology / cache).
cp "$REPO_ROOT/rcs/rosetta_candidate_generator.py" \
  "$REPO_ROOT/rcs/homba_token_rules.csv" \
  "$REPO_ROOT/rcs/homba_alias_rules.csv" \
  "$REPO_ROOT/rcs/homba_abbrev_rules.csv" \
  "$PACKAGE_DIR/rcs/"
# Package marker so `import rcs...` works.
: > "$PACKAGE_DIR/rcs/__init__.py"

cp "$READY_DIR/bna_name_index.csv" "$READY_DIR/bna_name_candidates.csv" \
  "$READY_DIR/bna_name_l2_candidates.csv" "$PACKAGE_DIR/ebl_data/"

find "$PACKAGE_DIR" -type d -name __pycache__ -exec rm -rf {} +
find "$PACKAGE_DIR" -type f -name '*.pyc' -delete

(cd "$PACKAGE_DIR" && zip -qr "$ZIP_PATH" .)
size_mb="$(awk -v b="$(wc -c < "$ZIP_PATH")" 'BEGIN { printf "%.2f", b / 1048576 }')"
echo "Built $ZIP_PATH ($size_mb MB)"
