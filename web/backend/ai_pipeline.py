"""LLM preprocess/postprocess pipeline for RCS.

Two-stage AI around the RCS engine (engine itself is untouched):
- preprocess: strip non-essential tokens (laterality, genes/markers, cell types, junk)
- postprocess: adjudicate RCS candidates into 0-4 acceptable picks with relation labels

No confidence scores. Relation is from the QUERY's perspective:
"'=" (apostrophe+equals, Excel-safe) | "<" (query smaller) | ">" (query larger).
Wrong candidates are omitted, never listed.

Environment:
- DEEPSEEK_API_KEY: required for any LLM stage
- AI_MODEL: model id (default deepseek-v4-flash)
- AI_HTTP_TIMEOUT_SEC: per-call timeout seconds (default 8)
"""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
from typing import Any

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_MODEL = "deepseek-v4-flash"

REMOVED_KINDS = {"laterality", "gene_or_marker", "cell_type", "method_or_other", "noise"}
RELATIONS = {"'=", "<", ">"}
MAX_AI_RESULTS = 4

PREPROCESS_SYSTEM = """You clean mammalian brain-region search queries for RCS (ROSETTA Candidate Search).

Task: given one raw query string, return the anatomical ROI essence only.
Remove non-essential tokens; do NOT invent a new region name that was not implied by the query.

An optional free-text "context" (e.g. paper title) may accompany the query. Use it only as a
disambiguation hint; the roi_query must still come from the query itself.

REMOVE (list each in "removed"):
- laterality: left, right, bilateral, ipsilateral, contralateral, ipsi, contra, etc.
- gene / molecular markers / driver lines: e.g. Drd1, Ppp1r1b, SST, vGluT2, Thy1, Cre lines
- cell-type words when not part of the region name: neurons, cells, interneurons, etc.
- method / experiment / trailing junk; cut "excluding|except|without ..." tails

KEEP:
- the region name or conventional abbreviation (NAc, BLA, ACC, VTA, ...)
- anatomical polarity/position that defines the ROI (e.g. KEEP "lateral" in "lateral hypothalamus";
  that is NOT laterality-of-hemisphere)
- compound region constituents that are part of the name

Rules:
- roi_query should be a short search string (name and/or acronym). Prefer the query's own wording/abbrev.
- If the query is already a clean ROI, roi_query may equal the trimmed query and removed=[] .
- Do NOT output confidence scores.
- Return STRICT JSON only, no markdown.

Schema:
{
  "roi_query": "<cleaned ROI string>",
  "removed": [
    {"text": "<removed span>", "kind": "laterality|gene_or_marker|cell_type|method_or_other|noise"}
  ],
  "reason": "<max 80 chars>"
}"""

POSTPROCESS_SYSTEM = """You adjudicate RCS (ROSETTA Candidate Search) candidates for mammalian brain regions.

You are given:
- raw_query: original user string
- context: optional free text (e.g. paper title) to disambiguate the intended region
- roi_query: optional cleaned ROI used for search (may equal raw_query)
- removed: optional list of tokens stripped in preprocess
- candidates: up to 10 HOMBA rows from RCS (id|acronym|name|score), best-first

Use context only to resolve ambiguity (e.g. which sense of an abbreviation). Do not let context
override the query's own region.

Task:
Return 0 to 4 acceptable candidates from the list (hard max 4).
First item is the best; following items are other plausible options if any.
Omit anatomically wrong candidates entirely (do not list them).

Relation is from the QUERY's perspective vs the chosen HOMBA entry:
- "'=" : same structure / accepted synonym / conventional spelling or word-order variant
       (MUST be apostrophe + equals, two characters: ' =  so spreadsheets do not treat it as a formula)
- "<"  : query is smaller than HOMBA (HOMBA is the broader parent/container)
- ">"  : query is larger than HOMBA (HOMBA is a part/subdivision / too narrow)

Rules:
- Every homba_id MUST appear in candidates. Never invent IDs.
- Prefer "'=" when a synonymous exact sense exists.
- If nothing is anatomically acceptable, return {"results": []}.
- Do NOT invent filler results. Do NOT output confidence scores.
- Do NOT use bare "=" ; only "'=", "<", ">".
- reason: max 80 chars.
- Return STRICT JSON only, no markdown.

Schema:
{
  "results": [
    {
      "homba_id": "<HOMBA:... from candidates>",
      "name": "<candidate name>",
      "relation": "'=" | "<" | ">",
      "reason": "<max 80 chars>"
    }
  ]
}"""


def ai_available() -> bool:
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def _model() -> str:
    return (os.environ.get("AI_MODEL") or DEFAULT_MODEL).strip() or DEFAULT_MODEL


def _timeout() -> float:
    try:
        return float(os.environ.get("AI_HTTP_TIMEOUT_SEC") or 8)
    except ValueError:
        return 8.0


def _extract_json_obj(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty content")
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object found")
    return json.loads(m.group(0))


def _chat(system: str, user: str, retries: int = 2) -> dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        raise RuntimeError("DEEPSEEK_API_KEY is not set")
    body: dict[str, Any] = {
        "model": _model(),
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "response_format": {"type": "json_object"},
    }
    if _model().startswith("deepseek"):
        body["thinking"] = {"type": "disabled"}
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            DEEPSEEK_URL,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=_timeout()) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}"
            if exc.code not in (429, 500, 502, 503) and attempt >= 1:
                break
            time.sleep(min(2**attempt, 8))
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(min(2**attempt, 8))
    raise RuntimeError(last)


def _content(payload: dict[str, Any]) -> str:
    return payload["choices"][0]["message"]["content"]


def _norm_removed(items: Any) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    if not isinstance(items, list):
        return out
    for it in items:
        if not isinstance(it, dict):
            continue
        text = str(it.get("text") or "").strip()
        kind = str(it.get("kind") or "").strip().lower()
        if not text:
            continue
        if kind not in REMOVED_KINDS:
            kind = "noise"
        out.append({"text": text, "kind": kind})
    return out


def preprocess(query: str, context: str = "") -> dict[str, Any]:
    """Return {roi_query, removed, reason, error}. On failure error is set and
    roi_query falls back to the original query."""
    if not query.strip():
        return {"roi_query": query, "removed": [], "reason": "", "error": "empty_query"}
    user = f"query={query}"
    if context.strip():
        user += f"\ncontext={context.strip()}"
    try:
        payload = _chat(PREPROCESS_SYSTEM, user)
        obj = _extract_json_obj(_content(payload))
        roi = str(obj.get("roi_query") or "").strip()
        if not roi:
            roi = query
        return {
            "roi_query": roi,
            "removed": _norm_removed(obj.get("removed")),
            "reason": str(obj.get("reason") or "")[:200],
            "error": None,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "roi_query": query,
            "removed": [],
            "reason": "",
            "error": str(exc)[:300],
        }


def _norm_relation(value: Any) -> str | None:
    rel = str(value or "").strip()
    if rel == "=":
        rel = "'="
    if rel not in RELATIONS:
        return None
    return rel


def _norm_homba_id(value: Any) -> str:
    hid = str(value or "").strip()
    if hid and not hid.upper().startswith("HOMBA:"):
        if re.fullmatch(r"(AA)?\d+", hid, re.I):
            hid = f"HOMBA:{hid}"
        else:
            hid = ""
    return hid


def postprocess(
    raw_query: str,
    roi_query: str,
    removed: list[dict[str, str]],
    candidates: list[dict[str, Any]],
    context: str = "",
) -> dict[str, Any]:
    """Return {results: [...], error}. results 0..4, wrong omitted."""
    if not candidates:
        return {"results": [], "error": None}
    allowed: dict[str, dict[str, Any]] = {}
    for c in candidates:
        hid = str(c.get("homba_id") or "")
        if hid:
            allowed[hid] = c
    if not allowed:
        return {"results": [], "error": None}

    lines = [
        f"raw_query={raw_query}",
        f"context={context.strip()}",
        f"roi_query={roi_query}",
        f"removed={json.dumps(removed, ensure_ascii=False)}",
        "candidates:",
    ]
    for i, c in enumerate(candidates[:10], 1):
        lines.append(
            f"  {i}. {c.get('homba_id')}|{c.get('acronym') or ''}|{c.get('name')}"
            f"|score={c.get('score')}"
        )
    user = "\n".join(lines)

    try:
        payload = _chat(POSTPROCESS_SYSTEM, user)
        obj = _extract_json_obj(_content(payload))
        items = obj.get("results") or []
    except Exception as exc:  # noqa: BLE001
        return {"results": [], "error": str(exc)[:300]}

    results: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(items, list):
        for it in items:
            if not isinstance(it, dict):
                continue
            hid = _norm_homba_id(it.get("homba_id"))
            if not hid or hid not in allowed or hid in seen:
                continue
            rel = _norm_relation(it.get("relation"))
            if rel is None:
                continue
            cand = allowed[hid]
            name = str(it.get("name") or "").strip() or str(cand.get("name") or "")
            results.append(
                {
                    "homba_id": hid,
                    "name": name,
                    "acronym": str(cand.get("acronym") or ""),
                    "relation": rel,
                    "reason": str(it.get("reason") or "")[:200],
                }
            )
            seen.add(hid)
            if len(results) >= MAX_AI_RESULTS:
                break
    return {"results": results, "error": None}
