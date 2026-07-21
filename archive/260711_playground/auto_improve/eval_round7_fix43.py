#!/usr/bin/env python3
"""Round7: evaluate only the 43 fixable round6-wrong queries."""
from __future__ import annotations

import csv
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, ENGINE_VERSION
import eval_harness as eh
from generate_wrong_report import ONTOLOGY_GAP_QUERIES

OUT = HERE / "runs" / "round7_fix43"


def fixable_queries_from_round6() -> list[tuple[str, str]]:
    gaps = set(ONTOLOGY_GAP_QUERIES)
    rows = list(csv.DictReader((HERE / "runs" / "round6" / "records.csv").open(encoding="utf-8-sig")))
    out = []
    for r in rows:
        if r["final_label"] != "wrong":
            continue
        q = r["query"]
        if q in gaps or any(
            q.startswith(k + " ") or q.startswith(k + "(") or q.startswith(k + ",")
            for k in gaps
        ):
            continue
        out.append((r["dataset"], q))
    return out


def main() -> int:
    queries = fixable_queries_from_round6()
    print(f"[round7] engine=v{ENGINE_VERSION} fixable={len(queries)}", flush=True)
    gen = RosettaCandidateGenerator(eh.HOMBA_CSV)
    results: list[eh.QueryResult] = []
    for dataset, q in queries:
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
        print(f"  [{dataset}] {q}\n    -> {top['name']} ({top['score']:.3f})", flush=True)

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY missing", flush=True)
        return 2
    cache = eh.load_cache()
    pending = [
        r for r in results if r.top_homba_id and not (
            {"pass1", "pass2", "pass3"}
            <= set(cache.get(eh.cache_key(r.dataset, r.query, r.top_homba_id), {}))
        )
    ]
    print(f"[round7] DeepSeek pending={len(pending)}/{len(results)}", flush=True)
    for pass_name, model, prompt in eh.PASSES:
        w = 64 if model == eh.FLASH_MODEL else 32
        eh.judge_pass(pending, pass_name, model, prompt, api_key, cache, 6, w)
        eh.save_cache(cache)

    rows = []
    for r in results:
        key = eh.cache_key(r.dataset, r.query, r.top_homba_id)
        entry = cache.get(key, {})
        final = eh.final_decision(entry.get("pass1") or {}, entry.get("pass2") or {}, entry.get("pass3") or {})
        rows.append({
            "dataset": r.dataset, "query": r.query,
            "top_homba_id": r.top_homba_id, "top_name": r.top_name,
            "score": r.score, "methods": r.methods,
            "final_label": final["label"],
            "pass1_label": (entry.get("pass1") or {}).get("label", ""),
            "pass3_label": (entry.get("pass3") or {}).get("label", ""),
            "pass3_reason": (entry.get("pass3") or {}).get("reason", ""),
            "top3": json.dumps(r.top3, ensure_ascii=False),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    # records.csv is gitignored pattern - write as fix43_records.csv
    out_csv = OUT / "fix43_records.csv"
    with out_csv.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    counts = Counter(r["final_label"] for r in rows)
    summary = {"n": len(rows), "label_counts": dict(counts), "engine": ENGINE_VERSION}
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    still_wrong = [r for r in rows if r["final_label"] == "wrong"]
    print(f"[round7] labels={dict(counts)}  still_wrong={len(still_wrong)}", flush=True)
    for r in still_wrong:
        print(f"  WRONG [{r['dataset']}] {r['query']} -> {r['top_name']}", flush=True)
    print(f"wrote {out_csv}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
