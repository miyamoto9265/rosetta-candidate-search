#!/usr/bin/env bash
# Decide which RCS components to deploy and print `name=true|false` lines
# (lambda: rcs-api + rcs-mcp, ebl: rcs-ebl-api, data: CSVs in the data bucket, frontend: web/frontend).
#   scripts/plan_deploy.sh <before-sha> <after-sha>   # from the files changed between two commits
#   scripts/plan_deploy.sh --target <all|lambda|ebl|data|frontend|smoke>
# An unknown or all-zero <before-sha> (new branch, force push) selects everything.
set -euo pipefail

COMPONENTS=(lambda ebl data frontend)
declare -A PATTERNS=(
  [lambda]='^(rcs/|rcs_ebl/|web/backend/|ebl_for_rcs_v1\.0_20260722/rcs_ready/|scripts/(package_lambda\.sh|build_generator_cache\.py|build_ebl_generator_cache\.py)$)'
  [ebl]='^(rcs/rosetta_candidate_generator\.py|rcs/homba_(token|alias|abbrev)_rules\.csv|rcs_ebl/|web/backend/lambda_function_ebl\.py|ebl_for_rcs_v1\.0_20260722/rcs_ready/|scripts/(package_lambda_ebl\.sh|build_ebl_generator_cache\.py)$)'
  [data]='^rcs/(HOMBA_v1_fixed|homba_token_rules|homba_alias_rules|homba_abbrev_rules)\.csv$'
  [frontend]='^web/frontend/'
)

emit_all() {
  local value="$1" c
  for c in "${COMPONENTS[@]}"; do echo "$c=$value"; done
}

if [[ "${1:-}" == "--target" ]]; then
  target="${2:-all}"
  case "$target" in
    all) emit_all true ;;
    smoke) emit_all false ;;
    lambda|ebl|data|frontend)
      for c in "${COMPONENTS[@]}"; do echo "$c=$([[ $c == "$target" ]] && echo true || echo false)"; done ;;
    *) echo "unknown target: $target" >&2; exit 2 ;;
  esac
  exit 0
fi

if [[ $# -ne 2 ]]; then
  echo "usage: $0 <before-sha> <after-sha> | $0 --target <name>" >&2
  exit 2
fi
before="$1"
after="$2"

if [[ "$before" =~ ^0+$ ]] || ! git cat-file -e "${before}^{commit}" 2>/dev/null; then
  emit_all true
  exit 0
fi

changed="$(git diff --name-only "$before" "$after")"
for c in "${COMPONENTS[@]}"; do
  if grep -qE "${PATTERNS[$c]}" <<<"$changed"; then echo "$c=true"; else echo "$c=false"; fi
done
