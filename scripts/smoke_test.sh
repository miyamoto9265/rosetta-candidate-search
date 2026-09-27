#!/usr/bin/env bash
# Smoke-test the public RCS endpoints (no credentials needed).
#   scripts/smoke_test.sh
# Override targets with RCS_API_BASE / RCS_WEB_BASE. When GITHUB_STEP_SUMMARY is set,
# a result table is appended to the job summary. Response bodies are never printed.
set -uo pipefail

API_BASE="${RCS_API_BASE:-https://hg2se72l61.execute-api.ap-northeast-1.amazonaws.com}"
WEB_BASE="${RCS_WEB_BASE:-https://rcs.cobrac.site}"
PYTHON="${PYTHON:-$(command -v python3 || command -v python)}"
BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

results=()
failed=0

record() {
  local label="$1" ok="$2" detail="$3"
  if [[ "$ok" == "1" ]]; then
    echo "PASS $label ($detail)"
    results+=("| $label | PASS | $detail |")
  else
    echo "FAIL $label ($detail)"
    results+=("| $label | **FAIL** | $detail |")
    failed=1
  fi
}

# request <method> <url> <json-body or ""> [extra curl args...] -> prints HTTP status, body in $BODY_FILE.
# Retries 5xx / network errors so a cold start right after a deploy does not fail the check.
request() {
  local method="$1" url="$2" data="$3"
  shift 3
  local status=000 attempt
  for attempt in 1 2 3 4; do
    if [[ -n "$data" ]]; then
      status="$(curl -sS -m 35 -o "$BODY_FILE" -w '%{http_code}' -X "$method" "$url" \
        -H 'Content-Type: application/json' -d "$data" "$@" 2>/dev/null)" || status=000
    else
      status="$(curl -sS -m 35 -o "$BODY_FILE" -w '%{http_code}' -X "$method" "$url" "$@" 2>/dev/null)" || status=000
    fi
    [[ "$status" =~ ^(000|5..)$ ]] || break
    sleep $((attempt * 5))
  done
  echo "$status"
}

# body_check <python-expression over `d` (parsed JSON)> -> prints the expression's value, or empty.
body_check() {
  "$PYTHON" - "$1" "$BODY_FILE" <<'PY' 2>/dev/null
import json, sys
expr, path = sys.argv[1], sys.argv[2]
d = json.load(open(path, encoding="utf-8"))
print(eval(expr, {}, {"d": d}))
PY
}

status="$(request POST "$API_BASE/candidates" \
  '{"query":"Pulvinar nucleus","top_k":3,"use_ai_preprocess":false,"use_ai_postprocess":false}')"
top="$(body_check '(d.get("candidates") or [{}])[0].get("homba_id")')"
[[ "$status" == 200 && "$top" == "HOMBA:10409" ]] && ok=1 || ok=0
record "POST /candidates" "$ok" "HTTP $status, top=${top:-none}"

status="$(request POST "$API_BASE/candidates-ebl" '{"query":"left DLPFC","top_k":3}')"
abbrs="$(body_check '",".join(str(c.get("bna_area_abbr")) for c in d.get("candidates") or [])')"
[[ "$status" == 200 && ",$abbrs," == *",A8vl,"* ]] && ok=1 || ok=0
record "POST /candidates-ebl" "$ok" "HTTP $status, candidates=${abbrs:-none}"

mcp_body='{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
status="$(request POST "$API_BASE/mcp" "$mcp_body")"
[[ "$status" == 401 ]] && ok=1 || ok=0
record "POST /mcp without token" "$ok" "HTTP $status (expect 401)"

status="$(request POST "$API_BASE/mcp" "$mcp_body" -H 'Authorization: Bearer invalid-smoke-test-token')"
[[ "$status" == 401 ]] && ok=1 || ok=0
record "POST /mcp with invalid token" "$ok" "HTTP $status (expect 401)"

for path in / /ebl/index.html /config.js; do
  status="$(request GET "$WEB_BASE$path" "")"
  [[ "$status" == 200 ]] && ok=1 || ok=0
  record "GET $path (web)" "$ok" "HTTP $status"
done

if [[ -n "${GITHUB_STEP_SUMMARY:-}" ]]; then
  {
    echo "### Smoke test"
    echo
    echo "| Check | Result | Detail |"
    echo "| ----- | ------ | ------ |"
    printf '%s\n' "${results[@]}"
  } >> "$GITHUB_STEP_SUMMARY"
fi

exit "$failed"
