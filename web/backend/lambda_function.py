"""AWS Lambda backend for ROSETTA Candidate Search.

The scoring engine lives in ``rcs/`` and is bundled into the deployment zip.
This module only handles S3 data loading, HTTP, and CORS.

Environment variables:
- HOMBA_BUCKET: S3 bucket for HOMBA_v1_fixed.csv and homba_*_rules.csv
- HOMBA_KEY: S3 key for HOMBA_v1_fixed.csv (default: HOMBA_v1_fixed.csv)
- TOKEN_RULES_KEY: S3 key for homba_token_rules.csv
- ALIAS_RULES_KEY: S3 key for homba_alias_rules.csv
- ABBREV_RULES_KEY: S3 key for homba_abbrev_rules.csv
- ALLOWED_ORIGIN: CORS origin, e.g. https://example.com or *
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import boto3

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rcs.review import add_review_flags
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator

S3 = boto3.client("s3")
GENERATOR: RosettaCandidateGenerator | None = None


def response(status_code: int, body: dict[str, object]) -> dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
            "Content-Type": "application/json; charset=utf-8",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def ensure_file_from_s3(bucket: str, key: str, local_name: str) -> Path:
    local_path = Path("/tmp") / local_name
    if not local_path.exists():
        S3.download_file(bucket, key, str(local_path))
    return local_path


def get_generator() -> RosettaCandidateGenerator:
    global GENERATOR
    if GENERATOR is not None:
        return GENERATOR

    bucket = os.environ["HOMBA_BUCKET"]
    homba_key = os.environ.get("HOMBA_KEY", "HOMBA_v1_fixed.csv")
    token_rules_key = os.environ.get("TOKEN_RULES_KEY", "homba_token_rules.csv")
    alias_rules_key = os.environ.get("ALIAS_RULES_KEY", "homba_alias_rules.csv")
    abbrev_rules_key = os.environ.get("ABBREV_RULES_KEY", "homba_abbrev_rules.csv")
    homba_path = ensure_file_from_s3(bucket, homba_key, "HOMBA_v1_fixed.csv")
    token_rules_path = ensure_file_from_s3(bucket, token_rules_key, "homba_token_rules.csv")
    alias_rules_path = ensure_file_from_s3(bucket, alias_rules_key, "homba_alias_rules.csv")
    abbrev_rules_path = ensure_file_from_s3(bucket, abbrev_rules_key, "homba_abbrev_rules.csv")
    GENERATOR = RosettaCandidateGenerator(
        homba_path,
        token_rules_csv=token_rules_path,
        alias_rules_csv=alias_rules_path,
        abbrev_rules_csv=abbrev_rules_path,
    )
    return GENERATOR


def lambda_handler(event, context):
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return response(200, {"ok": True})

    try:
        payload = json.loads(event.get("body") or "{}")
        query = str(payload.get("query", "")).strip()
        top_k = int(payload.get("top_k", 5))
        top_k = max(1, min(top_k, 20))
        dhba_filter = str(payload.get("dhba_filter", "both")).strip().lower()
        if dhba_filter not in ("both", "with", "without"):
            dhba_filter = "both"
        if not query:
            return response(400, {"error": "query is required"})

        candidates = get_generator().generate(query, top_k=top_k, dhba_filter=dhba_filter)
        add_review_flags(candidates)

        return response(
            200,
            {"query": query, "top_k": top_k, "dhba_filter": dhba_filter, "candidates": candidates},
        )
    except Exception as exc:
        return response(500, {"error": str(exc)})
