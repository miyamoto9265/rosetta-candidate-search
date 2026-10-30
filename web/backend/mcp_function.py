"""Remote MCP server (Streamable HTTP, stateless) for ROSETTA Candidate Search.

Deployed as Lambda ``rcs-mcp`` behind API Gateway ``ANY /mcp``. It shares the
deployment zip with ``rcs-api`` and reuses the RCS (HOMBA) and RCS_EBL (BNA)
pipelines, so tool results match ``POST /candidates`` and ``POST /candidates-ebl``.
Together the two cover the SABRA mixed atlas (see ``rcs/sabra.py``). ``map_coordinates`` is CBM
(Coordinate-to-Brain Mapper, ``rcs/cbm.py``): MNI / Talairach coordinates -> SABRA regions.

Only the subset of MCP needed for tools is implemented: every POST carries one
JSON-RPC message and is answered with a single ``application/json`` body. No
session id is issued and no SSE stream is offered (GET returns 405), which the
spec permits for stateless servers.

Environment variables (in addition to those read by ``lambda_function``):
- MCP_BEARER_SECRET_ID: Secrets Manager secret holding comma-separated accepted
  bearer tokens (re-read every MCP_BEARER_SECRET_TTL_SEC, default 300).
- MCP_BEARER_TOKENS: optional extra comma-separated tokens (local testing).
Neither set / both empty = reject all.
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import time
from collections import defaultdict

import lambda_function
from rcs import cbm, sabra
from rcs.rosetta_candidate_generator import ENGINE_VERSION

logger = logging.getLogger(__name__)

SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2025-03-26", "2024-11-05")
SERVER_INFO = {"name": "rcs", "title": "ROSETTA Candidate Search (SABRA: HOMBA/DHBA + BNA)", "version": ENGINE_VERSION}

SABRA_SUMMARY = (
    "SABRA (Standardized Ontology of Anatomies for Brain Reference Architecture) is a mixed "
    "atlas of region names: BNA (Brainnetome) for the neocortex only (cortical labels 1-210 "
    "except A28/34 entorhinal and TI) plus DHBA for every other region: subcortical nuclei "
    "(amygdala, basal ganglia, thalamus, ...), hippocampal formation and other allocortex, "
    "hypothalamus, brainstem, cerebellum, ... (boundary of 2026-10-04; BNA's subcortical labels "
    "211-246 are no longer SABRA regions). DHBA terms are the HOMBA terms that have a DHBA name. "
    "SABRA has no IDs of its own: a SABRA region is either a neocortical BNA area or a DHBA term."
)

INSTRUCTIONS = (
    SABRA_SUMMARY
    + " Tools: search_homba_candidates resolves a name to HOMBA (and DHBA) terms; every HOMBA "
    "result carries `sabra.atlas` telling whether SABRA represents that region with BNA or DHBA. "
    "search_bna_candidates resolves a (possibly vague) cortical name to a probability "
    "distribution over BNA areas learned from literature coordinates; each result's `sabra.atlas` "
    "is BNA only for neocortical areas. "
    "To express a region in SABRA: if `sabra.atlas` is DHBA use `sabra.dhba_name`; if it is BNA, "
    "use search_bna_candidates and pick BNA area(s). get_homba_term shows HOMBA ancestors/children; "
    "get_sabra_definition returns the full definition. "
    "map_coordinates (CBM) maps MNI or Talairach coordinates reported in a paper to the SABRA "
    "region at each point (BNA area or DHBA term, with the UC anchor), the regions around it, and "
    "the nearest gray matter when the point falls in white matter or outside the atlas. "
    "HOMBA data: research / non-commercial use only; cite the Allen Institute."
)

_ANNOTATIONS = {"readOnlyHint": True, "idempotentHint": True, "openWorldHint": False}

_POINT_SCHEMA = {
    "type": "object",
    "properties": {
        "x": {"type": "number"},
        "y": {"type": "number"},
        "z": {"type": "number"},
        "space": {"type": "string", "enum": [cbm.SPACE_MNI, cbm.SPACE_TAL], "description": "Overrides the call's `space` for this point."},
        "label": {"type": "string", "description": "The paper's name for the region (echoed back)."},
        "stat": {"type": "number", "description": "Peak statistic (Z / T), used for max_stat in `regions`."},
    },
    "required": ["x", "y", "z"],
    "additionalProperties": False,
}

TOOLS = [
    {
        "name": "search_homba_candidates",
        "title": "Search HOMBA candidates (SABRA DHBA side)",
        "description": (
            "Resolve a brain region name to HOMBA ontology candidates (RCS). "
            "Example: 'right NAc Drd1 neurons' -> nucleus accumbens (HOMBA:10339). "
            "Returns `candidates` (raw RCS ranking with score 0-1) and, when AI is enabled, "
            "`preprocess` (cleaned query) and `ai.results` (0-4 validated matches, best first, "
            "each with relation '= same / < query narrower / > query broader). An empty `ai.results` "
            "means no candidate is a valid match. Each candidate and AI result has `sabra`: "
            "{atlas: 'DHBA', dhba_name, dhba_acronym, dhba_exact} or {atlas: 'BNA', bna_territory} — "
            "for atlas BNA, use search_bna_candidates to get the SABRA (BNA) name. "
            "Typical latency 2-10 s with AI, <1 s without."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Brain region name to look up (English; abbreviations OK).",
                },
                "context": {
                    "type": "string",
                    "description": "Optional free text that helps disambiguation, e.g. species, "
                    "paper title, or the function being studied.",
                },
                "top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "default": 5,
                    "description": "Number of raw candidates to return.",
                },
                "dhba_filter": {
                    "type": "string",
                    "enum": ["both", "with", "without"],
                    "default": "both",
                    "description": "Restrict to terms with/without a DHBA name. Keep 'both' for "
                    "SABRA work so BNA-territory regions are still recognised.",
                },
                "use_ai": {
                    "type": "boolean",
                    "default": True,
                    "description": "Enable LLM query cleaning and candidate adjudication.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": _ANNOTATIONS,
    },
    {
        "name": "search_bna_candidates",
        "title": "Search BNA candidates (SABRA BNA side)",
        "description": (
            "Resolve a neocortical region name to Brainnetome Atlas (BNA) areas "
            "(RCS_EBL). The name is matched against ~3,700 literature region names, then expanded "
            "to the BNA areas where papers reported coordinates for that name, so results are a "
            "probability distribution (`p_raw`), not a single definitive label. "
            "Example: 'DLPFC' -> A9/46d, A9/46v, A8vl ... (MFG). `score` = name match x p_raw. "
            "`level` 'l3' returns BNA areas (e.g. A9/46d), 'l2' returns gyri (e.g. MFG; more reliable "
            "when one label is needed). Laterality words in the query (left/right/bilateral) select "
            "`bna_label_id`; otherwise use bna_label_id_l / _r. Reliability: `k_papers` (support) and "
            "`eff_n` (1 = peaked, larger = diffuse). `sabra`: {atlas: 'BNA', sabra_unit: true} for "
            "neocortical areas; subcortical, hippocampal and other non-neocortical areas have "
            "{atlas: 'DHBA', sabra_unit: false, dhba_homba_id} and are not SABRA regions: name them "
            "with search_homba_candidates instead (whole hippocampus: HiF; a named field such as CA1, "
            "CA3, DG or subiculum: that DHBA term). The l2 group PhG mixes neocortical and DHBA areas "
            "and is not a SABRA unit as a whole (sabra_unit: false): name its subregions. "
            "No AI; typical latency <2 s."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Region name as used in literature, e.g. 'left DLPFC', 'FEF'. "
                    "Drop gene / cell-type / method words.",
                },
                "top_k": {"type": "integer", "minimum": 1, "maximum": 30, "default": 10},
                "level": {"type": "string", "enum": ["l3", "l2"], "default": "l3"},
                "name_top_k": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 15,
                    "default": 5,
                    "description": "How many matched literature names to merge (exact matches win).",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
        "annotations": _ANNOTATIONS,
    },
    {
        "name": "get_homba_term",
        "title": "Get HOMBA term",
        "description": (
            "Look up one HOMBA term by ID and return its names, DHBA mapping, SABRA classification "
            "(`sabra`), ancestor chain (root first) and direct children. Accepts 'HOMBA:10339' or '10339'."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "homba_id": {"type": "string", "description": "HOMBA ID, e.g. HOMBA:10339."},
            },
            "required": ["homba_id"],
            "additionalProperties": False,
        },
        "annotations": _ANNOTATIONS,
    },
    {
        "name": "get_sabra_definition",
        "title": "Get SABRA definition",
        "description": (
            "Return the SABRA atlas definition: which regions use BNA vs DHBA, BNA label ranges, and "
            "the HOMBA subtrees treated as BNA territory."
        ),
        "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        "annotations": _ANNOTATIONS,
    },
    {
        "name": "map_coordinates",
        "title": "Map coordinates to SABRA (CBM)",
        "description": (
            "CBM (Coordinate-to-Brain Mapper): map stereotaxic coordinates reported in a paper "
            "(peak / focus coordinates in mm, e.g. from a results table) to SABRA regions using the "
            "SABRA volume (MNI152, 0.5 mm; BNA for neocortical gray matter, DHBA for everything else). "
            "Talairach points are converted to MNI first (Lancaster by default). Per point: `status` "
            "(gray_matter / white_matter / ventricle / cortex_outside_bna = DHBA gyrus band next to BNA "
            "areas / other / unassigned = no label, e.g. outside the brain / out_of_bounds), `region` at "
            "the point with `anchor` (UC anchor: BNA:<l>-<r> for a neocortical area, HOMBA:<id> for a "
            "DHBA gray-matter term; null for white matter etc.) and `sabra`, `overlap` (share of each "
            "region in a sphere of radius_mm; how cleanly the point sits in its region) and, when the "
            "point is not in gray matter, `nearest_gray_matter` within search_mm. `regions` groups the "
            "gray-matter points by anchor (peak_count, max_stat). Coordinates only locate the reported "
            "peak: name the population the paper describes, and prefer the paper's own region name "
            "(search_homba_candidates / search_bna_candidates) when the two disagree. Human brains only. "
            "No AI; typical latency <1 s."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "points": {"type": "array", "items": _POINT_SCHEMA, "minItems": 1, "maxItems": 100},
                "space": {
                    "type": "string",
                    "enum": [cbm.SPACE_MNI, cbm.SPACE_TAL],
                    "default": cbm.SPACE_MNI,
                    "description": "Coordinate space the paper reports. Use TAL only when the paper says Talairach.",
                },
                "tal_transform": {
                    "type": "string",
                    "enum": [cbm.TAL_LANCASTER, cbm.TAL_BRETT],
                    "default": cbm.TAL_LANCASTER,
                    "description": "TAL -> MNI transform; brett only when the paper converted MNI to TAL with Brett's mni2tal.",
                },
                "radius_mm": {"type": "number", "minimum": 0, "maximum": cbm.MAX_RADIUS_MM, "default": cbm.DEFAULT_RADIUS_MM},
                "search_mm": {"type": "number", "minimum": 0, "maximum": cbm.MAX_SEARCH_MM, "default": cbm.DEFAULT_SEARCH_MM},
            },
            "required": ["points"],
            "additionalProperties": False,
        },
        "annotations": _ANNOTATIONS,
    },
]

_CBM_ATLAS: cbm.CbmAtlas | None = None

# Fields of RCS_EBL candidates that only exist for the HOMBA-shaped web UI.
_EBL_UI_ALIAS_FIELDS = ("homba_id", "name", "acronym", "dhba_name", "dhba_acronym")

_CHILDREN: dict[str, list[int]] | None = None


class ToolInputError(ValueError):
    pass


def _http(status: int, body: object | None = None, headers: dict[str, str] | None = None) -> dict:
    out: dict[str, object] = {"statusCode": status, "headers": dict(headers or {})}
    if body is not None:
        out["headers"]["Content-Type"] = "application/json"  # type: ignore[index]
        out["body"] = json.dumps(body, ensure_ascii=False)
    else:
        out["body"] = ""
    return out


def _rpc_result(msg_id: object, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _rpc_error(msg_id: object, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


_SECRET_TOKENS: list[str] = []
_SECRET_FETCHED_AT: float | None = None


def _split_tokens(value: str) -> list[str]:
    return [t.strip() for t in value.split(",") if t.strip()]


def _accepted_tokens() -> list[str]:
    global _SECRET_TOKENS, _SECRET_FETCHED_AT
    secret_id = os.environ.get("MCP_BEARER_SECRET_ID", "").strip()
    ttl = float(os.environ.get("MCP_BEARER_SECRET_TTL_SEC", "300"))
    if secret_id and (_SECRET_FETCHED_AT is None or time.monotonic() - _SECRET_FETCHED_AT > ttl):
        try:
            import boto3

            value = boto3.client("secretsmanager").get_secret_value(SecretId=secret_id)["SecretString"]
            _SECRET_TOKENS = _split_tokens(value)
            _SECRET_FETCHED_AT = time.monotonic()
        except Exception:
            # Keep the last good tokens; retry on the next request.
            logger.exception("Failed to read MCP bearer secret %s", secret_id)
    return _SECRET_TOKENS + _split_tokens(os.environ.get("MCP_BEARER_TOKENS", ""))


def _authorized(headers: dict[str, str]) -> bool:
    tokens = _accepted_tokens()
    auth = headers.get("authorization", "")
    if not tokens or not auth.lower().startswith("bearer "):
        return False
    presented = auth[7:].strip().encode()
    return any(hmac.compare_digest(presented, t.encode()) for t in tokens)


def _term_summary(term) -> dict[str, object]:
    return {
        "homba_id": term.homba_id,
        "name": term.name,
        "acronym": term.acronym,
        "dhba_name": term.dhba_name,
        "dhba_acronym": term.dhba_acronym,
    }


def _children_index() -> dict[str, list[int]]:
    global _CHILDREN
    if _CHILDREN is None:
        index: dict[str, list[int]] = defaultdict(list)
        for i, term in enumerate(lambda_function.get_generator().terms):
            if term.parent_id:
                index[term.parent_id].append(i)
        _CHILDREN = index
    return _CHILDREN


def _annotate_sabra(items: object) -> None:
    if not isinstance(items, list):
        return
    gen = lambda_function.get_generator()
    for item in items:
        if isinstance(item, dict) and item.get("homba_id"):
            item["sabra"] = sabra.sabra_for_homba_term(gen, str(item["homba_id"]))


def _tool_search_homba(args: dict) -> dict:
    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolInputError("query is required")
    use_ai = lambda_function._bool(args, "use_ai", True)
    params = lambda_function.normalize_search_params(
        {
            "query": query,
            "context": args.get("context", ""),
            "top_k": args.get("top_k", 5),
            "dhba_filter": args.get("dhba_filter", "both"),
            "use_ai_preprocess": use_ai,
            "use_ai_postprocess": use_ai,
        }
    )
    body = lambda_function.run_search(**params)  # type: ignore[arg-type]
    _annotate_sabra(body.get("candidates"))
    ai = body.get("ai")
    if isinstance(ai, dict):
        _annotate_sabra(ai.get("results"))
    return body


def _tool_search_bna(args: dict) -> dict:
    import lambda_function_ebl

    query = str(args.get("query", "")).strip()
    if not query:
        raise ToolInputError("query is required")
    params = lambda_function_ebl.normalize_search_params(
        {
            "query": query,
            "top_k": args.get("top_k", 10),
            "level": args.get("level", "l3"),
            "name_top_k": args.get("name_top_k", 5),
        }
    )
    body = lambda_function_ebl.run_search(**params)  # type: ignore[arg-type]
    body.pop("use_ai_preprocess", None)
    body.pop("use_ai_postprocess", None)
    body.pop("context", None)
    for cand in body.get("candidates") or []:
        for field in _EBL_UI_ALIAS_FIELDS:
            cand.pop(field, None)
        cand["sabra"] = sabra.sabra_for_bna_area(
            str(cand.get("bna_l2_abbr") or ""),
            str(cand.get("bna_label_id_l") or ""),
            str(cand.get("bna_label_id_r") or ""),
        )
    return body


def _tool_get_term(args: dict) -> dict:
    raw = str(args.get("homba_id", "")).strip()
    if not raw:
        raise ToolInputError("homba_id is required")
    homba_id = raw if raw.upper().startswith("HOMBA:") else f"HOMBA:{raw}"
    homba_id = "HOMBA:" + homba_id.split(":", 1)[1].strip()

    gen = lambda_function.get_generator()
    idx = gen.term_index_by_id.get(homba_id)
    if idx is None:
        raise ToolInputError(f"unknown HOMBA ID: {raw}")
    term = gen.terms[idx]

    ancestors: list[dict[str, object]] = []
    seen = {term.homba_id}
    parent_id = term.parent_id
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        pidx = gen.term_index_by_id.get(parent_id)
        if pidx is None:
            break
        parent = gen.terms[pidx]
        ancestors.append(_term_summary(parent))
        parent_id = parent.parent_id
    ancestors.reverse()

    children = [_term_summary(gen.terms[i]) for i in _children_index().get(term.homba_id, [])]
    return {
        **_term_summary(term),
        "parent_id": term.parent_id,
        "depth": term.depth,
        "graph_order": term.graph_order,
        "sabra": sabra.sabra_for_homba_term(gen, term.homba_id),
        "ancestors": ancestors,
        "children": children,
        "meta": {"rcs_version": ENGINE_VERSION},
    }


def _tool_sabra_definition(args: dict) -> dict:
    return {
        "name": sabra.SABRA_NAME,
        "full_name": sabra.SABRA_FULL_NAME,
        "boundary_version": sabra.SABRA_BOUNDARY_VERSION,
        "summary": SABRA_SUMMARY,
        "atlases": {
            sabra.ATLAS_BNA: {
                "scope": "neocortex only",
                "label_count": sabra.BNA_LABEL_COUNT,
                "cortical_label_ids": [sabra.BNA_CORTICAL_LABEL_IDS.start, sabra.BNA_CORTICAL_LABEL_IDS.stop - 1],
                "non_neocortical_cortical_areas": {
                    f"{left}-{left + 1}": area for left, area in sabra.BNA_NON_NEOCORTICAL_CORTICAL_AREAS.items()
                },
                "subcortical_label_ids_not_sabra": [
                    sabra.BNA_SUBCORTICAL_LABEL_IDS.start,
                    sabra.BNA_SUBCORTICAL_LABEL_IDS.stop - 1,
                ],
                "subcortical_groups_not_sabra": sabra.BNA_SUBCORTICAL_L2,
                "mixed_groups_not_sabra": sabra.BNA_MIXED_L2,
                "tool": "search_bna_candidates",
            },
            sabra.ATLAS_DHBA: {
                "scope": "all regions outside BNA territory (everything but the neocortex); HOMBA terms that have a DHBA name",
                "tool": "search_homba_candidates",
            },
        },
        "bna_territory_homba_roots": sabra.BNA_TERRITORY_HOMBA_ROOTS,
        "bna_territory_excluded_homba": sabra.BNA_TERRITORY_EXCLUDED_HOMBA,
        "dhba_counterparts_of_non_neocortical_bna": {
            f"{left}-{left + 1}": {"dhba_homba_id": hid, "dhba_acronym": acr}
            for left, (hid, acr) in sabra.BNA_DHBA_COUNTERPARTS.items()
        },
        "previous_bna_territory_homba_roots": sabra.PREVIOUS_BNA_TERRITORY_HOMBA_ROOTS,
    }


def _cbm_atlas() -> cbm.CbmAtlas:
    global _CBM_ATLAS
    if _CBM_ATLAS is None:
        _CBM_ATLAS = cbm.load_atlas(os.environ.get("CBM_ATLAS_PATH") or cbm.DEFAULT_ATLAS_PATH)
    return _CBM_ATLAS


def _number(value: object, name: str, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolInputError(f"{name} must be a number")
    if not lo <= float(value) <= hi:
        raise ToolInputError(f"{name} must be between {lo} and {hi}")
    return float(value)


def _tool_map_coordinates(args: dict) -> dict:
    points = args.get("points")
    if not isinstance(points, list) or not 1 <= len(points) <= 100:
        raise ToolInputError("points must be a list of 1-100 {x, y, z} objects")
    space = str(args.get("space") or cbm.SPACE_MNI).upper()
    if space not in (cbm.SPACE_MNI, cbm.SPACE_TAL):
        raise ToolInputError("space must be MNI or TAL")
    transform = str(args.get("tal_transform") or cbm.TAL_LANCASTER).lower()
    if transform not in (cbm.TAL_LANCASTER, cbm.TAL_BRETT):
        raise ToolInputError("tal_transform must be lancaster or brett")
    radius = _number(args.get("radius_mm", cbm.DEFAULT_RADIUS_MM), "radius_mm", 0, cbm.MAX_RADIUS_MM)
    search = _number(args.get("search_mm", cbm.DEFAULT_SEARCH_MM), "search_mm", 0, cbm.MAX_SEARCH_MM)
    for i, p in enumerate(points):
        if not isinstance(p, dict):
            raise ToolInputError(f"points[{i}] must be an object")
        for axis in ("x", "y", "z"):
            _number(p.get(axis), f"points[{i}].{axis}", -1000, 1000)
        if p.get("space") and str(p["space"]).upper() not in (cbm.SPACE_MNI, cbm.SPACE_TAL):
            raise ToolInputError(f"points[{i}].space must be MNI or TAL")

    atlas = _cbm_atlas()
    results = cbm.map_coordinates(
        atlas,
        points,
        space=space,
        tal_transform=transform,
        radius_mm=radius,
        search_mm=search,
        generator=lambda_function.get_generator(),
    )
    return {
        "results": results,
        "regions": cbm.summarize(results),
        "atlas": {
            "source": atlas.source,
            "voxel_mm": atlas.voxel_mm[0],
            "sabra_boundary_version": sabra.SABRA_BOUNDARY_VERSION,
            "radius_mm": radius,
            "search_mm": search,
        },
        "meta": {"rcs_version": ENGINE_VERSION},
    }


TOOL_HANDLERS = {
    "search_homba_candidates": _tool_search_homba,
    "search_bna_candidates": _tool_search_bna,
    "get_homba_term": _tool_get_term,
    "get_sabra_definition": _tool_sabra_definition,
    "map_coordinates": _tool_map_coordinates,
}


def _call_tool(msg_id: object, params: dict) -> dict:
    name = params.get("name")
    handler = TOOL_HANDLERS.get(name)  # type: ignore[arg-type]
    if handler is None:
        return _rpc_error(msg_id, -32602, f"Unknown tool: {name}")
    args = params.get("arguments") or {}
    if not isinstance(args, dict):
        return _rpc_error(msg_id, -32602, "arguments must be an object")
    try:
        data = handler(args)
        is_error = False
    except ToolInputError as exc:
        data, is_error = {"error": str(exc)}, True
    except Exception as exc:
        logger.exception("Tool %s failed", name)
        data, is_error = {"error": f"internal error: {exc}"}, True
    return _rpc_result(
        msg_id,
        {
            "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False)}],
            "structuredContent": data,
            "isError": is_error,
        },
    )


def handle_message(msg: object) -> dict | None:
    """Return the JSON-RPC response, or None for notifications/responses."""
    if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
        return _rpc_error(None, -32600, "Invalid Request")
    if "method" not in msg:
        return None  # a client response to a server request; we never send any
    method = msg["method"]
    msg_id = msg.get("id")
    if msg_id is None:
        return None  # notification (e.g. notifications/initialized)
    params = msg.get("params") or {}

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else SUPPORTED_PROTOCOL_VERSIONS[0]
        return _rpc_result(
            msg_id,
            {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": INSTRUCTIONS,
            },
        )
    if method == "ping":
        return _rpc_result(msg_id, {})
    if method == "tools/list":
        return _rpc_result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        return _call_tool(msg_id, params)
    return _rpc_error(msg_id, -32601, f"Method not found: {method}")


def lambda_handler(event, context):
    method = event.get("requestContext", {}).get("http", {}).get("method", "")
    headers = {k.lower(): v for k, v in (event.get("headers") or {}).items()}

    if not _authorized(headers):
        return _http(
            401,
            {"error": "unauthorized"},
            {"WWW-Authenticate": 'Bearer realm="rcs-mcp"'},
        )
    if method != "POST":
        return _http(405, {"error": "method not allowed"}, {"Allow": "POST"})

    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        raw = base64.b64decode(raw).decode("utf-8")
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return _http(400, _rpc_error(None, -32700, "Parse error"))

    if isinstance(msg, list):
        replies = [r for r in (handle_message(m) for m in msg) if r is not None]
        return _http(200, replies) if replies else _http(202)
    reply = handle_message(msg)
    return _http(200, reply) if reply is not None else _http(202)
