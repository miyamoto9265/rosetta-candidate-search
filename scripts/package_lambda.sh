#!/usr/bin/env bash
# Build Lambda deployment zip from rcs/ (core) + web/backend/lambda_function.py (adapter).
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PACKAGE_DIR="$REPO_ROOT/dist/package"
ZIP_PATH="$REPO_ROOT/dist/lambda.zip"

rm -rf "$REPO_ROOT/dist"
mkdir -p "$PACKAGE_DIR"

cp "$REPO_ROOT/web/backend/lambda_function.py" "$PACKAGE_DIR/"
cp -r "$REPO_ROOT/rcs" "$PACKAGE_DIR/rcs"
rm -f "$PACKAGE_DIR/rcs/rcs_test_list.py" "$PACKAGE_DIR/rcs/rcs_test_interactive.py"
find "$PACKAGE_DIR/rcs" -type d -name __pycache__ -exec rm -rf {} +

(cd "$PACKAGE_DIR" && zip -r "$ZIP_PATH" .)
echo "Built $ZIP_PATH"
