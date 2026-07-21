#!/usr/bin/env python3
"""Final round7 check: full-set top1 changes vs round6, flag wrong regressions.

Only judges newly changed (query, top_id) pairs. Does not attempt to fix
regressions.
"""
from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from rcs.rosetta_candidate_generator import RosettaCandidateGenerator, ENGINE_VERSION
import eval_harness as eh
from generate_wrong_report import ONTOLOGY_GAP_QUERIES

OUT = HERE / "runs" / "round7"


def is_gap(q: str) -> bool:
    gaps = ONTOLOGY_GAP_QUERIES
    return q in gaps or any(
        q.startswith(k + " ") or q.startswith(k + "(") or q.startswith(k + ",")
        for k in gaps
    )


def main() -> int:
    r6 = {
        (r["dataset"], r["query"]): r
        for r in csv.DictReader((HERE / "runs" / "round6" / "records.csv").open(encoding="utf-8-sig"))
    }
    print(f"[round7-full] engine=v{ENGINE_VERSION} loading generator...", flush=True)
    gen = RosettaCandidateGenerator(eh.HOMBA_CSV)
    results: list[eh.QueryResult] = []
    for (dataset, query), old in r6.items():
        cands = gen.generate(query, top_k=3)
        if not cands:
            results.append(eh.QueryResult(dataset, query, "", "", "", "", "", "", "", []))
            continue
        top = cands[0]
        results.append(eh.QueryResult(
            dataset=dataset, query=query,
            top_homba_id=str(top.get("homba_id", "")),
            top_name=str(top.get("name", "")),
            score=str(top.get("score", "")),
            methods=str(top.get("methods", "")),
            matched_query=str(top.get("matched_query", "")),
            matched_alias=str(top.get("matched_alias", "")),
            modifier_terms=str(top.get("modifier_terms", "")),
            top3=[{"homba_id": c.get("homba_id"), "name": c.get("name"),
                   "score": c.get("score"), "methods": c.get("methods")} for c in cands],
        ))
    print(f"  scored {len(results)}", flush=True)

    cache = eh.load_cache()
    # Seed labels for unchanged top1 from round6 records into a local map
    seeded: dict[str, dict] = {}
    for r in results:
        old = r6[(r.dataset, r.query)]
        if r.top_homba_id == old["top_homba_id"] and old.get("final_label"):
            key = eh.cache_key(r.dataset, r.query, r.top_homba_id)
            # ensure cache has passes if possible; else synthesize final-only via fake passes
            if key not in cache or "pass1" not in cache.get(key, {}):
                vote = {
                    "label": old["final_label"],
                    "certainty": old.get("final_certainty") or "high",
                    "confidence": float(old.get("final_confidence") or 0.9),
                    "reason": "seeded from round6 unchanged top1",
                }
                cache.setdefault(key, {})
                for p in ("pass1", "pass2", "pass3"):
                    cache[key].setdefault(p, vote)

    pending = [
        r for r in results if r.top_homba_id and not (
            {"pass1", "pass2", "pass3"}
            <= set(cache.get(eh.cache_key(r.dataset, r.query, r.top_homba_id), {}))
        )
    ]
    print(f"  DeepSeek pending={len(pending)}", flush=True)
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if pending:
        if not api_key:
            print("DEEPSEEK_API_KEY missing", flush=True)
            return 2
        for pass_name, model, prompt in eh.PASSES:
            w = 64 if model == eh.FLASH_MODEL else 32
            eh.judge_pass(pending, pass_name, model, prompt, api_key, cache, 6, w)
            eh.save_cache(cache)

    rows = []
    for r in results:
        key = eh.cache_key(r.dataset, r.query, r.top_homba_id)
        entry = cache.get(key, {})
        final = eh.final_decision(entry.get("pass1") or {}, entry.get("pass2") or {}, entry.get("pass3") or {})
        old = r6[(r.dataset, r.query)]
        rows.append({
            "dataset": r.dataset, "query": r.query,
            "top_homba_id": r.top_homba_id, "top_name": r.top_name,
            "final_label": final["label"],
            "round6_label": old["final_label"],
            "round6_top": old["top_name"],
            "top_changed": r.top_homba_id != old["top_homba_id"],
            "is_gap": is_gap(r.query),
            "was_fixable_wrong": old["final_label"] == "wrong" and not is_gap(r.query),
        })

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "summary.json").write_text(json.dumps({
        "engine": ENGINE_VERSION,
        "n": len(rows),
        "label_counts": dict(Counter(r["final_label"] for r in rows)),
        "round6_label_counts": dict(Counter(r["round6_label"] for r in rows)),
    }, indent=2), encoding="utf-8")

    # Wrong regressions outside the 43 fixable set:
    # was not wrong (or was gap wrong) in round6, now wrong in round7, and not in fixable-43 list
    fixable_qs = {(r["dataset"], r["query"]) for r in rows if r["was_fixable_wrong"]}
    # Actually was_fixable_wrong is based on round6; for regression we want queries that
    # were NOT among the 43 targeted fixes.
    targeted = {
        (r["dataset"], r["query"]) for r in rows
        if r6[(r["dataset"], r["query"])]["final_label"] == "wrong" and not is_gap(r["query"])
    }

    regressions = [
        r for r in rows
        if r["final_label"] == "wrong"
        and r["round6_label"] != "wrong"
        and (r["dataset"], r["query"]) not in targeted
    ]
    # also: was wrong-gap and still wrong is fine; was aligned and now wrong is regression
    print(f"[round7-full] labels={dict(Counter(r['final_label'] for r in rows))}", flush=True)
    print(f"[round7-full] round6 wrong={sum(1 for r in rows if r['round6_label']=='wrong')} "
          f"-> round7 wrong={sum(1 for r in rows if r['final_label']=='wrong')}", flush=True)
    print(f"[round7-full] wrong regressions (excl. targeted 43): {len(regressions)}", flush=True)
    for r in regressions:
        print(f"  REGRESS [{r['dataset']}] {r['query']}: "
              f"{r['round6_label']}({r['round6_top']}) -> wrong({r['top_name']})", flush=True)

    still_fixable_wrong = [
        r for r in rows
        if r["final_label"] == "wrong" and (r["dataset"], r["query"]) in targeted
    ]
    print(f"[round7-full] targeted-43 still wrong: {len(still_fixable_wrong)}/{len(targeted)}", flush=True)

    with (OUT / "regressions.txt").open("w", encoding="utf-8") as fh:
        fh.write(f"wrong regressions excl targeted43: {len(regressions)}\n")
        for r in regressions:
            fh.write(f"[{r['dataset']}] {r['query']}: {r['round6_label']} -> wrong ({r['top_name']})\n")
    print(f"wrote {OUT / 'summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
