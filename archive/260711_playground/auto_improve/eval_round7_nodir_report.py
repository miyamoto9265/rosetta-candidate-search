#!/usr/bin/env python3
"""baseline_nodir ↁEround7_nodir report (rcs_corpus_no_direction + species).

* Reuses ``runs/baseline_nodir`` (no baseline re-eval).
* Round7: RCS on no_direction corpus + species; DeepSeek only for uncached
  (dataset, query, top_id) pairs. Seeds from round6_nodir when top1 unchanged.
* Overwrites ``auto_improve_report_nodir.html``.
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
SPECIES_CSV = REPO / "build_testdata" / "rcs_species.csv"
RUNS = HERE / "runs"
OUT_BASE = RUNS / "baseline_nodir"
OUT_R7 = RUNS / "round7_nodir"
R6_NODIR = RUNS / "round6_nodir"
REPORT_OUT = HERE.parent / "top1_consistency_review" / "auto_improve_report_nodir.html"


def load_queries(path: Path) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
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


def run_rcs(pairs: list[tuple[str, str]]) -> list[eh.QueryResult]:
    gen = RosettaCandidateGenerator(eh.HOMBA_CSV)
    results: list[eh.QueryResult] = []
    for dataset, q in pairs:
        cands = gen.generate(q, top_k=3)
        if not cands:
            results.append(eh.QueryResult(dataset, q, "", "", "", "", "", "", "", []))
            continue
        top = cands[0]
        results.append(eh.QueryResult(
            dataset=dataset, query=q,
            top_homba_id=str(top.get("homba_id", "")),
            top_name=str(top.get("name", "")),
            score=str(top.get("score", "")),
            methods=str(top.get("methods", "")),
            matched_query=str(top.get("matched_query", "")),
            matched_alias=str(top.get("matched_alias", "")),
            modifier_terms=str(top.get("modifier_terms", "")),
            top3=[{
                "homba_id": c.get("homba_id"), "name": c.get("name"),
                "score": c.get("score"), "methods": c.get("methods"),
            } for c in cands],
        ))
    return results


def seed_from_prior(results: list[eh.QueryResult], prior_path: Path, cache: dict) -> int:
    if not prior_path.exists():
        return 0
    prior = {(r["dataset"], r["query"]): r for r in read_records(prior_path)}
    seeded = 0
    for r in results:
        old = prior.get((r.dataset, r.query))
        if not old or r.top_homba_id != old.get("top_homba_id"):
            continue
        key = eh.cache_key(r.dataset, r.query, r.top_homba_id)
        if {"pass1", "pass2", "pass3"} <= set(cache.get(key, {})):
            continue
        # Prefer copying real pass fields if present
        if old.get("pass1_label"):
            cache[key] = {
                "pass1": {"label": old["pass1_label"], "certainty": "high",
                          "confidence": 0.9, "reason": old.get("pass1_reason", "")},
                "pass2": {"label": old.get("pass2_label") or old["pass1_label"],
                          "certainty": "high", "confidence": 0.9,
                          "reason": old.get("pass2_reason", "")},
                "pass3": {"label": old.get("pass3_label") or old["final_label"],
                          "certainty": old.get("final_certainty") or "high",
                          "confidence": float(old.get("final_confidence") or 0.9),
                          "reason": old.get("pass3_reason", "")},
            }
        else:
            vote = {
                "label": old["final_label"],
                "certainty": old.get("final_certainty") or "high",
                "confidence": float(old.get("final_confidence") or 0.9),
                "reason": "seeded from prior run unchanged top1",
            }
            cache[key] = {"pass1": vote, "pass2": vote, "pass3": vote}
        seeded += 1
    return seeded


def rows_from_results(results: list[eh.QueryResult], cache: dict) -> list[dict[str, Any]]:
    rows = []
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

    if not (OUT_BASE / "records.csv").exists():
        print("baseline_nodir/records.csv missing; run eval_nodir_report.py first", flush=True)
        return 2

    nodir = load_queries(NODIR_CSV)
    species = load_queries(SPECIES_CSV)
    pairs = [("corpus", q) for q in nodir] + [("species", q) for q in species]
    print(f"[round7_nodir] engine=v{ENGINE_VERSION} "
          f"corpus={len(nodir)} species={len(species)}", flush=True)

    print("[round7_nodir] RCS...", flush=True)
    results = run_rcs(pairs)
    print(f"  scored {len(results)}", flush=True)

    cache = eh.load_cache()
    # alias ablation keys
    aliased = 0
    for key, val in list(cache.items()):
        if key.startswith("corpus_no_direction||"):
            alt = "corpus||" + key[len("corpus_no_direction||"):]
            if alt not in cache:
                cache[alt] = val
                aliased += 1
    seeded = seed_from_prior(results, R6_NODIR / "records.csv", cache)
    # also seed from baseline_nodir for unchanged top1 vs baseline (rare but free)
    seeded += seed_from_prior(results, OUT_BASE / "records.csv", cache)
    print(f"  cache alias={aliased} seeded={seeded}", flush=True)

    pending = [
        r for r in results if r.top_homba_id and not (
            {"pass1", "pass2", "pass3"}
            <= set(cache.get(eh.cache_key(r.dataset, r.query, r.top_homba_id), {}))
        )
    ]
    print(f"  DeepSeek pending={len(pending)} (workers={args.workers})", flush=True)
    if pending:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY not set", flush=True)
            return 2
        for pass_name, model, prompt in eh.PASSES:
            w = args.workers if model == eh.FLASH_MODEL else max(24, args.workers // 2)
            eh.judge_pass(pending, pass_name, model, prompt, api_key, cache,
                          args.batch_size, w)
            eh.save_cache(cache)

    rows = rows_from_results(results, cache)
    write_records(OUT_R7 / "records.csv", rows)
    (OUT_R7 / "summary.json").write_text(
        json.dumps(summarize(rows), ensure_ascii=False, indent=2), encoding="utf-8")

    base_rows = read_records(OUT_BASE / "records.csv")
    print(f"[baseline_nodir] n={len(base_rows)} "
          f"wrong={sum(1 for r in base_rows if r['final_label']=='wrong')}", flush=True)
    print(f"[round7_nodir] n={len(rows)} "
          f"wrong={sum(1 for r in rows if r['final_label']=='wrong')} "
          f"labels={dict(Counter(r['final_label'] for r in rows))}", flush=True)

    html = render_report("baseline_nodir", "round7_nodir")
    html = html.replace(
        "rcs_corpus.csv + rcs_species.csv",
        "rcs_corpus_no_direction.csv + rcs_species.csv",
    )
    html = html.replace("最絁E(round7_nodir)", "最絁E(round7 / no_direction corpus)")
    html = html.replace("エンジン v0.6.0", f"エンジン v{ENGINE_VERSION}")
    # generate_html_report may hardcode v0.6.0 in subtitle via engine from summary
    REPORT_OUT.write_text(html, encoding="utf-8")
    print(f"wrote {REPORT_OUT}", flush=True)
    print(f"elapsed={time.time() - t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
