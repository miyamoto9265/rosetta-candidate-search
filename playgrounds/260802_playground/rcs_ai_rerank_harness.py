#!/usr/bin/env python3
"""RCS + AI rerank prototype (playground only).

Pipeline
--------
1. Run RCS with top_k=10 (candidates only; engine untouched).
2. One LLM call per query: pick best candidate among the RCS top-10 and
   label how that HOMBA record relates to the query.

Relation labels (HOMBA relative to query):
- match     — 一致 (same structure / synonym)
- larger    — より大きい (HOMBA is broader parent/container than query)
- smaller   — より小さい (HOMBA is narrower / partial vs query)
- different — 異なる (anatomically distinct)

This is NOT the 3-pass validation judge. That remains offline evaluation only.

Usage (repo root):
    set DEEPSEEK_API_KEY=...
    python playgrounds/260802_playground/rcs_ai_rerank_harness.py --limit 5
    python playgrounds/260802_playground/rcs_ai_rerank_harness.py --stage all
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.rosetta_candidate_generator import RosettaCandidateGenerator  # noqa: E402

RCS_DIR = REPO_ROOT / "rcs"
HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
INPUT_CSV = REPO_ROOT / "build_testdata" / "rcs_ai_compare.csv"
RUNS_DIR = HERE / "runs" / "rcs_ai_rerank"
CACHE_DIR = HERE / "cache"
RCS_CACHE = CACHE_DIR / "rcs_ai_rerank_rcs.json"
AI_CACHE = CACHE_DIR / "rcs_ai_rerank_ai.json"

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
FLASH_MODEL = "deepseek-v4-flash"

RELATION_LABELS = ("match", "larger", "smaller", "different")
RELATION_JA = {
    "match": "一致",
    "larger": "より大きい",
    "smaller": "より小さい",
    "different": "異なる",
}

PRICING = {
    "deepseek-v4-flash": {
        "input_miss": 0.14,
        "input_hit": 0.0028,
        "output": 0.28,
    },
}

SYSTEM_PROMPT = """You improve RCS (ROSETTA Candidate Search) results for mammalian brain regions.

You are given:
- a user query (name or abbreviation)
- up to 10 HOMBA candidates already ranked by RCS (non-AI lexical/search engine)

Tasks:
1. Pick the single best HOMBA candidate for the query FROM THE PROVIDED LIST ONLY.
2. Label the anatomical relation of that chosen HOMBA record relative to the query.

Relation labels (HOMBA vs query):
- match: HOMBA names the same structure, accepted synonym, or conventional spelling/word-order variant.
- larger: HOMBA is broader than the query but anatomically the right parent/container.
- smaller: HOMBA is narrower than the query (subdivision / only one component of a compound query).
- different: HOMBA is anatomically a different structure (wrong pick among the list, or list has no good match).

Rules:
- You MUST set homba_id to one of the candidate IDs. Do not invent IDs.
- Prefer match over larger/smaller when a synonymous exact sense exists in the list.
- If no candidate is anatomically acceptable, still pick the least-bad ID and set relation=different with low confidence.
- Return STRICT JSON only, no markdown.

Schema:
{
  "results": [
    {
      "record_id": <int>,
      "homba_id": "<HOMBA:... from candidates>",
      "name": "<candidate name>",
      "relation": "match|larger|smaller|different",
      "confidence": <float 0..1>,
      "reason": "<max 180 chars>"
    }
  ]
}
"""


@dataclass
class UsageAccum:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cache_miss_tokens: int = 0
    cost_usd: float = 0.0
    errors: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def add(self, model: str, usage: dict[str, Any]) -> None:
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int(
            usage.get("prompt_cache_hit_tokens")
            or details.get("cached_tokens")
            or 0
        )
        miss = int(usage.get("prompt_cache_miss_tokens") or max(0, prompt - cached))
        price = PRICING.get(model, {})
        delta = (
            (miss / 1_000_000) * price.get("input_miss", 0.0)
            + (cached / 1_000_000) * price.get("input_hit", 0.0)
            + (completion / 1_000_000) * price.get("output", 0.0)
        )
        with self._lock:
            self.calls += 1
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.cached_tokens += cached
            self.cache_miss_tokens += miss
            self.cost_usd += delta

    def add_error(self) -> None:
        with self._lock:
            self.errors += 1

    def as_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                "calls": self.calls,
                "prompt_tokens": self.prompt_tokens,
                "completion_tokens": self.completion_tokens,
                "cached_tokens": self.cached_tokens,
                "cache_miss_tokens": self.cache_miss_tokens,
                "cost_usd": round(self.cost_usd, 6),
                "errors": self.errors,
            }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--stage",
        choices=["rcs", "ai", "report", "all"],
        default="all",
        help="Pipeline stage (default: all).",
    )
    p.add_argument("--input", type=Path, default=INPUT_CSV)
    p.add_argument("--top-k", type=int, default=10, help="RCS candidates for AI (default 10).")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--batch-size", type=int, default=8)
    p.add_argument("--limit", type=int, default=0, help="Limit rows (0 = all).")
    p.add_argument("--remap-rcs", action="store_true", help="Ignore RCS cache.")
    p.add_argument("--remap-ai", action="store_true", help="Ignore AI cache.")
    p.add_argument(
        "--model",
        default=FLASH_MODEL,
        help="DeepSeek model id (default: deepseek-v4-flash).",
    )
    p.add_argument(
        "--query",
        action="append",
        default=[],
        help="Ad-hoc query (repeatable). Skips CSV expected-id metrics.",
    )
    return p.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def extract_json_obj(text: str) -> dict[str, Any]:
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


def load_dataset(path: Path, limit: int = 0) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(dict(row))
            if limit and len(rows) >= limit:
                break
    return rows


def rows_from_queries(queries: list[str]) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for i, q in enumerate(queries, 1):
        q = q.strip()
        if not q:
            continue
        out.append(
            {
                "id": f"ADHOC-{i:03d}",
                "structure_name": q,
                "fullname": "",
                "expected_homba_id": "",
                "expected_homba_name": "",
                "difficulty": "adhoc",
                "query_kind": "adhoc",
                "source": "cli",
                "gt_status": "",
                "n_mentions": "",
                "notes": "",
            }
        )
    return out


def http_chat(
    *,
    url: str,
    api_key: str,
    body: dict[str, Any],
    retries: int = 5,
) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:400]}"
            if exc.code not in (429, 500, 502, 503) and attempt >= 2:
                break
            time.sleep(min(2**attempt, 30))
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(min(2**attempt, 12))
    raise RuntimeError(last)


def slim_candidate(c: dict[str, Any]) -> dict[str, Any]:
    return {
        "homba_id": str(c.get("homba_id") or ""),
        "name": str(c.get("name") or ""),
        "acronym": str(c.get("acronym") or ""),
        "score": float(c.get("score") or 0.0),
        "methods": str(c.get("methods") or ""),
        "parent_id": str(c.get("parent_id") or ""),
        "depth": c.get("depth"),
    }


def run_rcs(rows: list[dict[str, str]], top_k: int) -> dict[str, dict[str, Any]]:
    gen = RosettaCandidateGenerator(
        HOMBA_CSV,
        token_rules_csv=RCS_DIR / "homba_token_rules.csv",
        alias_rules_csv=RCS_DIR / "homba_alias_rules.csv",
        abbrev_rules_csv=RCS_DIR / "homba_abbrev_rules.csv",
    )
    out: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows, 1):
        q = row["structure_name"].strip()
        cands = [slim_candidate(c) for c in gen.generate(q, top_k=top_k)]
        top = cands[0] if cands else None
        out[row["id"]] = {
            "query": q,
            "top_k": top_k,
            "candidates": cands,
            "rcs_top1_id": top["homba_id"] if top else "",
            "rcs_top1_name": top["name"] if top else "",
            "rcs_top1_score": top["score"] if top else 0.0,
        }
        if i % 25 == 0 or i == len(rows):
            print(f"  RCS {i}/{len(rows)}", flush=True)
    return out


def _normalize_ai_item(
    item: dict[str, Any],
    allowed_ids: set[str],
    id_to_name: dict[str, str],
) -> dict[str, Any] | None:
    try:
        rid = int(item.get("record_id"))
    except Exception:  # noqa: BLE001
        return None
    hid = str(item.get("homba_id") or "").strip()
    if hid and not hid.upper().startswith("HOMBA:"):
        if re.fullmatch(r"(AA)?\d+", hid, re.I):
            hid = f"HOMBA:{hid}"
        else:
            hid = ""
    if hid not in allowed_ids:
        return None
    relation = str(item.get("relation") or "").strip().lower()
    # accept a few aliases
    alias = {
        "aligned": "match",
        "exact": "match",
        "same": "match",
        "broader": "larger",
        "broader_parent": "larger",
        "parent": "larger",
        "narrower": "smaller",
        "partial": "smaller",
        "partial_or_narrower": "smaller",
        "wrong": "different",
        "off": "different",
    }
    relation = alias.get(relation, relation)
    if relation not in RELATION_LABELS:
        relation = "different"
    try:
        conf = float(item.get("confidence"))
    except Exception:  # noqa: BLE001
        conf = 0.0
    conf = max(0.0, min(1.0, conf))
    name = str(item.get("name") or "").strip() or id_to_name.get(hid, "")
    reason = str(item.get("reason") or "").strip()[:180]
    return {
        "record_id": rid,
        "homba_id": hid,
        "name": name,
        "relation": relation,
        "relation_ja": RELATION_JA[relation],
        "confidence": conf,
        "reason": reason,
    }


def build_user_payload(batch: list[tuple[int, str, list[dict[str, Any]]]]) -> str:
    lines = ["Evaluate these records. Candidates are RCS-ranked (best first).\n"]
    for rid, query, cands in batch:
        lines.append(f"record_id={rid}")
        lines.append(f"query={query}")
        lines.append("candidates:")
        if not cands:
            lines.append("  (none)")
        else:
            for rank, c in enumerate(cands, 1):
                lines.append(
                    f"  {rank}. {c['homba_id']}|{c.get('acronym') or ''}|{c['name']}"
                    f"|score={c.get('score')}|methods={c.get('methods')}"
                )
        lines.append("")
    return "\n".join(lines)


def call_ai_batch(
    batch: list[tuple[int, str, list[dict[str, Any]]]],
    *,
    api_key: str,
    model: str,
    usage: UsageAccum,
) -> dict[int, dict[str, Any]]:
    # skip empty-candidate rows locally
    nonempty = [(rid, q, c) for rid, q, c in batch if c]
    out: dict[int, dict[str, Any]] = {}
    for rid, q, _ in batch:
        if not _:
            out[rid] = {
                "homba_id": "",
                "name": "",
                "relation": "different",
                "relation_ja": RELATION_JA["different"],
                "confidence": 0.0,
                "reason": "rcs_no_candidates",
                "error": None,
            }
    if not nonempty:
        return out

    body = {
        "model": model,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": build_user_payload(nonempty)},
        ],
        "response_format": {"type": "json_object"},
    }
    # DeepSeek thinking off when supported
    if model.startswith("deepseek"):
        body["thinking"] = {"type": "disabled"}

    try:
        resp = http_chat(url=DEEPSEEK_URL, api_key=api_key, body=body)
        usage.add(model, resp.get("usage") or {})
        content = resp["choices"][0]["message"]["content"]
        obj = extract_json_obj(content)
        results = obj.get("results") or []
    except Exception as exc:  # noqa: BLE001
        usage.add_error()
        for rid, _, _ in nonempty:
            out[rid] = {
                "homba_id": "",
                "name": "",
                "relation": "different",
                "relation_ja": RELATION_JA["different"],
                "confidence": 0.0,
                "reason": "",
                "error": str(exc)[:300],
            }
        return out

    by_rid: dict[int, dict[str, Any]] = {}
    for rid, _, cands in nonempty:
        allowed = {c["homba_id"] for c in cands if c.get("homba_id")}
        id_to_name = {c["homba_id"]: c["name"] for c in cands if c.get("homba_id")}
        # default fallback: RCS top1 + different (will overwrite if model returns)
        top = cands[0]
        by_rid[rid] = {
            "homba_id": top["homba_id"],
            "name": top["name"],
            "relation": "different",
            "relation_ja": RELATION_JA["different"],
            "confidence": 0.0,
            "reason": "ai_parse_fallback_rcs_top1",
            "error": "missing_result",
        }
        # stash for normalize
        by_rid[rid]["_allowed"] = allowed  # type: ignore[assignment]
        by_rid[rid]["_id_to_name"] = id_to_name  # type: ignore[assignment]

    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            rid = int(item.get("record_id"))
        except Exception:  # noqa: BLE001
            continue
        meta = by_rid.get(rid)
        if not meta:
            continue
        allowed = meta.pop("_allowed")  # type: ignore[misc]
        id_to_name = meta.pop("_id_to_name")  # type: ignore[misc]
        norm = _normalize_ai_item(item, allowed, id_to_name)
        if norm is None:
            # keep fallback but clear internal keys if still present
            meta.pop("_allowed", None)
            meta.pop("_id_to_name", None)
            meta["error"] = "invalid_or_out_of_list_id"
            continue
        out[rid] = {**norm, "error": None}
        by_rid.pop(rid, None)

    for rid, meta in by_rid.items():
        meta.pop("_allowed", None)
        meta.pop("_id_to_name", None)
        out[rid] = meta
    return out


def run_ai(
    rows: list[dict[str, str]],
    rcs_map: dict[str, dict[str, Any]],
    *,
    api_key: str,
    model: str,
    workers: int,
    batch_size: int,
    cache: dict[str, Any],
    remap: bool,
) -> tuple[dict[str, dict[str, Any]], UsageAccum]:
    usage = UsageAccum()
    out: dict[str, dict[str, Any]] = {}
    pending: list[tuple[str, int, str, list[dict[str, Any]]]] = []
    # stable local record_id per pending item
    for i, row in enumerate(rows):
        rid_str = row["id"]
        cache_key = f"{model}||{rid_str}||{row['structure_name'].strip()}"
        if not remap and cache_key in cache:
            out[rid_str] = cache[cache_key]
            continue
        rcs = rcs_map.get(rid_str) or {}
        pending.append(
            (
                rid_str,
                i + 1,
                row["structure_name"].strip(),
                list(rcs.get("candidates") or []),
            )
        )

    batches: list[list[tuple[str, int, str, list[dict[str, Any]]]]] = []
    for i in range(0, len(pending), batch_size):
        batches.append(pending[i : i + batch_size])

    def _work(
        batch: list[tuple[str, int, str, list[dict[str, Any]]]],
    ) -> list[tuple[str, dict[str, Any]]]:
        local_batch = [(local_id, q, cands) for _, local_id, q, cands in batch]
        got = call_ai_batch(local_batch, api_key=api_key, model=model, usage=usage)
        results: list[tuple[str, dict[str, Any]]] = []
        for rid_str, local_id, _, _ in batch:
            results.append((rid_str, got[local_id]))
        return results

    id_to_row = {r["id"]: r for r in rows}
    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(_work, b) for b in batches]
        for fut in as_completed(futs):
            for rid_str, item in fut.result():
                row = id_to_row[rid_str]
                cache_key = f"{model}||{rid_str}||{row['structure_name'].strip()}"
                out[rid_str] = item
                cache[cache_key] = item
                done += 1
            print(f"  AI {min(done, len(pending))}/{len(pending)}", flush=True)

    return out, usage


def build_records(
    rows: list[dict[str, str]],
    rcs_map: dict[str, dict[str, Any]],
    ai_map: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for row in rows:
        rid = row["id"]
        rcs = rcs_map.get(rid) or {}
        ai = ai_map.get(rid) or {}
        expected = (row.get("expected_homba_id") or "").strip()
        rcs_top1 = rcs.get("rcs_top1_id") or ""
        ai_id = ai.get("homba_id") or ""
        records.append(
            {
                "id": rid,
                "query": row["structure_name"].strip(),
                "expected_homba_id": expected,
                "expected_homba_name": row.get("expected_homba_name") or "",
                "difficulty": row.get("difficulty") or "",
                "top_k": rcs.get("top_k"),
                "candidates": rcs.get("candidates") or [],
                "rcs_top1": {
                    "homba_id": rcs_top1,
                    "name": rcs.get("rcs_top1_name") or "",
                    "score": rcs.get("rcs_top1_score") or 0.0,
                },
                "ai": {
                    "enabled": True,
                    "best_homba_id": ai_id,
                    "best_name": ai.get("name") or "",
                    "relation": ai.get("relation") or "",
                    "relation_ja": ai.get("relation_ja") or "",
                    "confidence": ai.get("confidence") or 0.0,
                    "reason": ai.get("reason") or "",
                    "error": ai.get("error"),
                    "changed_from_rcs_top1": bool(ai_id and rcs_top1 and ai_id != rcs_top1),
                },
                "metrics": {
                    "rcs_top1_hit": bool(expected and rcs_top1 == expected),
                    "ai_best_hit": bool(expected and ai_id == expected),
                    "expected_in_rcs_topk": bool(
                        expected
                        and any(
                            c.get("homba_id") == expected
                            for c in (rcs.get("candidates") or [])
                        )
                    ),
                },
            }
        )
    return records


def summarize(records: list[dict[str, Any]], usage: UsageAccum, model: str) -> dict[str, Any]:
    n = len(records)
    with_expected = [r for r in records if r.get("expected_homba_id")]
    n_exp = len(with_expected)
    rcs_hits = sum(1 for r in with_expected if r["metrics"]["rcs_top1_hit"])
    ai_hits = sum(1 for r in with_expected if r["metrics"]["ai_best_hit"])
    in_topk = sum(1 for r in with_expected if r["metrics"]["expected_in_rcs_topk"])
    changed = sum(1 for r in records if r["ai"]["changed_from_rcs_top1"])
    rel_counts = Counter(r["ai"]["relation"] for r in records if r["ai"].get("relation"))
    # flips vs expected
    rcs_wrong_ai_right = sum(
        1
        for r in with_expected
        if (not r["metrics"]["rcs_top1_hit"]) and r["metrics"]["ai_best_hit"]
    )
    rcs_right_ai_wrong = sum(
        1
        for r in with_expected
        if r["metrics"]["rcs_top1_hit"] and (not r["metrics"]["ai_best_hit"])
    )
    return {
        "n_queries": n,
        "n_with_expected": n_exp,
        "model": model,
        "rcs_top1_hit_rate": round(rcs_hits / n_exp, 4) if n_exp else None,
        "ai_best_hit_rate": round(ai_hits / n_exp, 4) if n_exp else None,
        "expected_in_rcs_topk_rate": round(in_topk / n_exp, 4) if n_exp else None,
        "ai_changed_from_rcs_top1": changed,
        "rcs_wrong_ai_right": rcs_wrong_ai_right,
        "rcs_right_ai_wrong": rcs_right_ai_wrong,
        "relation_counts": dict(rel_counts),
        "costs": usage.as_dict(),
    }


def write_report(records: list[dict[str, Any]], summary: dict[str, Any], path: Path) -> None:
    rows_html: list[str] = []
    for r in records:
        ai = r["ai"]
        m = r["metrics"]
        cands = r["candidates"]
        cand_preview = "<br>".join(
            html.escape(
                f"{i}. {c.get('homba_id')} {c.get('name')} ({c.get('score')})"
            )
            for i, c in enumerate(cands[:5], 1)
        )
        if len(cands) > 5:
            cand_preview += f"<br>… +{len(cands) - 5} more"
        changed = "yes" if ai.get("changed_from_rcs_top1") else ""
        rows_html.append(
            "<tr>"
            f"<td>{html.escape(r['id'])}</td>"
            f"<td>{html.escape(r['query'])}</td>"
            f"<td>{html.escape(r.get('difficulty') or '')}</td>"
            f"<td>{html.escape(r['rcs_top1'].get('homba_id') or '')}<br>"
            f"<small>{html.escape(r['rcs_top1'].get('name') or '')}</small></td>"
            f"<td>{html.escape(ai.get('best_homba_id') or '')}<br>"
            f"<small>{html.escape(ai.get('best_name') or '')}</small></td>"
            f"<td>{html.escape(ai.get('relation') or '')}"
            f" ({html.escape(ai.get('relation_ja') or '')})</td>"
            f"<td>{ai.get('confidence')}</td>"
            f"<td>{changed}</td>"
            f"<td>{'Y' if m.get('rcs_top1_hit') else ''}</td>"
            f"<td>{'Y' if m.get('ai_best_hit') else ''}</td>"
            f"<td>{'Y' if m.get('expected_in_rcs_topk') else ''}</td>"
            f"<td><small>{html.escape(ai.get('reason') or '')}</small></td>"
            f"<td><small>{cand_preview}</small></td>"
            "</tr>"
        )

    s = summary
    body = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<title>RCS AI rerank prototype</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 24px; color: #1a1a1a; }}
h1 {{ font-size: 1.4rem; }}
.cards {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 16px 0 24px; }}
.card {{ border: 1px solid #ddd; padding: 12px 16px; min-width: 140px; }}
.card b {{ display: block; font-size: 1.3rem; }}
table {{ border-collapse: collapse; width: 100%; font-size: 0.85rem; }}
th, td {{ border: 1px solid #e0e0e0; padding: 6px 8px; vertical-align: top; }}
th {{ background: #f5f5f5; position: sticky; top: 0; }}
tr:nth-child(even) {{ background: #fafafa; }}
code {{ background: #f0f0f0; padding: 1px 4px; }}
</style>
</head>
<body>
<h1>RCS AI rerank prototype</h1>
<p>RCS top-{html.escape(str(records[0]['top_k'] if records else 10))} → LLM picks best + relation
(<code>match/larger/smaller/different</code>). Model: <code>{html.escape(str(s.get('model')))}</code></p>
<div class="cards">
  <div class="card"><span>queries</span><b>{s.get('n_queries')}</b></div>
  <div class="card"><span>RCS top1 hit</span><b>{s.get('rcs_top1_hit_rate')}</b></div>
  <div class="card"><span>AI best hit</span><b>{s.get('ai_best_hit_rate')}</b></div>
  <div class="card"><span>expected in topK</span><b>{s.get('expected_in_rcs_topk_rate')}</b></div>
  <div class="card"><span>AI≠RCS top1</span><b>{s.get('ai_changed_from_rcs_top1')}</b></div>
  <div class="card"><span>RCS✗→AI✓</span><b>{s.get('rcs_wrong_ai_right')}</b></div>
  <div class="card"><span>RCS✓→AI✗</span><b>{s.get('rcs_right_ai_wrong')}</b></div>
  <div class="card"><span>cost USD</span><b>{(s.get('costs') or {}).get('cost_usd')}</b></div>
</div>
<p>relation_counts: {html.escape(json.dumps(s.get('relation_counts') or {}, ensure_ascii=False))}</p>
<table>
<thead>
<tr>
<th>id</th><th>query</th><th>diff</th>
<th>RCS top1</th><th>AI best</th><th>relation</th><th>conf</th><th>changed</th>
<th>RCS hit</th><th>AI hit</th><th>in topK</th><th>reason</th><th>candidates (top5)</th>
</tr>
</thead>
<tbody>
{''.join(rows_html)}
</tbody>
</table>
</body>
</html>
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def main() -> int:
    args = parse_args()
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    if args.query:
        rows = rows_from_queries(args.query)
        if args.limit:
            rows = rows[: args.limit]
    else:
        rows = load_dataset(args.input, limit=args.limit)
    if not rows:
        print("No rows.", file=sys.stderr)
        return 1

    top_k = max(1, min(int(args.top_k), 20))
    rcs_cache = {} if args.remap_rcs else _load_json(RCS_CACHE)
    ai_cache = {} if args.remap_ai else _load_json(AI_CACHE)

    # ----- RCS -----
    if args.stage in ("rcs", "all"):
        print(f"[rcs] {len(rows)} queries, top_k={top_k}", flush=True)
        # reuse cache entries when query+top_k match
        need = []
        rcs_map: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"{row['id']}||{row['structure_name'].strip()}||{top_k}"
            if key in rcs_cache and not args.remap_rcs:
                rcs_map[row["id"]] = rcs_cache[key]
            else:
                need.append(row)
        if need:
            fresh = run_rcs(need, top_k=top_k)
            for row in need:
                key = f"{row['id']}||{row['structure_name'].strip()}||{top_k}"
                rcs_cache[key] = fresh[row["id"]]
                rcs_map[row["id"]] = fresh[row["id"]]
            _save_json(RCS_CACHE, rcs_cache)
        else:
            print("  RCS cache hit for all rows", flush=True)
        _save_json(RUNS_DIR / "rcs_results.json", rcs_map)
    else:
        rcs_map = {}
        for row in rows:
            key = f"{row['id']}||{row['structure_name'].strip()}||{top_k}"
            if key in rcs_cache:
                rcs_map[row["id"]] = rcs_cache[key]
        if len(rcs_map) != len(rows):
            # fallback: runs file
            disk = _load_json(RUNS_DIR / "rcs_results.json")
            rcs_map = {row["id"]: disk[row["id"]] for row in rows if row["id"] in disk}
        if len(rcs_map) != len(rows):
            print("Missing RCS results; run --stage rcs|all first.", file=sys.stderr)
            return 1

    usage = UsageAccum()
    ai_map: dict[str, dict[str, Any]] = {}

    # ----- AI -----
    if args.stage in ("ai", "all"):
        api_key = os.environ.get("DEEPSEEK_API_KEY") or ""
        if not api_key:
            print("DEEPSEEK_API_KEY is required for AI stage.", file=sys.stderr)
            return 1
        print(f"[ai] model={args.model} workers={args.workers}", flush=True)
        ai_map, usage = run_ai(
            rows,
            rcs_map,
            api_key=api_key,
            model=args.model,
            workers=args.workers,
            batch_size=max(1, args.batch_size),
            cache=ai_cache,
            remap=args.remap_ai,
        )
        _save_json(AI_CACHE, ai_cache)
        _save_json(RUNS_DIR / "ai_results.json", ai_map)
        _save_json(RUNS_DIR / "costs.json", usage.as_dict())
    else:
        ai_map = _load_json(RUNS_DIR / "ai_results.json")
        if not ai_map:
            # try rebuild from cache keys
            for row in rows:
                key = f"{args.model}||{row['id']}||{row['structure_name'].strip()}"
                if key in ai_cache:
                    ai_map[row["id"]] = ai_cache[key]
        if len(ai_map) != len(rows):
            print("Missing AI results; run --stage ai|all first.", file=sys.stderr)
            return 1

    # ----- report -----
    if args.stage in ("report", "all"):
        if args.stage == "report":
            costs = _load_json(RUNS_DIR / "costs.json")
            if costs:
                usage.calls = int(costs.get("calls") or 0)
                usage.prompt_tokens = int(costs.get("prompt_tokens") or 0)
                usage.completion_tokens = int(costs.get("completion_tokens") or 0)
                usage.cached_tokens = int(costs.get("cached_tokens") or 0)
                usage.cache_miss_tokens = int(costs.get("cache_miss_tokens") or 0)
                usage.cost_usd = float(costs.get("cost_usd") or 0.0)
                usage.errors = int(costs.get("errors") or 0)
        records = build_records(rows, rcs_map, ai_map)
        summary = summarize(records, usage, args.model)
        _save_json(RUNS_DIR / "results.json", {"records": records})
        _save_json(RUNS_DIR / "summary.json", summary)
        write_report(records, summary, RUNS_DIR / "rcs_ai_rerank_report.html")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        print(f"Report: {RUNS_DIR / 'rcs_ai_rerank_report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
