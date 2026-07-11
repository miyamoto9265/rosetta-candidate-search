"""AWS Lambda backend for ROSETTA Candidate Search.

The scoring engine lives in ``rcs/`` and is bundled into the deployment zip.
This module only handles cache/CSV loading, HTTP, and CORS.

Environment variables:
- HOMBA_BUCKET: S3 bucket for CSV fallback when cache is missing or invalid
- HOMBA_KEY: S3 key for HOMBA_v1_fixed.csv (default: HOMBA_v1_fixed.csv)
- TOKEN_RULES_KEY: S3 key for homba_token_rules.csv
- ALIAS_RULES_KEY: S3 key for homba_alias_rules.csv
- ABBREV_RULES_KEY: S3 key for homba_abbrev_rules.csv
- GENERATOR_CACHE_PATH: Optional override for generator_cache.pkl
- ALLOWED_ORIGIN: CORS origin, e.g. https://example.com or *
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from pathlib import Path

import boto3

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rcs.generator_cache import (  # noqa: E402
    GeneratorCacheError,
    default_cache_path,
    default_csv_paths,
    load_generator_cache,
)
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator  # noqa: E402

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

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


def _load_from_cache(cache_path: Path) -> RosettaCandidateGenerator | None:
    if not cache_path.is_file():
        return None
    started = time.perf_counter()
    try:
        generator = load_generator_cache(cache_path)
    except GeneratorCacheError as exc:
        logger.warning("Generator cache rejected: %s", exc)
        return None
    except Exception:
        logger.exception("Generator cache load failed")
        return None
    logger.info("Loaded generator cache from %s in %.3fs", cache_path, time.perf_counter() - started)
    return generator


def _load_from_bundled_csv() -> RosettaCandidateGenerator | None:
    paths = default_csv_paths(_ROOT / "rcs")
    if not all(path.is_file() for path in paths.values()):
        return None
    started = time.perf_counter()
    generator = RosettaCandidateGenerator(
        paths["homba"],
        token_rules_csv=paths["token_rules"],
        alias_rules_csv=paths["alias_rules"],
        abbrev_rules_csv=paths["abbrev_rules"],
    )
    logger.info("Built generator from bundled CSV in %.3fs", time.perf_counter() - started)
    return generator


def _load_from_s3_csv() -> RosettaCandidateGenerator:
    bucket = os.environ["HOMBA_BUCKET"]
    homba_key = os.environ.get("HOMBA_KEY", "HOMBA_v1_fixed.csv")
    token_rules_key = os.environ.get("TOKEN_RULES_KEY", "homba_token_rules.csv")
    alias_rules_key = os.environ.get("ALIAS_RULES_KEY", "homba_alias_rules.csv")
    abbrev_rules_key = os.environ.get("ABBREV_RULES_KEY", "homba_abbrev_rules.csv")
    started = time.perf_counter()
    homba_path = ensure_file_from_s3(bucket, homba_key, "HOMBA_v1_fixed.csv")
    token_rules_path = ensure_file_from_s3(bucket, token_rules_key, "homba_token_rules.csv")
    alias_rules_path = ensure_file_from_s3(bucket, alias_rules_key, "homba_alias_rules.csv")
    abbrev_rules_path = ensure_file_from_s3(bucket, abbrev_rules_key, "homba_abbrev_rules.csv")
    generator = RosettaCandidateGenerator(
        homba_path,
        token_rules_csv=token_rules_path,
        alias_rules_csv=alias_rules_path,
        abbrev_rules_csv=abbrev_rules_path,
    )
    logger.info("Built generator from S3 CSV in %.3fs", time.perf_counter() - started)
    return generator


def get_generator() -> RosettaCandidateGenerator:
    global GENERATOR
    if GENERATOR is not None:
        return GENERATOR

    cache_path = Path(os.environ.get("GENERATOR_CACHE_PATH", default_cache_path(_ROOT)))
    generator = _load_from_cache(cache_path)
    if generator is None:
        generator = _load_from_bundled_csv()
    if generator is None:
        generator = _load_from_s3_csv()

    GENERATOR = generator
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

        return response(
            200,
            {"query": query, "top_k": top_k, "dhba_filter": dhba_filter, "candidates": candidates},
        )
    except Exception as exc:
        return response(500, {"error": str(exc)})
