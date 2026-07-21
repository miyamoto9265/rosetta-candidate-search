#!/usr/bin/env python3
"""Build baseline→round6 report using rcs_corpus_no_direction.csv.

Efficiency rules
----------------
* Do NOT re-judge baseline.  Project existing ``runs/baseline`` onto the
  no-direction query set (intersection only for corpus).
* Species rows are copied from existing baseline / round6 runs.
* Round6 corpus side: RCS on ``rcs_corpus_no_direction.csv`` only; DeepSeek
  only for (dataset, query, top_id) pairs missing from the judgement cache.
  Also reuse cache entries keyed as ``corpus_no_direction||…`` from the
  earlier ablation run.
* High DeepSeek concurrency (default 64).

Outputs
-------
runs/baseline_nodir/{records.csv,summary.json}
runs/round6_nodir/{records.csv,summary.json}
../top1_consistency_review/auto_improve_report_nodir.html
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, ENGINE_VERSION  # noqa: E402
import eval_harness as eh  # noqa: E402
from generate_html_report import render as render_report  # noqa: E402

NODIR_CSV = REPO / "build_testdata" / "rcs_corpus_no_direction.csv"
RUNS = HERE / "runs"
BASELINE_SRC = RUNS / "baseline"
ROUND6_SRC = RUNS / "round6"
OUT_BASE = RUNS / "baseline_nodir"
OUT_R6 = RUNS / "round6_nodir"
REPORT_OUT = HERE.parent / "top1_consistency_review" / "auto_improve_report_nodir.html"


def load_nodir_queries() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    with NODIR_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            q = (row.get("structure_name") or "").strip()
            if not q or q in seen:
                continue
            seen.add(q)
            out.append(q)
    return out


def read_records(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def write_records(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    def agg(subset: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "records": len(subset),
            "label_counts": dict(Counter(r["final_label"] for r in subset)),
            "certainty_counts": dict(Counter(r.get("final_certainty", "") for r in subset)),
            "vote_split_pattern_counts": dict(
                Counter(r.get("vote_split_pattern", "") for r in subset)),
        }

    corpus = [r for r in rows if r["dataset"] == "corpus"]
    species = [r for r in rows if r["dataset"] == "species"]
    return {
        "total_records": len(rows),
        "datasets": {"corpus": agg(corpus), "species": agg(species)},
        "overall": {
            "label_counts": dict(Counter(r["final_label"] for r in rows)),
            "certainty_counts": dict(Counter(r.get("final_certainty", "") for r in rows)),
            "vote_split_pattern_counts": dict(
                Counter(r.get("vote_split_pattern", "") for r in rows)),
            "uncertainty_tag_counts": dict(
                Counter(r.get("uncertainty_tag", "") for r in rows)),
        },
        "note": "corpus = rcs_corpus_no_direction.csv",
        "engine": ENGINE_VERSION,
    }


def build_baseline_nodir(nodir_queries: set[str]) -> list[dict[str, Any]]:
    """Reuse baseline records: all species + corpus ∩ no_direction."""
    rows = read_records(BASELINE_SRC / "records.csv")
    out = []
    for r in rows:
        if r["dataset"] == "species":
            out.append(r)
        elif r["dataset"] == "corpus" and r["query"] in nodir_queries:
            out.append(r)
    return out


def alias_cache_from_nodir(cache: dict[str, Any]) -> int:
    """Copy corpus_no_direction|| keys ↁEcorpus|| so shared judgements hit."""
    added = 0
    for key, val in list(cache.items()):
        if not key.startswith("corpus_no_direction||"):
            continue
        alt = "corpus||" + key[len("corpus_no_direction||"):]
        if alt not in cache:
            cache[alt] = val
            added += 1
    return added


def run_round6_corpus(nodir_queries: list[str]) -> list[eh.QueryResult]:
    gen = RosettaCandidateGenerator(eh.HOMBA_CSV)
    results: list[eh.QueryResult] = []
    for q in nodir_queries:
        cands = gen.generate(q, top_k=3)
        if not cands:
            results.append(eh.QueryResult("corpus", q, "", "", "", "", "", "", "", []))
            continue
        top = cands[0]
        results.append(
            eh.QueryResult(
                dataset="corpus",
                query=q,
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
                    for c in cands
                ],
            )
        )
    return results


def rows_from_query_results(
    results: list[eh.QueryResult], cache: dict[str, Any]
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for i, r in enumerate(results):
        key = eh.cache_key(r.dataset, r.query, r.top_homba_id)
        entry = cache.get(key, {})
        p1, p2, p3 = entry.get("pass1") or {}, entry.get("pass2") or {}, entry.get("pass3") or {}
        final = eh.final_decision(p1, p2, p3)
        rows.append({
            "validation_id": str(i),
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
            "pass1_label": p1.get("label", ""),
            "pass1_reason": p1.get("reason", ""),
            "pass2_label": p2.get("label", ""),
            "pass2_reason": p2.get("reason", ""),
            "pass3_label": p3.get("label", ""),
            "pass3_reason": p3.get("reason", ""),
            "final_label": final["label"],
            "final_certainty": final["certainty"],
            "final_confidence": final["confidence"],
            "vote_agreement": final["agreement"],
            "vote_split_pattern": final["vote_split_pattern"],
            "uncertainty_tag": final["uncertainty_tag"],
        })
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=64)
    ap.add_argument("--batch-size", type=int, default=6)
    args = ap.parse_args()

    t0 = time.time()
    nodir_list = load_nodir_queries()
    nodir_set = set(nodir_list)
    print(f"[nodir] queries={len(nodir_list)} engine=v{ENGINE_VERSION}", flush=True)

    # --- baseline projection (no LLM) ---
    base_rows = build_baseline_nodir(nodir_set)
    only_new = sorted(nodir_set - {r["query"] for r in base_rows if r["dataset"] == "corpus"})
    print(
        f"[baseline_nodir] reused={len(base_rows)} "
        f"(corpus∩={sum(1 for r in base_rows if r['dataset']=='corpus')}, "
        f"species={sum(1 for r in base_rows if r['dataset']=='species')}); "
        f"corpus-only-in-nodir (no baseline)={len(only_new)}: {only_new}",
        flush=True,
    )
    OUT_BASE.mkdir(parents=True, exist_ok=True)
    write_records(OUT_BASE / "records.csv", base_rows)
    (OUT_BASE / "summary.json").write_text(
        json.dumps(summarize(base_rows), ensure_ascii=False, indent=2), encoding="utf-8")

    # --- round6: species copy + corpus RCS ---
    print("[round6_nodir] RCS on corpus_no_direction...", flush=True)
    corpus_results = run_round6_corpus(nodir_list)
    print(f"  scored {len(corpus_results)}", flush=True)

    cache = eh.load_cache()
    aliased = alias_cache_from_nodir(cache)
    print(f"  aliased {aliased} cache keys corpus_no_direction→corpus", flush=True)

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY not set", flush=True)
        return 2

    # Only pairs missing from cache
    pending = [
        r for r in corpus_results
        if r.top_homba_id and not (
            "pass1" in cache.get(eh.cache_key(r.dataset, r.query, r.top_homba_id), {})
            and "pass2" in cache.get(eh.cache_key(r.dataset, r.query, r.top_homba_id), {})
            and "pass3" in cache.get(eh.cache_key(r.dataset, r.query, r.top_homba_id), {})
        )
    ]
    print(f"  DeepSeek pending={len(pending)} / {len(corpus_results)} (workers={args.workers})", flush=True)
    if pending:
        for pass_name, model, prompt in eh.PASSES:
            w = args.workers if model == eh.FLASH_MODEL else max(24, args.workers // 2)
            eh.judge_pass(pending, pass_name, model, prompt, api_key, cache,
                          args.batch_size, w)
            eh.save_cache(cache)

    corpus_rows = rows_from_query_results(corpus_results, cache)

    # species from existing round6
    r6_all = read_records(ROUND6_SRC / "records.csv")
    species_rows = [r for r in r6_all if r["dataset"] == "species"]
    # renumber validation_id
    round6_rows = corpus_rows + species_rows
    for i, r in enumerate(round6_rows):
        r["validation_id"] = str(i)

    OUT_R6.mkdir(parents=True, exist_ok=True)
    write_records(OUT_R6 / "records.csv", round6_rows)
    (OUT_R6 / "summary.json").write_text(
        json.dumps(summarize(round6_rows), ensure_ascii=False, indent=2), encoding="utf-8")

    wc = Counter(r["final_label"] for r in corpus_rows)
    bc = Counter(r["final_label"] for r in base_rows if r["dataset"] == "corpus")
    print(f"[corpus] baseline∩ labels={dict(bc)}", flush=True)
    print(f"[corpus] round6_nodir labels={dict(wc)}", flush=True)
    print(
        f"[overall] baseline_nodir n={len(base_rows)} "
        f"wrong={sum(1 for r in base_rows if r['final_label']=='wrong')} | "
        f"round6_nodir n={len(round6_rows)} "
        f"wrong={sum(1 for r in round6_rows if r['final_label']=='wrong')}",
        flush=True,
    )

    # HTML report (reuse generator; point at our tags)
    # Patch generate_html_report defaults by calling render directly after
    # ensuring runs/baseline_nodir and runs/round6_nodir exist (done).
    # generate_html_report.render reads RUNS / tag  Esame RUNS path.
    html = render_report("baseline_nodir", "round6_nodir")
    # Fix subtitle to mention no_direction corpus
    html = html.replace(
        "rcs_corpus.csv + rcs_species.csv",
        "rcs_corpus_no_direction.csv + rcs_species.csv",
    )
    html = html.replace(
        "最絁E(round6_nodir)",
        "最絁E(round6 / no_direction corpus)",
    )
    REPORT_OUT.write_text(html, encoding="utf-8")
    print(f"wrote {REPORT_OUT}", flush=True)
    print(f"elapsed={time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
