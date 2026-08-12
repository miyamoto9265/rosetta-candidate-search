#!/usr/bin/env python3
"""RCS top-1 validation for curated non-neocortex suitable records.

Pipeline
--------
1. Load suitable non_neocortex queries from curated CSV.
2. Run RCS (top-3) and cache results.
3. DeepSeek deepseek-v4-flash × 3 independent passes (NO pro).
   Prompt biases: strict / parent-aware / conservative.
4. Majority vote → validation_results.csv + summary.json.

Usage (repo root):
    set DEEPSEEK_API_KEY=...
    python playgrounds/260802_playground/eval_harness.py --workers 128
    python playgrounds/260802_playground/generate_report.py
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.rosetta_candidate_generator import RosettaCandidateGenerator  # noqa: E402

RCS_DIR = REPO_ROOT / "rcs"
HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
INPUT_CSV = (
    REPO_ROOT
    / "build_testdata"
    / "rcs_projection_corpus_curated_non_neocortex.csv"
)

CACHE_DIR = HERE / "cache"
RUNS_DIR = HERE / "runs"
CACHE_PATH = CACHE_DIR / "judgements.json"

API_URL = "https://api.deepseek.com/chat/completions"
# Official API id; served checkpoint is DeepSeek-V4-Flash-0731.
FLASH_MODEL = "deepseek-v4-flash"
MODEL_LABEL = "deepseek-v4-flash-0731"

LABELS = {
    "aligned",
    "broader_parent",
    "partial_or_narrower",
    "wrong",
    "ambiguous",
    "source_or_ontology_issue",
}
CERTAINTY = {"high", "medium", "low"}

PROMPT_BASE = """You are reviewing RCS top-1 candidate consistency for mammalian brain regions.

Important:
- There is NO established ground-truth dataset in this project.
- Judge whether `top1_name` is consistent with the `query` being evaluated.
- `query_kind` is either abbrev (short name/acronym) or fullname (expanded name).
  Judge the `query` itself; structure_name/fullname are context only.
- Do not compare against any previous LLM label.
- If the query is a compound structure and top1 covers only one part, label
  partial_or_narrower.

Labels:
- aligned: top1 directly names the same anatomical structure, accepted synonym,
  conventional spelling/word-order variant, or same named entity.
- broader_parent: top1 is broader than the query but anatomically the right
  parent/container. This is not exact, but it is not wrong.
- partial_or_narrower: top1 is only one component/subdivision of a broader or
  compound query, or is too narrow for the query.
- wrong: top1 is anatomically different/off-structure/off-lobe.
- ambiguous: multiple plausible interpretations; cannot decide confidently.
- source_or_ontology_issue: query appears misspelled/source-specific, or likely
  missing at HOMBA granularity, so candidate consistency cannot be strictly
  judged from the pair alone.

Return STRICT JSON only:
{
  "results": [
    {
      "record_id": <int>,
      "label": "<one label>",
      "certainty": "high|medium|low",
      "confidence": <float 0..1>,
      "reason": "<max 180 chars>"
    }
  ]
}
"""

PROMPT_A = (
    PROMPT_BASE
    + "\nBias: strict. Loose anatomical neighbors → wrong."
)
PROMPT_B = (
    PROMPT_BASE
    + "\nBias: distinguish exact/synonym from parent fallback. Use broader_parent "
    "when the candidate is a valid parent but not the exact query."
)
PROMPT_C = (
    PROMPT_BASE
    + "\nBias: expert conservative adjudication. Use ambiguous only when a human "
    "neuroanatomy review is genuinely needed. Pure JSON, no markdown."
)

PASSES = [
    ("pass1", FLASH_MODEL, PROMPT_A),
    ("pass2", FLASH_MODEL, PROMPT_B),
    ("pass3", FLASH_MODEL, PROMPT_C),
]


@dataclass
class QueryResult:
    dataset: str  # non_neocortex_abbrev | non_neocortex_fullname
    query: str
    query_kind: str  # abbrev | fullname
    structure_name: str
    fullname: str
    species: str
    n_mentions: str
    top_homba_id: str
    top_name: str
    score: str
    methods: str
    matched_query: str
    matched_alias: str
    modifier_terms: str
    top3: list[dict[str, Any]]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--tag", default="baseline")
    p.add_argument("--input", type=Path, default=INPUT_CSV)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--workers", type=int, default=128)
    p.add_argument("--limit", type=int, default=0, help="Smoke-test first N queries.")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument(
        "--rcs-only-refresh",
        action="store_true",
        help="Force re-run RCS even if rcs_results.json exists.",
    )
    return p.parse_args()


def load_queries(path: Path, limit: int = 0) -> list[dict[str, str]]:
    """Emit both structure_name (abbrev) and distinct fullname as separate queries."""
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()  # (kind, query.casefold())

    def add(
        *,
        query: str,
        kind: str,
        structure_name: str,
        fullname: str,
        species: str,
        n_mentions: str,
    ) -> None:
        q = query.strip()
        if not q:
            return
        key = (kind, q.casefold())
        if key in seen:
            return
        seen.add(key)
        rows.append(
            {
                "query": q,
                "query_kind": kind,
                "dataset": f"non_neocortex_{kind}",
                "structure_name": structure_name,
                "fullname": fullname,
                "species": species,
                "n_mentions": n_mentions,
            }
        )

    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            if (row.get("suitability") or "").strip() not in {"", "suitable"}:
                continue
            if (row.get("region_class") or "").strip() not in {"", "non_neocortex"}:
                continue
            structure = (row.get("structure_name") or "").strip()
            fullname = (row.get("fullname") or "").strip()
            species = (row.get("species") or "").strip()
            n_mentions = (row.get("n_mentions") or "").strip()
            if not structure:
                continue

            add(
                query=structure,
                kind="abbrev",
                structure_name=structure,
                fullname=fullname,
                species=species,
                n_mentions=n_mentions,
            )
            # Distinct fullname as its own RCS query (skip if identical to abbrev)
            if fullname and fullname.casefold() != structure.casefold():
                add(
                    query=fullname,
                    kind="fullname",
                    structure_name=structure,
                    fullname=fullname,
                    species=species,
                    n_mentions=n_mentions,
                )

            if limit and len(rows) >= limit:
                break
    return rows


def run_rcs(queries: list[dict[str, str]]) -> list[QueryResult]:
    generator = RosettaCandidateGenerator(
        HOMBA_CSV,
        token_rules_csv=RCS_DIR / "homba_token_rules.csv",
        alias_rules_csv=RCS_DIR / "homba_alias_rules.csv",
        abbrev_rules_csv=RCS_DIR / "homba_abbrev_rules.csv",
    )
    results: list[QueryResult] = []
    total = len(queries)
    for i, qrow in enumerate(queries, 1):
        query = qrow["query"]
        cands = generator.generate(query, top_k=3)
        base = dict(
            dataset=qrow["dataset"],
            query=query,
            query_kind=qrow["query_kind"],
            structure_name=qrow["structure_name"],
            fullname=qrow["fullname"],
            species=qrow["species"],
            n_mentions=qrow["n_mentions"],
        )
        if not cands:
            results.append(
                QueryResult(
                    **base,
                    top_homba_id="",
                    top_name="",
                    score="",
                    methods="",
                    matched_query="",
                    matched_alias="",
                    modifier_terms="",
                    top3=[],
                )
            )
        else:
            top = cands[0]
            results.append(
                QueryResult(
                    **base,
                    top_homba_id=str(top.get("homba_id", "")),
                    top_name=str(top.get("name", "")),
                    score=str(top.get("score", "")),
                    methods=str(top.get("methods", "")),
                    matched_query=str(top.get("matched_query", "")),
                    matched_alias=str(top.get("matched_alias", "")),
                    modifier_terms=str(top.get("modifier_terms", "")),
                    top3=[
                        {
                            "homba_id": c.get("homba_id"),
                            "name": c.get("name"),
                            "score": c.get("score"),
                            "methods": c.get("methods"),
                        }
                        for c in cands[:3]
                    ],
                )
            )
        if i % 200 == 0 or i == total:
            print(f"  RCS {i}/{total}", flush=True)
    return results


def cache_key(dataset: str, query: str, top_id: str) -> str:
    return f"{dataset}||{query}||{top_id}"


def load_cache() -> dict[str, Any]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(
        json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8"
    )


def extract_json_obj(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty content")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object found.")
    return json.loads(m.group(0))


def normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        rid = int(item.get("record_id"))
    except Exception:  # noqa: BLE001
        return None
    label = str(item.get("label") or "").strip().casefold().replace(" ", "_").replace("-", "_")
    aliases = {
        "exact": "aligned",
        "same": "aligned",
        "parent": "broader_parent",
        "broader": "broader_parent",
        "partial": "partial_or_narrower",
        "narrower": "partial_or_narrower",
        "ontology": "source_or_ontology_issue",
        "source": "source_or_ontology_issue",
    }
    label = aliases.get(label, label)
    if label not in LABELS:
        return None
    cert = str(item.get("certainty") or "medium").strip().casefold()
    if cert not in CERTAINTY:
        cert = "medium"
    try:
        conf = float(item.get("confidence", 0.5))
    except Exception:  # noqa: BLE001
        conf = 0.5
    conf = min(1.0, max(0.0, conf))
    return {
        "record_id": rid,
        "label": label,
        "certainty": cert,
        "confidence": conf,
        "reason": str(item.get("reason") or "").strip()[:220],
    }


def validate(id_map: dict[int, QueryResult], obj: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(obj.get("results"), list):
        return False, "missing results[]"
    ids = set(id_map)
    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for item in obj["results"]:
        if not isinstance(item, dict):
            return False, "non-object"
        norm = normalize_item(item)
        if norm is None:
            return False, f"bad item {item!r}"[:200]
        rid = norm["record_id"]
        if rid not in ids:
            return False, f"unknown record_id {rid}"
        if rid in seen:
            return False, f"duplicate {rid}"
        seen.add(rid)
        normalized.append(norm)
    if seen != ids:
        return False, f"missing {sorted(ids - seen)}"
    obj["results"] = normalized
    return True, ""


def call_deepseek(
    model: str,
    prompt: str,
    batch: list[QueryResult],
    base_id: int,
    api_key: str,
    retries: int = 5,
) -> dict[str, Any]:
    id_map = {base_id + i: r for i, r in enumerate(batch)}
    payload = [
        {
            "record_id": rid,
            "dataset": r.dataset,
            "query_kind": r.query_kind,
            "query": r.query,
            "structure_name": r.structure_name,
            "fullname": r.fullname,
            "species": r.species,
            "top1_name": r.top_name,
            "top1_id": r.top_homba_id,
        }
        for rid, r in id_map.items()
    ]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Review these records.\nrecords="
                + json.dumps(payload, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "max_tokens": 8192,
    }
    data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            API_URL,
            data=data_bytes,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"].get("content") or ""
            obj = extract_json_obj(content)
            ok, why = validate(id_map, obj)
            if not ok:
                raise ValueError(why)
            results: dict[str, Any] = {}
            for item in obj["results"]:
                r = id_map[int(item["record_id"])]
                results[cache_key(r.dataset, r.query, r.top_homba_id)] = {
                    "label": item["label"],
                    "certainty": item["certainty"],
                    "confidence": float(item["confidence"]),
                    "reason": item["reason"],
                }
            return {"ok": True, "results": results, "usage": data.get("usage", {})}
        except urllib.error.HTTPError as exc:
            body_txt = exc.read().decode("utf-8", errors="replace")[:300]
            last_error = f"HTTP {exc.code}: {body_txt}"
            sleep_s = (
                min(2**attempt, 30)
                if exc.code in (429, 500, 502, 503)
                else min(2**attempt, 12)
            )
            time.sleep(sleep_s)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(min(2**attempt, 12))
    return {"ok": False, "error": last_error}


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


def judge_pass(
    to_judge: list[QueryResult],
    pass_name: str,
    model: str,
    prompt: str,
    api_key: str,
    cache: dict[str, Any],
    batch_size: int,
    workers: int,
) -> int:
    pending = [
        r
        for r in to_judge
        if pass_name not in cache.get(cache_key(r.dataset, r.query, r.top_homba_id), {})
    ]
    if not pending:
        print(f"  {pass_name}: reuse all ({len(to_judge)})", flush=True)
        return 0

    batches = chunked(pending, batch_size)
    done = 0
    failures = 0
    total = len(batches)
    finished = 0
    print(
        f"  {pass_name}: model={model} pending={len(pending)} "
        f"batches={total} workers={workers}",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(call_deepseek, model, prompt, batch, i * 1000, api_key): batch
            for i, batch in enumerate(batches)
        }
        for fut in as_completed(futs):
            res = fut.result()
            finished += 1
            if not res["ok"]:
                failures += 1
            else:
                for key, vote in res["results"].items():
                    cache.setdefault(key, {})[pass_name] = vote
                    done += 1
            if finished % 40 == 0 or finished == total:
                save_cache(cache)
                print(
                    f"    {pass_name}: {finished}/{total} "
                    f"judged={done} fail_batches={failures}",
                    flush=True,
                )
    # retry missing once with smaller batches
    missing = [
        r
        for r in to_judge
        if pass_name not in cache.get(cache_key(r.dataset, r.query, r.top_homba_id), {})
    ]
    if missing:
        print(f"  {pass_name}: retry missing={len(missing)}", flush=True)
        retry_batches = chunked(missing, max(1, min(2, batch_size)))
        with ThreadPoolExecutor(max_workers=max(8, min(workers, 64))) as ex:
            futs = {
                ex.submit(call_deepseek, model, prompt, batch, i * 1000, api_key): batch
                for i, batch in enumerate(retry_batches)
            }
            for fut in as_completed(futs):
                res = fut.result()
                if not res["ok"]:
                    failures += 1
                    continue
                for key, vote in res["results"].items():
                    cache.setdefault(key, {})[pass_name] = vote
                    done += 1
    covered = sum(
        1
        for r in to_judge
        if pass_name in cache.get(cache_key(r.dataset, r.query, r.top_homba_id), {})
    )
    print(
        f"  {pass_name}: done judged_keys~={done} "
        f"covered={covered}/{len(to_judge)} fail_batches={failures}",
        flush=True,
    )
    return done


def final_decision(p1: dict, p2: dict, p3: dict) -> dict[str, Any]:
    votes = [v for v in (p1, p2, p3) if v and v.get("label")]
    n = len(votes)
    if not votes:
        return {
            "label": "no_consensus",
            "certainty": "low",
            "confidence": 0.0,
            "agreement": "0/3",
            "has_disagreement": True,
            "vote_split_pattern": "missing",
            "uncertainty_tag": "api_missing",
        }
    labels = [v["label"] for v in votes]
    certainties = [v.get("certainty", "medium") for v in votes]
    confidences = [float(v.get("confidence", 0)) for v in votes]
    counts = Counter(labels)
    label, count = counts.most_common(1)[0]
    avg_conf = sum(confidences) / len(confidences)
    has_disagreement = len(counts) > 1

    if n >= 3:
        has_maj = count >= 2
        split = "3-0" if count == 3 else ("2-1" if count == 2 else "1-1-1")
    elif n == 2:
        has_maj = count == 2
        split = "2-0" if has_maj else "1-1"
    else:
        has_maj = False
        split = "1-0"

    if has_maj:
        certainty = "high" if (count == n and avg_conf >= 0.8) else "medium"
        uncertainty = "stable" if count == n else "majority_vote"
    else:
        label = "no_consensus"
        certainty = "low"
        uncertainty = "split_vote"
        split = "1-1-1" if n >= 3 else split

    if "low" in certainties:
        uncertainty += "+low_certainty"
        if certainty == "high":
            certainty = "medium"

    return {
        "label": label,
        "certainty": certainty,
        "confidence": round(avg_conf, 4),
        "agreement": f"{count}/{n}",
        "has_disagreement": has_disagreement,
        "vote_split_pattern": split,
        "uncertainty_tag": uncertainty,
    }


def build_summary(rows: list[dict[str, Any]], meta: dict[str, Any]) -> dict[str, Any]:
    def agg(subset: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "records": len(subset),
            "label_counts": dict(Counter(r["final_label"] for r in subset)),
            "certainty_counts": dict(Counter(r["final_certainty"] for r in subset)),
            "vote_split_pattern_counts": dict(
                Counter(r["vote_split_pattern"] for r in subset)
            ),
        }

    abbrev = [r for r in rows if r["query_kind"] == "abbrev"]
    fullname = [r for r in rows if r["query_kind"] == "fullname"]
    return {
        "total_records": len(rows),
        "dataset": "non_neocortex",
        "models": {
            "pass1": MODEL_LABEL,
            "pass2": MODEL_LABEL,
            "pass3": MODEL_LABEL,
            "pro_used": False,
        },
        "input": meta.get("input"),
        "no_match_n": meta.get("no_match_n", 0),
        "query_kind_counts": dict(Counter(r["query_kind"] for r in rows)),
        "datasets": {
            "non_neocortex_abbrev": agg(abbrev),
            "non_neocortex_fullname": agg(fullname),
            "non_neocortex": agg(rows),
        },
        "overall": {
            "label_counts": dict(Counter(r["final_label"] for r in rows)),
            "certainty_counts": dict(Counter(r["final_certainty"] for r in rows)),
            "vote_split_pattern_counts": dict(
                Counter(r["vote_split_pattern"] for r in rows)
            ),
            "uncertainty_tag_counts": dict(
                Counter(r["uncertainty_tag"] for r in rows)
            ),
        },
    }


def save_rcs(path: Path, results: list[QueryResult]) -> None:
    path.write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=1),
        encoding="utf-8",
    )


def load_rcs(path: Path) -> list[QueryResult]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [QueryResult(**row) for row in data]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    args = parse_args()
    out_dir = RUNS_DIR / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)
    rcs_path = out_dir / "rcs_results.json"

    print(f"[{args.tag}] input={args.input}", flush=True)
    queries = load_queries(args.input, args.limit)
    print(f"  queries={len(queries)}", flush=True)

    if rcs_path.exists() and not args.rcs_only_refresh and not args.limit:
        print("  reuse RCS cache", flush=True)
        results = load_rcs(rcs_path)
    else:
        print("  running RCS...", flush=True)
        results = run_rcs(queries)
        save_rcs(rcs_path, results)
        print(f"  wrote {rcs_path}", flush=True)

    no_match = sum(1 for r in results if not r.top_homba_id)
    print(f"  RCS done: {len(results)}  no_match={no_match}", flush=True)

    cache = load_cache()
    if not args.no_llm:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY not set.", flush=True)
            return 2
        judgeable = [r for r in results if r.top_homba_id]
        print(
            f"  LLM judgeable={len(judgeable)} model={MODEL_LABEL} (no pro)",
            flush=True,
        )
        for pass_name, model, prompt in PASSES:
            judge_pass(
                judgeable,
                pass_name,
                model,
                prompt,
                api_key,
                cache,
                args.batch_size,
                args.workers,
            )
            save_cache(cache)

    rows: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        key = cache_key(r.dataset, r.query, r.top_homba_id)
        votes = cache.get(key, {})
        p1 = votes.get("pass1", {})
        p2 = votes.get("pass2", {})
        p3 = votes.get("pass3", {})
        if not r.top_homba_id:
            final = {
                "label": "source_or_ontology_issue",
                "certainty": "high",
                "confidence": 1.0,
                "agreement": "0/0",
                "has_disagreement": False,
                "vote_split_pattern": "no_match",
                "uncertainty_tag": "rcs_no_match",
            }
        else:
            final = final_decision(p1, p2, p3)
        rows.append(
            {
                "validation_id": i,
                "dataset": r.dataset,
                "query_kind": r.query_kind,
                "query": r.query,
                "structure_name": r.structure_name,
                "fullname": r.fullname,
                "species": r.species,
                "n_mentions": r.n_mentions,
                "top_homba_id": r.top_homba_id,
                "top_name": r.top_name,
                "score": r.score,
                "methods": r.methods,
                "matched_query": r.matched_query,
                "matched_alias": r.matched_alias,
                "modifier_terms": r.modifier_terms,
                "top3": json.dumps(r.top3, ensure_ascii=False),
                "pass1_label": p1.get("label", ""),
                "pass1_certainty": p1.get("certainty", ""),
                "pass1_confidence": p1.get("confidence", ""),
                "pass1_reason": p1.get("reason", ""),
                "pass2_label": p2.get("label", ""),
                "pass2_certainty": p2.get("certainty", ""),
                "pass2_confidence": p2.get("confidence", ""),
                "pass2_reason": p2.get("reason", ""),
                "pass3_label": p3.get("label", ""),
                "pass3_certainty": p3.get("certainty", ""),
                "pass3_confidence": p3.get("confidence", ""),
                "pass3_reason": p3.get("reason", ""),
                "final_label": final["label"],
                "final_certainty": final["certainty"],
                "final_confidence": final["confidence"],
                "vote_agreement": final["agreement"],
                "has_vote_disagreement": str(final["has_disagreement"]).lower(),
                "vote_split_pattern": final["vote_split_pattern"],
                "uncertainty_tag": final["uncertainty_tag"],
            }
        )

    csv_path = out_dir / "validation_results.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    summary = build_summary(
        rows, {"input": str(args.input), "no_match_n": no_match}
    )
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary["overall"]["label_counts"], ensure_ascii=False), flush=True)
    print(f"wrote {csv_path}", flush=True)
    print(f"wrote {out_dir / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
