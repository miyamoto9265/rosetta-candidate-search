#!/usr/bin/env python3
"""improvement_02 evaluation harness.

Runs either the *production* RCS engine (baseline) or the *improved* local
engine (``rcs_engine.py``) over LLM-reviewed RCS buckets from round 1.

Important terminology
---------------------
Every mapping in this project is a provisional LLM visual review outcome.
The harness therefore uses names such as ``llm_accept_top1`` and
``llm_reject_top1`` to describe review buckets, without implying a
pre-established reference answer set.

Input files (all share dataset,query,...,top_homba_id columns):
  llm_review_inputs/1_highconf_correct.csv
      -> llm_accept_top1: LLM accepted the previous top-1 for this review pass.
  llm_review_inputs/2_highconf_incorrect.csv
      -> llm_check=correct_parent is tracked as llm_accept_top1 for regression
         only; wrong/questionable are tracked as llm_reject_top1.
  llm_review_inputs/3_unresolved_correct.csv
      -> llm_accept_top1 for this review pass.
  llm_review_inputs/4_unresolved_incorrect.csv
      -> B_algo/C_dict are llm_reject_top1; D_homba_gap/E_source_typo are
         llm_out_of_scope_for_rcs.

Usage:
  python eval.py baseline                 # production engine, prod dicts only
  python eval.py improved                 # local engine + playground dicts
  python eval.py compare                  # run both, write diff + metrics
  python eval.py search "query" [--improved]
"""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
PG_DIR = HERE.parent                    # 260621_playground
BUILD_TESTDATA = PG_DIR.parent          # ROSETTA
REPO_ROOT = BUILD_TESTDATA
RCS_DIR = REPO_ROOT / "rcs"
REVIEW_INPUT_DIR = HERE / "llm_review_inputs"
OUTPUT_DIR = HERE / "output"

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.review import review_flag_for  # noqa: E402

HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
PROD_ALIAS = RCS_DIR / "homba_alias_rules.csv"
PROD_ABBREV = RCS_DIR / "homba_abbrev_rules.csv"
PROD_TOKEN = RCS_DIR / "homba_token_rules.csv"

PG_ALIAS = HERE / "playground_alias_rules.csv"
PG_ABBREV = HERE / "playground_abbrev_rules.csv"
PG_TOKEN = HERE / "playground_token_rules.csv"

DATASETS = {
    "corpus": BUILD_TESTDATA / "rcs_corpus.csv",
    "species": BUILD_TESTDATA / "rcs_species.csv",
}


# ---------------------------------------------------------------------------
# Engine loading: baseline = installed rcs package; improved = local file.
# ---------------------------------------------------------------------------
def _load_engine(improved: bool):
    if not improved:
        from rcs.rosetta_candidate_generator import RosettaCandidateGenerator
        return RosettaCandidateGenerator
    spec = importlib.util.spec_from_file_location("rcs_engine", HERE / "rcs_engine.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["rcs_engine"] = mod  # required for @dataclass to resolve __module__
    spec.loader.exec_module(mod)
    return mod.RosettaCandidateGenerator


def _merge_csv(prod: Path, additions: Path | None, tmpdir: Path, name: str) -> Path:
    """Concatenate prod + playground dictionaries.

    Uses the UNION of column names so playground-only columns (e.g.
    ``bidirectional``) are preserved even when the production file lacks them.
    """
    all_rows: list[dict[str, str]] = []
    columns: list[str] = []
    for path in (prod, additions):
        if not path or not path.exists():
            continue
        with path.open(newline="", encoding="utf-8-sig") as fh:
            reader = csv.DictReader(fh)
            for col in reader.fieldnames or []:
                if col and col not in columns:
                    columns.append(col)
            for row in reader:
                if any((v or "").strip() for v in row.values()):
                    all_rows.append(row)
    out = tmpdir / name
    with out.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in all_rows:
            writer.writerow({c: row.get(c, "") for c in columns})
    return out


def build_generator(tmpdir: Path, *, improved: bool):
    Gen = _load_engine(improved)
    use_pg = improved
    alias = _merge_csv(PROD_ALIAS, PG_ALIAS if use_pg else None, tmpdir, "alias.csv")
    abbrev = _merge_csv(PROD_ABBREV, PG_ABBREV if use_pg else None, tmpdir, "abbrev.csv")
    token = _merge_csv(PROD_TOKEN, PG_TOKEN if use_pg else None, tmpdir, "token.csv")
    return Gen(
        HOMBA_CSV,
        token_rules_csv=token,
        alias_rules_csv=alias,
        abbrev_rules_csv=abbrev,
    )


# ---------------------------------------------------------------------------
# LLM review bucket loading
# ---------------------------------------------------------------------------
def _read(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_review_groups():
    """Return LLM review buckets keyed by (dataset, query)."""
    f1 = _read(REVIEW_INPUT_DIR / "1_highconf_correct.csv")
    f2 = _read(REVIEW_INPUT_DIR / "2_highconf_incorrect.csv")
    f3 = _read(REVIEW_INPUT_DIR / "3_unresolved_correct.csv")
    f4 = _read(REVIEW_INPUT_DIR / "4_unresolved_incorrect.csv")

    llm_accept_top1: dict[tuple[str, str], str] = {}
    llm_reject_top1: dict[tuple[str, str], dict] = {}
    llm_out_of_scope_for_rcs: dict[tuple[str, str], dict] = {}

    for r in f1:
        llm_accept_top1[(r["dataset"], r["query"])] = r["top_homba_id"]
    for r in f3:
        llm_accept_top1[(r["dataset"], r["query"])] = r["top_homba_id"]
    for r in f2:
        key = (r["dataset"], r["query"])
        chk = (r.get("llm_check") or "").strip()
        if chk == "correct_parent":
            # This is NOT a strict correct label. It only means the previous
            # top-1 was accepted as a parent/fallback in that LLM review pass.
            llm_accept_top1[key] = r["top_homba_id"]
        else:  # wrong / questionable
            llm_reject_top1[key] = {"old_id": r["top_homba_id"], "kind": f"highconf_{chk}"}
    for r in f4:
        key = (r["dataset"], r["query"])
        cat = (r.get("_category") or "").strip()
        if cat in ("B_algo", "C_dict"):
            llm_reject_top1[key] = {"old_id": r["top_homba_id"], "kind": cat}
        else:
            llm_out_of_scope_for_rcs[key] = {"old_id": r["top_homba_id"], "kind": cat}

    # Optional curated target-name substring map for a small manually reviewed
    # subset. These are review targets, not ground-truth labels.
    review_target_substrings: dict[tuple[str, str], str] = {}
    rtp = REVIEW_INPUT_DIR / "review_target_substrings.csv"
    if rtp.exists():
        for r in _read(rtp):
            review_target_substrings[(r["dataset"], r["query"])] = (
                r["review_target_name_substr"] or "").strip().lower()

    return llm_accept_top1, llm_reject_top1, llm_out_of_scope_for_rcs, review_target_substrings


def all_review_queries():
    queries = []
    seen = set()
    for fname in ("1_highconf_correct.csv", "2_highconf_incorrect.csv",
                  "3_unresolved_correct.csv", "4_unresolved_incorrect.csv"):
        for r in _read(REVIEW_INPUT_DIR / fname):
            key = (r["dataset"], r["query"])
            if key not in seen:
                seen.add(key)
                queries.append(key)
    return queries


# ---------------------------------------------------------------------------
# Evaluation
# ---------------------------------------------------------------------------
BASELINE_CACHE = OUTPUT_DIR / "baseline_results.json"


def _key(t: tuple[str, str]) -> str:
    return f"{t[0]}\t{t[1]}"


def _unkey(s: str) -> tuple[str, str]:
    a, b = s.split("\t", 1)
    return (a, b)


def get_baseline_results(force: bool = False) -> dict[tuple[str, str], dict]:
    """Reference snapshot = engine+dicts at the moment refresh was last run.

    Run ``refresh-baseline`` *before* editing rcs_engine.py / dict files to
    freeze the 'before' state; subsequent ``compare`` runs then show the delta
    introduced by the edits. Built with improved=True so the reference reflects
    the round3 production-engine + playground-dict state.
    """
    if not force and BASELINE_CACHE.exists():
        data = json.loads(BASELINE_CACHE.read_text(encoding="utf-8"))
        return {_unkey(k): v for k, v in data.items()}
    res = run_engine(improved=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    BASELINE_CACHE.write_text(
        json.dumps({_key(k): v for k, v in res.items()}, ensure_ascii=False, indent=0),
        encoding="utf-8")
    return res


def run_engine(improved: bool) -> dict[tuple[str, str], dict]:
    """Return {(dataset,query): top1-info-dict} for every reviewed query."""
    results: dict[tuple[str, str], dict] = {}
    with tempfile.TemporaryDirectory() as td:
        gen = build_generator(Path(td), improved=improved)
        for dataset, query in all_review_queries():
            cands = gen.generate(query, top_k=3)
            if cands:
                top = cands[0]
                flag = review_flag_for(top)
                results[(dataset, query)] = {
                    "id": top["homba_id"], "name": top["name"],
                    "score": float(top["score"]), "flag": flag,
                    "methods": top["methods"],
                    "rank2_name": cands[1]["name"] if len(cands) > 1 else "",
                    "rank2_score": float(cands[1]["score"]) if len(cands) > 1 else 0.0,
                }
            else:
                results[(dataset, query)] = {
                    "id": "", "name": "", "score": 0.0, "flag": "no_candidate",
                    "methods": "", "rank2_name": "", "rank2_score": 0.0,
                }
    return results


def metrics(results: dict, llm_accept_top1, llm_reject_top1,
            llm_out_of_scope_for_rcs, review_target_substrings) -> dict:
    accept_same_id = accept_changed_id = accept_high = 0
    changed_accept_list = []
    for key, review_reference_id in llm_accept_top1.items():
        r = results.get(key)
        if not r:
            continue
        if r["id"] == review_reference_id:
            accept_same_id += 1
            if r["flag"] == "high_confidence":
                accept_high += 1
        else:
            accept_changed_id += 1
            changed_accept_list.append(
                (key, review_reference_id, r["id"], r["name"], round(r["score"], 3)))

    reject_changed = target_matched = 0
    target_matched_list = []
    still_list = []
    for key, info in llm_reject_top1.items():
        r = results.get(key)
        if not r:
            continue
        changed = r["id"] != info["old_id"]
        if changed:
            reject_changed += 1
        substr = review_target_substrings.get(key)
        if substr and substr in (r["name"] or "").lower():
            target_matched += 1
            target_matched_list.append((key, r["name"], round(r["score"], 3)))
        elif substr:
            still_list.append((key, substr, r["name"], round(r["score"], 3)))

    flags = Counter(r["flag"] for r in results.values())
    return {
        "llm_accept_top1_total": len(llm_accept_top1),
        "llm_accept_top1_same_id": accept_same_id,
        "llm_accept_top1_changed_id": accept_changed_id,
        "llm_accept_top1_highconf": accept_high,
        "changed_accept_list": changed_accept_list,
        "llm_reject_top1_total": len(llm_reject_top1),
        "llm_reject_top1_changed": reject_changed,
        "curated_target_matched": target_matched,
        "target_matched_list": target_matched_list,
        "still_list": still_list,
        "llm_out_of_scope_for_rcs_total": len(llm_out_of_scope_for_rcs),
        "flags": dict(flags),
    }


def print_metrics(tag: str, m: dict) -> None:
    print(f"\n===== {tag} =====")
    print(f"llm_accept_top1: {m['llm_accept_top1_same_id']}/{m['llm_accept_top1_total']} "
          f"same id, {m['llm_accept_top1_changed_id']} changed id, "
          f"{m['llm_accept_top1_highconf']} high_confidence")
    print(f"llm_reject_top1: {m['llm_reject_top1_changed']}/{m['llm_reject_top1_total']} "
          f"changed top-1; curated target matches {m['curated_target_matched']}")
    fl = m["flags"]
    for f in ("high_confidence", "needs_review", "modifier_conflict", "low_confidence", "no_candidate"):
        print(f"  {f:18s} {fl.get(f, 0)}")


def cmd_baseline(args):
    accepted, rejected, out_scope, targets = load_review_groups()
    res = run_engine(improved=False)
    m = metrics(res, accepted, rejected, out_scope, targets)
    print_metrics("BASELINE (production engine, prod dicts)", m)


def cmd_improved(args):
    accepted, rejected, out_scope, targets = load_review_groups()
    res = run_engine(improved=True)
    m = metrics(res, accepted, rejected, out_scope, targets)
    print_metrics("IMPROVED (local engine + playground dicts)", m)
    if args.show_broken and m["changed_accept_list"]:
        print("\n-- LLM-accepted previous top-1 ids that changed --")
        for (ds, q), review_id, got_id, name, sc in m["changed_accept_list"]:
            print(f"  [{ds}] {q!r}: reviewed_top1_id {review_id} got {got_id} {name!r} ({sc})")


def cmd_baseline_refresh(args):
    get_baseline_results(force=True)
    print(f"Baseline cache written: {BASELINE_CACHE.name}")


def cmd_compare(args):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    accepted, rejected, out_scope, targets = load_review_groups()
    base = get_baseline_results(force=args.refresh_baseline)
    impr = run_engine(improved=True)
    mb = metrics(base, accepted, rejected, out_scope, targets)
    mi = metrics(impr, accepted, rejected, out_scope, targets)
    print_metrics("BASELINE", mb)
    print_metrics("IMPROVED", mi)

    # Per-query diff CSV (only rows where id/flag/score changed).
    diff_rows = []
    for key in all_review_queries():
        b = base[key]
        i = impr[key]
        if b["id"] != i["id"] or b["flag"] != i["flag"] or abs(b["score"] - i["score"]) > 1e-6:
            ds, q = key
            role = ("llm_accept_top1" if key in accepted else
                    "llm_reject_top1" if key in rejected else
                    "llm_out_of_scope_for_rcs" if key in out_scope else "other")
            diff_rows.append({
                "dataset": ds, "query": q, "role": role,
                "review_reference_top1_id": accepted.get(key, ""),
                "base_id": b["id"], "base_name": b["name"],
                "base_score": round(b["score"], 4), "base_flag": b["flag"],
                "impr_id": i["id"], "impr_name": i["name"],
                "impr_score": round(i["score"], 4), "impr_flag": i["flag"],
            })
    diff_path = OUTPUT_DIR / "diff_baseline_vs_improved.csv"
    with diff_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(diff_rows[0].keys()) if diff_rows else
                           ["dataset", "query"])
        w.writeheader()
        w.writerows(diff_rows)
    print(f"\nDiff rows: {len(diff_rows)} -> {diff_path.name}")

    summary = {"baseline": _clean(mb), "improved": _clean(mi)}
    (OUTPUT_DIR / "metrics.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8")
    print("Wrote metrics.json")


def _clean(m: dict) -> dict:
    return {k: v for k, v in m.items() if not k.endswith("_list")}


def cmd_export(args):
    """Write the improved top-1 for every reviewed query, annotated with the
    LLM review bucket and the change vs the cached baseline (round3 reference)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    accepted, rejected, out_scope, targets = load_review_groups()
    base = get_baseline_results()
    impr = run_engine(improved=True)
    rows = []
    for key in all_review_queries():
        ds, q = key
        b, i = base[key], impr[key]
        role = ("llm_accept_top1" if key in accepted else "llm_reject_top1" if key in rejected
                else "llm_out_of_scope_for_rcs" if key in out_scope else "other")
        review_id = accepted.get(key, "")
        rows.append({
            "dataset": ds, "query": q, "role": role,
            "review_reference_top1_id": review_id,
            "impr_id": i["id"], "impr_name": i["name"],
            "impr_score": round(i["score"], 4), "impr_flag": i["flag"],
            "changed_vs_baseline": "yes" if (b["id"] != i["id"] or b["flag"] != i["flag"]) else "",
            "base_id": b["id"], "base_name": b["name"],
            "base_score": round(b["score"], 4), "base_flag": b["flag"],
        })
    out = OUTPUT_DIR / "improved_full_results.csv"
    with out.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote {len(rows)} rows -> {out.name}")


def cmd_search(args):
    with tempfile.TemporaryDirectory() as td:
        gen = build_generator(Path(td), improved=args.improved)
        for c in gen.generate(args.query, top_k=args.top_k):
            print(f"  {c['score']:.3f}  {c['homba_id']:14s} {c['name']!r}  "
                  f"[{c['methods']}] alias={c['matched_alias']!r}")


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("baseline").set_defaults(func=cmd_baseline)
    sub.add_parser("refresh-baseline").set_defaults(func=cmd_baseline_refresh)
    pi = sub.add_parser("improved")
    pi.add_argument("--show-broken", action="store_true")
    pi.set_defaults(func=cmd_improved)
    pc = sub.add_parser("compare")
    pc.add_argument("--refresh-baseline", action="store_true")
    pc.set_defaults(func=cmd_compare)
    sub.add_parser("export").set_defaults(func=cmd_export)
    ps = sub.add_parser("search")
    ps.add_argument("query")
    ps.add_argument("--top-k", type=int, default=8)
    ps.add_argument("--improved", action="store_true")
    ps.set_defaults(func=cmd_search)
    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
