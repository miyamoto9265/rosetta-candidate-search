"""AWS Lambda backend for RCS_EBL (literature name → BNA candidates).

Bundled data: rcs/ (matcher + rules), rcs_ebl/, ebl_data/ (rcs_ready tables).
No AI pipeline; independent from HOMBA rcs-api.
"""

from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from rcs.rosetta_candidate_generator import ENGINE_VERSION as RCS_ENGINE_VERSION  # noqa: E402
from rcs_ebl import ENGINE_VERSION  # noqa: E402
from rcs_ebl.ebl_candidate_generator import EblCandidateGenerator  # noqa: E402

logger = logging.getLogger(__name__)
if not logger.handlers:
    logging.basicConfig(level=logging.INFO)

GENERATOR: EblCandidateGenerator | None = None


def _data_dir() -> Path:
    override = os.environ.get("RCS_EBL_DATA_DIR")
    if override:
        return Path(override)
    bundled = _ROOT / "ebl_data"
    if bundled.is_dir():
        return bundled
    return _ROOT.parent / "ebl_for_rcs_v1.0_20260722" / "rcs_ready"


def _rules_dir() -> Path:
    bundled = _ROOT / "rcs"
    if (bundled / "homba_token_rules.csv").is_file():
        return bundled
    return _ROOT.parent / "rcs"


def get_generator() -> EblCandidateGenerator:
    global GENERATOR
    if GENERATOR is not None:
        return GENERATOR
    data = _data_dir()
    rules = _rules_dir()
    logger.info("Loading RCS_EBL from data=%s rules=%s", data, rules)
    GENERATOR = EblCandidateGenerator(
        rcs_ready_dir=data,
        token_rules_csv=rules / "homba_token_rules.csv",
        alias_rules_csv=rules / "homba_alias_rules.csv",
        abbrev_rules_csv=rules / "homba_abbrev_rules.csv",
        cache_dir=Path(os.environ.get("TMPDIR") or os.environ.get("TMP") or "/tmp") / "rcs_ebl",
    )
    return GENERATOR


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


def lambda_handler(event, context):
    method = (
        (event.get("requestContext") or {}).get("http", {}).get("method")
        or event.get("httpMethod")
        or "POST"
    )
    if method == "OPTIONS":
        return response(200, {"ok": True})

    try:
        payload = json.loads(event.get("body") or "{}")
        query = str(payload.get("query", "")).strip()
        if not query:
            return response(400, {"error": "query is required"})

        top_k = int(payload.get("top_k", 10))
        top_k = max(1, min(top_k, 30))
        level = str(payload.get("level", "l3")).strip().lower()
        if level not in ("l3", "l2"):
            level = "l3"
        name_top_k = int(payload.get("name_top_k", 5))
        name_top_k = max(1, min(name_top_k, 15))

        candidates = get_generator().generate(
            query, top_k=top_k, name_top_k=name_top_k, level=level
        )
        body: dict[str, object] = {
            "query": query,
            "context": str(payload.get("context", "")).strip(),
            "top_k": top_k,
            "level": level,
            "use_ai_preprocess": False,
            "use_ai_postprocess": False,
            "candidates": candidates,
            "meta": {
                "rcs_ebl_version": ENGINE_VERSION,
                "base_rcs_version": RCS_ENGINE_VERSION,
                "engine": "RCS_EBL",
            },
        }
        return response(200, body)
    except Exception as exc:  # noqa: BLE001
        logger.exception("RCS_EBL handler failed")
        return response(500, {"error": str(exc)})
