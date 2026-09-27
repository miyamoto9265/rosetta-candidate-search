#!/usr/bin/env bash
# Update one Lambda function's code and wait until it is active.
#   scripts/deploy_lambda_code.sh <function-name> <zip-path>
#   scripts/deploy_lambda_code.sh --check <function-name>   # only the environment check
#
# Lambda API responses (UpdateFunctionCode / GetFunctionConfiguration) contain the
# function's environment variables, and this repository's Actions logs are public.
# Never print a full response here and never enable `set -x`: only the fields picked
# with --query below may reach the log.
set -euo pipefail

CHECK_ONLY=0
if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=1
  shift
fi
if [[ ( $CHECK_ONLY == 1 && $# -ne 1 ) || ( $CHECK_ONLY == 0 && $# -ne 2 ) ]]; then
  echo "usage: $0 <function-name> <zip-path> | $0 --check <function-name>" >&2
  exit 2
fi
FUNCTION="$1"
ZIP="${2:-}"
export AWS_PAGER=""

# Secrets must live in Secrets Manager, not in Lambda environment variables.
FORBIDDEN_ENV_KEYS=(DEEPSEEK_API_KEY MCP_BEARER_TOKENS)
# shellcheck disable=SC2016  # backticks are a JMESPath literal
keys="$(aws lambda get-function-configuration --function-name "$FUNCTION" \
  --query 'keys(Environment.Variables || `{}`)' --output text)"
for key in "${FORBIDDEN_ENV_KEYS[@]}"; do
  if tr -s '\t ' '\n' <<<"$keys" | grep -qx "$key"; then
    echo "::error::$FUNCTION has $key in its environment variables. Move it to Secrets Manager before deploying from CI." >&2
    exit 1
  fi
done
if [[ $CHECK_ONLY == 1 ]]; then
  echo "Checked $FUNCTION: no plaintext secrets in environment variables"
  exit 0
fi

expected_sha="$(openssl dgst -sha256 -binary "$ZIP" | base64)"

aws lambda update-function-code --function-name "$FUNCTION" --zip-file "fileb://$ZIP" \
  --query 'LastUpdateStatus' --output text > /dev/null
aws lambda wait function-updated-v2 --function-name "$FUNCTION"

read -r status code_sha < <(aws lambda get-function-configuration --function-name "$FUNCTION" \
  --query '[LastUpdateStatus, CodeSha256]' --output text)
if [[ "$status" != "Successful" || "$code_sha" != "$expected_sha" ]]; then
  echo "::error::$FUNCTION update did not complete (LastUpdateStatus=$status, code matches zip: $([[ "$code_sha" == "$expected_sha" ]] && echo yes || echo no))" >&2
  exit 1
fi
echo "Updated $FUNCTION (CodeSha256=$code_sha)"
