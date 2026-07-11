#!/usr/bin/env python3
"""Ablate parent promotion (_promote_common_parents) without touching RCS source.

Compares WITH vs WITHOUT hierarchy parent promotion on:
  - build_testdata/rcs_core.csv              (ground-truth IDs → exact metrics)
  - build_testdata/rcs_corpus_no_direction.csv (DeepSeek 3-pass)
  - build_testdata/rcs_species.csv            (DeepSeek 3-pass)

The original ``rosetta_candidate_generator.py`` is never modified: the no-promotion
condition is implemented by monkey-patching ``_promote_common_parents`` to a no-op
on a live generator instance.

Usage
-----
    python ablate_parent_promotion.py --workers 24
    python ablate_parent_promotion.py --no-llm   # RCS + core metrics only
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
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(HERE))

from rcs.rosetta_candidate_generator import (  # noqa: E402
    ENGINE_VERSION,
    RosettaCandidateGenerator,
)
import eval_harness as eh  # noqa: E402

OUT_DIR = HERE / "runs" / "ablate_parent_promotion"

DATASETS = {
    "core": REPO / "build_testdata" / "rcs_core.csv",
    "corpus_no_direction": REPO / "build_testdata" / "rcs_corpus_no_direction.csv",
    "species": REPO / "build_testdata" / "rcs_species.csv",
}


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


def load_core_expected(path: Path) -> dict[str, dict[str, str]]:
    """query -> {expected_homba_id, expected_homba_name} (first occurrence wins)."""
    out: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            q = (row.get("structure_name") or "").strip()
            if not q or q in out:
                continue
            out[q] = {
                "expected_homba_id": (row.get("expected_homba_id") or "").strip(),
                "expected_homba_name": (row.get("expected_homba_name") or "").strip(),
            }
    return out


def run_condition(
    generator: RosettaCandidateGenerator,
    dataset: str,
    queries: list[str],
) -> list[eh.QueryResult]:
    results: list[eh.QueryResult] = []
    for query in queries:
        cands = generator.generate(query, top_k=3)
        if not cands:
            results.append(eh.QueryResult(dataset, query, "", "", "", "", "", "", "", []))
            continue
        top = cands[0]
        results.append(
            eh.QueryResult(
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


def noop_promote(self, *args, **kwargs) -> None:  # noqa: ANN001
    return None


def core_metrics(
    results: list[eh.QueryResult],
    expected: dict[str, dict[str, str]],
) -> dict[str, Any]:
    n = 0
    exact = 0
    in_top3 = 0
    misses: list[dict[str, str]] = []
    for r in results:
        exp = expected.get(r.query)
        if not exp or not exp["expected_homba_id"]:
            continue
        n += 1
        eid = exp["expected_homba_id"]
        top3_ids = [str(c.get("homba_id") or "") for c in r.top3]
        if r.top_homba_id == eid:
            exact += 1
        elif eid in top3_ids:
            in_top3 += 1
            misses.append({
                "query": r.query,
                "expected": exp["expected_homba_name"],
                "expected_id": eid,
                "top1": r.top_name,
                "top1_id": r.top_homba_id,
                "rank": "top2-3",
            })
        else:
            misses.append({
                "query": r.query,
                "expected": exp["expected_homba_name"],
                "expected_id": eid,
                "top1": r.top_name,
                "top1_id": r.top_homba_id,
                "rank": "miss",
            })
    return {
        "n": n,
        "exact": exact,
        "exact_rate": round(exact / n, 4) if n else 0.0,
        "in_top3": exact + in_top3,
        "in_top3_rate": round((exact + in_top3) / n, 4) if n else 0.0,
        "misses": misses,
    }


def judge_results(
    results: list[eh.QueryResult],
    cache: dict[str, Any],
    api_key: str,
    batch_size: int,
    workers: int,
) -> list[dict[str, Any]]:
    judgeable = [r for r in results if r.top_homba_id]
    for pass_name, model, prompt in eh.PASSES:
        w = workers if model == eh.FLASH_MODEL else max(6, workers // 2)
        eh.judge_pass(judgeable, pass_name, model, prompt, api_key, cache, batch_size, w)
        eh.save_cache(cache)

    rows: list[dict[str, Any]] = []
    for r in results:
        key = eh.cache_key(r.dataset, r.query, r.top_homba_id)
        entry = cache.get(key, {})
        p1 = entry.get("pass1") or {}
        p2 = entry.get("pass2") or {}
        p3 = entry.get("pass3") or {}
        final = eh.final_decision(p1, p2, p3)
        rows.append({
            "dataset": r.dataset,
            "query": r.query,
            "top_homba_id": r.top_homba_id,
            "top_name": r.top_name,
            "score": r.score,
            "methods": r.methods,
            "final_label": final["label"],
            "final_certainty": final["certainty"],
        })
    return rows


def label_counts(rows: list[dict[str, Any]]) -> Counter:
    return Counter(r["final_label"] for r in rows)


def compare_core_pairs(
    with_p: list[eh.QueryResult],
    without_p: list[eh.QueryResult],
    expected: dict[str, dict[str, str]],
) -> dict[str, Any]:
    by_q_with = {r.query: r for r in with_p}
    by_q_without = {r.query: r for r in without_p}
    changed = 0
    helped = 0   # without wrong/miss, with exact
    hurt = 0     # with wrong/miss relative to without exact
    same_top = 0
    details = []
    for q, exp in expected.items():
        eid = exp["expected_homba_id"]
        if not eid:
            continue
        a = by_q_with.get(q)
        b = by_q_without.get(q)
        if not a or not b:
            continue
        if a.top_homba_id == b.top_homba_id:
            same_top += 1
            continue
        changed += 1
        a_ok = a.top_homba_id == eid
        b_ok = b.top_homba_id == eid
        if a_ok and not b_ok:
            helped += 1
            tag = "promotion_helps"
        elif b_ok and not a_ok:
            hurt += 1
            tag = "promotion_hurts"
        else:
            tag = "both_wrong_or_swap"
        details.append({
            "query": q,
            "expected": exp["expected_homba_name"],
            "with_promotion": a.top_name,
            "without_promotion": b.top_name,
            "tag": tag,
        })
    return {
        "changed_top1": changed,
        "same_top1": same_top,
        "promotion_helps": helped,
        "promotion_hurts": hurt,
        "details": details,
    }


def compare_llm_pairs(
    with_rows: list[dict[str, Any]],
    without_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    rank = {
        "aligned": 5, "broader_parent": 4, "partial_or_narrower": 3,
        "no_consensus": 2, "ambiguous": 2, "source_or_ontology_issue": 2,
        "wrong": 1,
    }
    by_w = {(r["dataset"], r["query"]): r for r in with_rows}
    by_o = {(r["dataset"], r["query"]): r for r in without_rows}
    improved = 0  # without -> with is better
    regressed = 0
    changed = 0
    details = []
    for key, wr in by_w.items():
        o = by_o.get(key)
        if not o:
            continue
        if wr["top_homba_id"] != o["top_homba_id"]:
            changed += 1
        wl, ol = wr["final_label"], o["final_label"]
        if wl == ol:
            continue
        if rank.get(wl, 0) > rank.get(ol, 0):
            improved += 1
            tag = "promotion_better_label"
        else:
            regressed += 1
            tag = "promotion_worse_label"
        details.append({
            "dataset": key[0],
            "query": key[1],
            "without": f"{ol} ({o['top_name']})",
            "with": f"{wl} ({wr['top_name']})",
            "tag": tag,
        })
    return {
        "changed_top1": changed,
        "promotion_better_label": improved,
        "promotion_worse_label": regressed,
        "details": details,
    }


def write_txt_report(path: Path, payload: dict[str, Any]) -> None:
    lines: list[str] = []
    lines.append(f"Parent-promotion ablation  (engine v{ENGINE_VERSION})")
    lines.append("=" * 60)
    core = payload["core"]
    lines.append("\n## rcs_core.csv (ground-truth ID match)")
    lines.append(
        f"  WITH    exact={core['with']['exact']}/{core['with']['n']} "
        f"({core['with']['exact_rate']:.1%})  "
        f"top3={core['with']['in_top3_rate']:.1%}"
    )
    lines.append(
        f"  WITHOUT exact={core['without']['exact']}/{core['without']['n']} "
        f"({core['without']['exact_rate']:.1%})  "
        f"top3={core['without']['in_top3_rate']:.1%}"
    )
    delta_exact = core["with"]["exact"] - core["without"]["exact"]
    lines.append(f"  Δ exact (WITH - WITHOUT) = {delta_exact:+d}")
    cp = core["pair_compare"]
    lines.append(
        f"  top1 changed={cp['changed_top1']}  "
        f"promotion_helps={cp['promotion_helps']}  "
        f"promotion_hurts={cp['promotion_hurts']}"
    )
    if cp["details"]:
        lines.append("  changed cases:")
        for d in cp["details"]:
            lines.append(
                f"    [{d['tag']}] {d['query']}\n"
                f"      expected={d['expected']}\n"
                f"      WITH   ={d['with_promotion']}\n"
                f"      WITHOUT={d['without_promotion']}"
            )

    for ds in ("corpus_no_direction", "species"):
        block = payload.get(ds)
        if not block:
            continue
        lines.append(f"\n## {ds} (DeepSeek 3-pass)")
        for cond in ("with", "without"):
            lc = block[cond]["label_counts"]
            n = block[cond]["n"]
            lines.append(
                f"  {cond.upper():7s} n={n}  "
                f"aligned={lc.get('aligned', 0)}  "
                f"broader={lc.get('broader_parent', 0)}  "
                f"partial={lc.get('partial_or_narrower', 0)}  "
                f"wrong={lc.get('wrong', 0)}  "
                f"other={n - sum(lc.get(k, 0) for k in ('aligned','broader_parent','partial_or_narrower','wrong'))}"
            )
            good = lc.get("aligned", 0) + lc.get("broader_parent", 0)
            lines.append(
                f"          aligned+broader={good} ({good / n:.1%})  "
                f"wrong_rate={lc.get('wrong', 0) / n:.1%}"
            )
        pc = block["pair_compare"]
        lines.append(
            f"  top1 changed={pc['changed_top1']}  "
            f"promotion_better_label={pc['promotion_better_label']}  "
            f"promotion_worse_label={pc['promotion_worse_label']}"
        )
        if pc["details"]:
            lines.append("  label-changing cases (up to 40):")
            for d in pc["details"][:40]:
                lines.append(
                    f"    [{d['tag']}] [{d['dataset']}] {d['query']}\n"
                    f"      WITHOUT {d['without']}\n"
                    f"      WITH    {d['with']}"
                )

    lines.append("\n## Verdict")
    lines.append(payload.get("verdict", ""))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=24)
    ap.add_argument("--batch-size", type=int, default=6)
    ap.add_argument("--no-llm", action="store_true")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    print(f"[ablate] engine v{ENGINE_VERSION}", flush=True)
    print("[ablate] loading generator...", flush=True)
    gen = RosettaCandidateGenerator(eh.HOMBA_CSV)

    # --- WITH promotion (default) ---
    print("[ablate] running WITH parent promotion...", flush=True)
    with_by_ds: dict[str, list[eh.QueryResult]] = {}
    for name, path in DATASETS.items():
        qs = load_queries(path)
        with_by_ds[name] = run_condition(gen, name, qs)
        print(f"  {name}: {len(with_by_ds[name])} queries", flush=True)

    # --- WITHOUT promotion (monkey-patch; original source untouched) ---
    print("[ablate] monkey-patching _promote_common_parents → no-op...", flush=True)
    original = RosettaCandidateGenerator._promote_common_parents
    RosettaCandidateGenerator._promote_common_parents = noop_promote  # type: ignore[method-assign]
    try:
        without_by_ds: dict[str, list[eh.QueryResult]] = {}
        print("[ablate] running WITHOUT parent promotion...", flush=True)
        for name, path in DATASETS.items():
            qs = load_queries(path)
            without_by_ds[name] = run_condition(gen, name, qs)
            print(f"  {name}: {len(without_by_ds[name])} queries", flush=True)
    finally:
        RosettaCandidateGenerator._promote_common_parents = original  # type: ignore[method-assign]
        print("[ablate] restored _promote_common_parents", flush=True)

    payload: dict[str, Any] = {"engine": ENGINE_VERSION}

    # --- core ground-truth ---
    expected = load_core_expected(DATASETS["core"])
    core_with = core_metrics(with_by_ds["core"], expected)
    core_without = core_metrics(without_by_ds["core"], expected)
    payload["core"] = {
        "with": {k: v for k, v in core_with.items() if k != "misses"},
        "without": {k: v for k, v in core_without.items() if k != "misses"},
        "pair_compare": compare_core_pairs(
            with_by_ds["core"], without_by_ds["core"], expected),
        "with_misses": core_with["misses"],
        "without_misses": core_without["misses"],
    }
    print(
        f"[core] WITH exact={core_with['exact_rate']:.1%}  "
        f"WITHOUT exact={core_without['exact_rate']:.1%}  "
        f"Δ={core_with['exact'] - core_without['exact']:+d}",
        flush=True,
    )

    # --- LLM datasets ---
    if not args.no_llm:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY not set; skip LLM datasets.", flush=True)
            return 2
        cache = eh.load_cache()
        for name in ("corpus_no_direction", "species"):
            print(f"[ablate] DeepSeek judging {name} WITH...", flush=True)
            with_rows = judge_results(
                with_by_ds[name], cache, api_key, args.batch_size, args.workers)
            print(f"[ablate] DeepSeek judging {name} WITHOUT...", flush=True)
            without_rows = judge_results(
                without_by_ds[name], cache, api_key, args.batch_size, args.workers)
            wc, oc = label_counts(with_rows), label_counts(without_rows)
            payload[name] = {
                "with": {"n": len(with_rows), "label_counts": dict(wc)},
                "without": {"n": len(without_rows), "label_counts": dict(oc)},
                "pair_compare": compare_llm_pairs(with_rows, without_rows),
            }
            print(
                f"[{name}] WITH wrong={wc.get('wrong', 0)} aligned+broader="
                f"{wc.get('aligned', 0) + wc.get('broader_parent', 0)}  |  "
                f"WITHOUT wrong={oc.get('wrong', 0)} aligned+broader="
                f"{oc.get('aligned', 0) + oc.get('broader_parent', 0)}",
                flush=True,
            )

    # --- verdict ---
    d_exact = core_with["exact"] - core_without["exact"]
    helps = payload["core"]["pair_compare"]["promotion_helps"]
    hurts = payload["core"]["pair_compare"]["promotion_hurts"]
    verdict_parts = [
        f"rcs_core: parent promotion changes exact matches by {d_exact:+d} "
        f"(helps {helps} / hurts {hurts} among changed top-1).",
    ]
    for name in ("corpus_no_direction", "species"):
        if name not in payload:
            continue
        w = payload[name]["with"]["label_counts"]
        o = payload[name]["without"]["label_counts"]
        wg = w.get("aligned", 0) + w.get("broader_parent", 0)
        og = o.get("aligned", 0) + o.get("broader_parent", 0)
        verdict_parts.append(
            f"{name}: WITH aligned+broader={wg} wrong={w.get('wrong', 0)}; "
            f"WITHOUT aligned+broader={og} wrong={o.get('wrong', 0)} "
            f"(Δgood={wg - og:+d}, Δwrong={w.get('wrong', 0) - o.get('wrong', 0):+d})."
        )
    if d_exact >= 0 and all(
        payload.get(n, {}).get("with", {}).get("label_counts", {}).get("wrong", 0)
        <= payload.get(n, {}).get("without", {}).get("label_counts", {}).get("wrong", 9999)
        for n in ("corpus_no_direction", "species")
        if n in payload
    ):
        verdict_parts.append(
            "Overall: removing parent promotion does NOT improve results; "
            "keep promotion (net neutral-to-positive)."
        )
    else:
        verdict_parts.append(
            "Overall: mixed — inspect per-dataset Δ; promotion may help some sets and hurt others."
        )
    payload["verdict"] = " ".join(verdict_parts)
    payload["elapsed_sec"] = round(time.time() - t0, 1)

    json_path = OUT_DIR / "summary.json"
    txt_path = OUT_DIR / "report.txt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_txt_report(txt_path, payload)
    print(f"\n[ablate] wrote {json_path}", flush=True)
    print(f"[ablate] wrote {txt_path}", flush=True)
    print(payload["verdict"], flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
