#!/usr/bin/env python3
"""RCS auto-improvement evaluation harness.

Pipeline
--------
1. Run RCS over the corpus + species test data (dedup by structure_name),
   collecting the top-1 (and optionally top-3) candidate per query.
2. Validate each (query -> top-1) pair with a DeepSeek 3-pass consistency
   review (Flash strict / Flash parent-aware / Pro conservative), in parallel.
3. Judgements are cached keyed on (dataset, query, top_homba_id) so that when
   the algorithm changes only the *new* query->candidate pairs are re-judged.
   This keeps the improvement loop cheap.

Output
------
runs/<tag>/records.csv     per-query top-1 + 3-pass labels
runs/<tag>/summary.json    label / certainty aggregates (v1-compatible schema)
cache/judgements.json      persistent (dataset,query,top_id) -> 3 votes cache

Usage
-----
    python eval_harness.py --tag baseline
    python eval_harness.py --tag round1 --workers 16
    python eval_harness.py --tag baseline --no-llm   # RCS only, skip DeepSeek
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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.rosetta_candidate_generator import RosettaCandidateGenerator  # noqa: E402

RCS_DIR = REPO_ROOT / "rcs"
HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
CORPUS_CSV = REPO_ROOT / "build_testdata" / "rcs_corpus_no_direction.csv"
SPECIES_CSV = REPO_ROOT / "build_testdata" / "rcs_species.csv"

CACHE_DIR = HERE / "cache"
RUNS_DIR = HERE / "runs"
CACHE_PATH = CACHE_DIR / "judgements.json"

API_URL = "https://api.deepseek.com/chat/completions"
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"

LABELS = {
    "aligned",
    "broader_parent",
    "partial_or_narrower",
    "wrong",
    "ambiguous",
    "source_or_ontology_issue",
}
CERTAINTY = {"high", "medium", "low"}

PROMPT_BASE = """You are reviewing RCS top-1 candidate consistency.

Important:
- There is NO established ground-truth dataset in this project.
- Judge only whether `top1_name` is consistent with the original `query`.
- Do not compare against any previous LLM label.
- If the query is a compound structure and top1 covers only one part, label partial_or_narrower.

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
      "reason": "<max 220 chars>"
    }
  ]
}
"""

PROMPT_A = PROMPT_BASE + """
Bias: be strict. If a candidate is only a loose anatomical neighbor, label wrong.
"""
PROMPT_B = PROMPT_BASE + """
Bias: distinguish exact/synonym from parent fallback. Use broader_parent when
the candidate is anatomically a valid parent but not the exact query.
"""
PROMPT_C = PROMPT_BASE + """
Bias: expert conservative adjudication. Use ambiguous only when a human
neuroanatomy review is genuinely needed. Return pure JSON, no markdown.
"""

PASSES = [
    ("pass1", FLASH_MODEL, PROMPT_A),
    ("pass2", FLASH_MODEL, PROMPT_B),
    ("pass3", PRO_MODEL, PROMPT_C),
]


@dataclass
class QueryResult:
    dataset: str
    query: str
    top_homba_id: str
    top_name: str
    score: str
    methods: str
    matched_query: str
    matched_alias: str
    modifier_terms: str
    top3: list[dict[str, Any]]


def load_queries() -> list[tuple[str, str]]:
    """Return list of (dataset, query) deduped by structure_name per dataset."""
    out: list[tuple[str, str]] = []
    for dataset, path in (("corpus", CORPUS_CSV), ("species", SPECIES_CSV)):
        seen: set[str] = set()
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for row in csv.DictReader(fh):
                q = (row.get("structure_name") or "").strip()
                if not q or q in seen:
                    continue
                seen.add(q)
                out.append((dataset, q))
    return out


def run_rcs(rcs_dir: Path | None = None) -> list[QueryResult]:
    rcs_dir = rcs_dir or RCS_DIR
    generator = RosettaCandidateGenerator(
        HOMBA_CSV,
        token_rules_csv=rcs_dir / "homba_token_rules.csv",
        alias_rules_csv=rcs_dir / "homba_alias_rules.csv",
        abbrev_rules_csv=rcs_dir / "homba_abbrev_rules.csv",
    )
    results: list[QueryResult] = []
    for dataset, query in load_queries():
        cands = generator.generate(query, top_k=3)
        if not cands:
            results.append(QueryResult(dataset, query, "", "", "", "", "", "", "", []))
            continue
        top = cands[0]
        results.append(
            QueryResult(
                dataset=dataset,
                query=query,
                top_homba_id=str(top.get("homba_id", "")),
                top_name=str(top.get("name", "")),
                score=str(top.get("score", "")),
                methods=str(top.get("methods", "")),
                matched_query=str(top.get("matched_query", "")),
                matched_alias=str(top.get("matched_alias", "")),
                modifier_terms=str(top.get("modifier_terms", "")),
                top3=[
                    {"homba_id": c.get("homba_id"), "name": c.get("name"),
                     "score": c.get("score"), "methods": c.get("methods")}
                    for c in cands[:3]
                ],
            )
        )
    return results


def cache_key(dataset: str, query: str, top_id: str) -> str:
    return f"{dataset}||{query}||{top_id}"


def load_cache() -> dict[str, Any]:
    if CACHE_PATH.exists():
        return json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    return {}


def save_cache(cache: dict[str, Any]) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")


def extract_json_obj(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object found.")
    return json.loads(m.group(0))


def validate(batch: list[QueryResult], id_map: dict[int, QueryResult],
             obj: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(obj.get("results"), list):
        return False, "missing results[]"
    ids = set(id_map)
    seen = set()
    for item in obj["results"]:
        rid = item.get("record_id")
        if rid not in ids:
            return False, f"unknown record_id {rid}"
        if rid in seen:
            return False, f"duplicate record_id {rid}"
        seen.add(rid)
        if item.get("label") not in LABELS:
            return False, f"invalid label {item.get('label')!r}"
        if item.get("certainty") not in CERTAINTY:
            return False, f"invalid certainty {item.get('certainty')!r}"
        try:
            c = float(item.get("confidence"))
        except Exception:
            return False, f"invalid confidence {rid}"
        if not 0 <= c <= 1:
            return False, f"confidence out of range {rid}"
    if seen != ids:
        return False, f"missing ids {sorted(ids - seen)}"
    return True, ""


def call_deepseek(model: str, prompt: str, batch: list[QueryResult],
                  base_id: int, api_key: str, retries: int = 4) -> dict[str, Any]:
    id_map = {base_id + i: r for i, r in enumerate(batch)}
    payload_records = [
        {
            "record_id": rid,
            "dataset": r.dataset,
            "query": r.query,
            "top1_name": r.top_name,
            "top1_id": r.top_homba_id,
        }
        for rid, r in id_map.items()
    ]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Review these records.\nrecords="
             + json.dumps(payload_records, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 2400,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            obj = extract_json_obj(content)
            ok, why = validate(batch, id_map, obj)
            if not ok:
                raise ValueError(why)
            results = {}
            for item in obj["results"]:
                r = id_map[int(item["record_id"])]
                results[cache_key(r.dataset, r.query, r.top_homba_id)] = {
                    "label": item["label"],
                    "certainty": item["certainty"],
                    "confidence": float(item["confidence"]),
                    "reason": (item.get("reason") or "").strip(),
                }
            return {"ok": True, "results": results}
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:200]}"
        except Exception as exc:
            last_error = str(exc)
        time.sleep(min(2 ** attempt, 10))
    return {"ok": False, "error": last_error}


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def judge_pass(to_judge: list[QueryResult], pass_name: str, model: str,
               prompt: str, api_key: str, cache: dict[str, Any],
               batch_size: int, workers: int) -> int:
    """Judge all pairs missing this pass; write into cache[key][pass_name]."""
    pending = [
        r for r in to_judge
        if pass_name not in cache.get(cache_key(r.dataset, r.query, r.top_homba_id), {})
    ]
    if not pending:
        return 0
    batches = chunked(pending, batch_size)
    done = 0
    failures = 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {}
        for i, batch in enumerate(batches):
            futs[ex.submit(call_deepseek, model, prompt, batch, i * 1000, api_key)] = batch
        for fut in as_completed(futs):
            res = fut.result()
            if not res["ok"]:
                failures += 1
                continue
            for key, vote in res["results"].items():
                cache.setdefault(key, {})[pass_name] = vote
                done += 1
    print(f"  {pass_name}: judged={done} pending={len(pending)} failed_batches={failures}", flush=True)
    return done


def final_decision(p1: dict, p2: dict, p3: dict) -> dict[str, Any]:
    votes = [v for v in (p1, p2, p3) if v]
    labels = [v["label"] for v in votes]
    certainties = [v["certainty"] for v in votes]
    confidences = [float(v["confidence"]) for v in votes]
    if not labels:
        return {"label": "no_consensus", "certainty": "low", "confidence": 0.0,
                "agreement": "0/3", "has_disagreement": True,
                "vote_split_pattern": "missing", "uncertainty_tag": "api_missing"}
    counts = Counter(labels)
    label, count = counts.most_common(1)[0]
    avg_conf = sum(confidences) / len(confidences)
    has_disagreement = len(counts) > 1
    if count >= 2:
        certainty = "high" if count == 3 and avg_conf >= 0.8 else "medium"
        uncertainty = "stable" if count == 3 else "majority_vote"
        vote_split_pattern = "3-0" if count == 3 else "2-1"
    else:
        label = "no_consensus"
        certainty = "low"
        uncertainty = "split_vote"
        vote_split_pattern = "1-1-1"
    if "low" in certainties:
        uncertainty += "+low_certainty"
        if certainty == "high":
            certainty = "medium"
    return {"label": label, "certainty": certainty, "confidence": round(avg_conf, 4),
            "agreement": f"{count}/3", "has_disagreement": has_disagreement,
            "vote_split_pattern": vote_split_pattern, "uncertainty_tag": uncertainty}


def build_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def agg(subset: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "records": len(subset),
            "label_counts": dict(Counter(r["final_label"] for r in subset)),
            "certainty_counts": dict(Counter(r["final_certainty"] for r in subset)),
            "vote_split_pattern_counts": dict(Counter(r["vote_split_pattern"] for r in subset)),
        }
    corpus = [r for r in rows if r["dataset"] == "corpus"]
    species = [r for r in rows if r["dataset"] == "species"]
    return {
        "total_records": len(rows),
        "datasets": {"corpus": agg(corpus), "species": agg(species)},
        "overall": {
            "label_counts": dict(Counter(r["final_label"] for r in rows)),
            "certainty_counts": dict(Counter(r["final_certainty"] for r in rows)),
            "vote_split_pattern_counts": dict(Counter(r["vote_split_pattern"] for r in rows)),
            "uncertainty_tag_counts": dict(Counter(r["uncertainty_tag"] for r in rows)),
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tag", required=True, help="run name (runs/<tag>/)")
    parser.add_argument("--batch-size", type=int, default=6)
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--no-llm", action="store_true", help="RCS only, skip DeepSeek")
    args = parser.parse_args()

    out_dir = RUNS_DIR / args.tag
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"[{args.tag}] running RCS...", flush=True)
    results = run_rcs()
    print(f"  {len(results)} queries scored.", flush=True)

    cache = load_cache()

    if not args.no_llm:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY not set.", flush=True)
            return 2
        judgeable = [r for r in results if r.top_homba_id]
        for pass_name, model, prompt in PASSES:
            workers = args.workers if model == FLASH_MODEL else max(6, args.workers // 2)
            judge_pass(judgeable, pass_name, model, prompt, api_key, cache,
                       args.batch_size, workers)
            save_cache(cache)

    rows: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        key = cache_key(r.dataset, r.query, r.top_homba_id)
        votes = cache.get(key, {})
        p1, p2, p3 = votes.get("pass1", {}), votes.get("pass2", {}), votes.get("pass3", {})
        final = final_decision(p1, p2, p3)
        rows.append({
            "validation_id": i,
            "dataset": r.dataset,
            "query": r.query,
            "top_homba_id": r.top_homba_id,
            "top_name": r.top_name,
            "score": r.score,
            "methods": r.methods,
            "matched_query": r.matched_query,
            "matched_alias": r.matched_alias,
            "modifier_terms": r.modifier_terms,
            "top3": json.dumps(r.top3, ensure_ascii=False),
            "pass1_label": p1.get("label", ""), "pass1_reason": p1.get("reason", ""),
            "pass2_label": p2.get("label", ""), "pass2_reason": p2.get("reason", ""),
            "pass3_label": p3.get("label", ""), "pass3_reason": p3.get("reason", ""),
            "final_label": final["label"],
            "final_certainty": final["certainty"],
            "final_confidence": final["confidence"],
            "vote_agreement": final["agreement"],
            "vote_split_pattern": final["vote_split_pattern"],
            "uncertainty_tag": final["uncertainty_tag"],
        })

    csv_path = out_dir / "records.csv"
    with csv_path.open("w", newline="", encoding="utf-8-sig") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    summary = build_summary(rows)
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    overall = summary["overall"]["label_counts"]
    print(f"\n[{args.tag}] label counts: {overall}", flush=True)
    print(f"  wrong={overall.get('wrong', 0)} "
          f"partial={overall.get('partial_or_narrower', 0)} "
          f"aligned={overall.get('aligned', 0)} "
          f"broader_parent={overall.get('broader_parent', 0)}", flush=True)
    print(f"  wrote {csv_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
