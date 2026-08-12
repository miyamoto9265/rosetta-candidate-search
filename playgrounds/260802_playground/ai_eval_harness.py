#!/usr/bin/env python3
"""AI-on vs AI-off RCS evaluation on the curated non-neocortex set.

Reuses round5 (AI-off) results. Runs AI-on (preprocess + postprocess) on all
queries, then 3-pass validates ONLY records whose top-1 differs between
AI-off and AI-on. Cheap + fair: unchanged records inherit the round5 label.

Relation-vs-judge consistency is also computed:
- "'=" should be aligned
- "<"  should be broader_parent
- ">"  should be partial_or_narrower

Usage (repo root):
    set DEEPSEEK_API_KEY=...
    python playgrounds/260802_playground/ai_eval_harness.py --stage all --workers 16
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "web" / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "web" / "backend"))

import ai_pipeline  # noqa: E402
from rcs.rosetta_candidate_generator import RosettaCandidateGenerator  # noqa: E402

RCS_DIR = REPO_ROOT / "rcs"
HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
INPUT_CSV = (
    REPO_ROOT / "build_testdata" / "rcs_projection_corpus_curated_non_neocortex.csv"
)
ROUND5_DIR = HERE / "runs" / "round5_abbrev"
OUT_DIR = HERE / "runs" / "ai_eval"
CACHE_DIR = HERE / "cache"
AI_RESULTS_PATH = OUT_DIR / "ai_results.json"
DIFF_JUDGE_CACHE = CACHE_DIR / "ai_eval_diff_judgements.json"

FLASH_MODEL = "deepseek-v4-flash"
API_URL = "https://api.deepseek.com/chat/completions"

LABELS = {
    "aligned",
    "broader_parent",
    "partial_or_narrower",
    "wrong",
    "ambiguous",
    "source_or_ontology_issue",
}

JUDGE_BASE = """You are reviewing top-1 candidate consistency for mammalian brain regions.

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
PROMPT_A = JUDGE_BASE + "\nBias: strict. Loose anatomical neighbors → wrong."
PROMPT_B = (
    JUDGE_BASE
    + "\nBias: distinguish exact/synonym from parent fallback. Use broader_parent "
    "when the candidate is a valid parent but not the exact query."
)
PROMPT_C = (
    JUDGE_BASE
    + "\nBias: expert conservative adjudication. Use ambiguous only when a human "
    "neuroanatomy review is genuinely needed. Pure JSON, no markdown."
)
PASSES = [
    ("pass1", FLASH_MODEL, PROMPT_A),
    ("pass2", FLASH_MODEL, PROMPT_B),
    ("pass3", FLASH_MODEL, PROMPT_C),
]

# relation -> expected judge label
RELATION_EXPECT = {
    "'=": "aligned",
    "<": "broader_parent",
    ">": "partial_or_narrower",
}


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--stage",
        choices=["ai", "judge", "report", "all"],
        default="all",
    )
    p.add_argument("--input", type=Path, default=INPUT_CSV)
    p.add_argument("--workers", type=int, default=16)
    p.add_argument("--batch-size", type=int, default=4)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--remap-ai", action="store_true")
    p.add_argument("--rejudge", action="store_true")
    return p.parse_args()


def _load_json(path: Path) -> Any:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return None


def _save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def load_queries(path: Path, limit: int = 0) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()

    def add(query: str, kind: str, structure: str, fullname: str, species: str, n: str) -> None:
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
                "structure_name": structure,
                "fullname": fullname,
                "species": species,
                "n_mentions": n,
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
            add(structure, "abbrev", structure, fullname, species, n_mentions)
            if fullname and fullname.casefold() != structure.casefold():
                add(fullname, "fullname", structure, fullname, species, n_mentions)
            if limit and len(rows) >= limit:
                break
    return rows


def qkey(qrow: dict[str, str]) -> str:
    return f"{qrow['dataset']}||{qrow['query']}"


# ---------------------------------------------------------------- AI-on run

def run_ai_on(queries: list[dict[str, str]], workers: int, remap: bool) -> dict[str, Any]:
    existing = {} if remap else (_load_json(AI_RESULTS_PATH) or {})
    gen = RosettaCandidateGenerator(
        HOMBA_CSV,
        token_rules_csv=RCS_DIR / "homba_token_rules.csv",
        alias_rules_csv=RCS_DIR / "homba_alias_rules.csv",
        abbrev_rules_csv=RCS_DIR / "homba_abbrev_rules.csv",
    )
    out: dict[str, Any] = dict(existing)
    pending = [q for q in queries if qkey(q) not in out]
    print(f"[ai] total={len(queries)} cached={len(existing)} pending={len(pending)}", flush=True)
    if not pending:
        return out

    def work(qrow: dict[str, str]) -> tuple[str, dict[str, Any]]:
        query = qrow["query"]
        pre = ai_pipeline.preprocess(query)
        search_q = pre["roi_query"] if not pre["error"] else query
        cands = gen.generate(search_q, top_k=10)
        post = ai_pipeline.postprocess(query, search_q, pre["removed"], cands)
        best = post["results"][0] if post["results"] else None
        return qkey(qrow), {
            "query": query,
            "roi_query": search_q,
            "removed": pre["removed"],
            "preprocess_error": pre["error"],
            "ai_results": post["results"],
            "ai_error": post["error"],
            "ai_best_id": (best or {}).get("homba_id", ""),
            "ai_best_name": (best or {}).get("name", ""),
            "ai_best_relation": (best or {}).get("relation", ""),
            "rcs_top1_id": str(cands[0].get("homba_id")) if cands else "",
            "rcs_top1_name": str(cands[0].get("name")) if cands else "",
        }

    done = 0
    with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
        futs = [ex.submit(work, q) for q in pending]
        for fut in as_completed(futs):
            k, v = fut.result()
            out[k] = v
            done += 1
            if done % 50 == 0 or done == len(pending):
                _save_json(AI_RESULTS_PATH, out)
                print(f"  AI {done}/{len(pending)}", flush=True)
    _save_json(AI_RESULTS_PATH, out)
    return out


# ---------------------------------------------------------------- judge diff

def _norm_item(item: dict[str, Any]) -> dict[str, Any] | None:
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
    }
    label = aliases.get(label, label)
    if label not in LABELS:
        return None
    cert = str(item.get("certainty") or "medium").strip().casefold()
    if cert not in {"high", "medium", "low"}:
        cert = "medium"
    try:
        conf = float(item.get("confidence", 0.5))
    except Exception:  # noqa: BLE001
        conf = 0.5
    return {
        "record_id": rid,
        "label": label,
        "certainty": cert,
        "confidence": min(1.0, max(0.0, conf)),
        "reason": str(item.get("reason") or "")[:220],
    }


def _extract_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if text.startswith("```"):
        import re as _re
        text = _re.sub(r"^```(?:json)?\s*", "", text)
        text = _re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    import re as _re
    m = _re.search(r"\{.*\}", text, _re.S)
    if not m:
        raise ValueError("no json")
    return json.loads(m.group(0))


def call_judge(
    prompt: str,
    batch: list[tuple[int, dict[str, Any]]],
    api_key: str,
    retries: int = 5,
) -> dict[str, Any]:
    payload = [
        {
            "record_id": rid,
            "query": rec["query"],
            "query_kind": rec["query_kind"],
            "structure_name": rec["structure_name"],
            "fullname": rec["fullname"],
            "top1_name": rec["judge_name"],
            "top1_id": rec["judge_id"],
        }
        for rid, rec in batch
    ]
    body = {
        "model": FLASH_MODEL,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Review these records.\nrecords=" + json.dumps(payload, ensure_ascii=False)},
        ],
        "temperature": 0,
        "max_tokens": 8192,
    }
    data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            API_URL,
            data=data_bytes,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            obj = _extract_json(data["choices"][0]["message"]["content"] or "")
            out: dict[int, dict[str, Any]] = {}
            for item in obj.get("results") or []:
                norm = _norm_item(item)
                if norm:
                    out[norm["record_id"]] = norm
            return {"ok": True, "results": out}
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}"
            time.sleep(min(2**attempt, 30) if exc.code in (429, 500, 502, 503) else min(2**attempt, 12))
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(min(2**attempt, 12))
    return {"ok": False, "error": last}


def judge_diff(
    diff_records: list[dict[str, Any]],
    workers: int,
    batch_size: int,
    rejudge: bool,
) -> dict[str, Any]:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY not set.", flush=True)
        return {}
    cache = {} if rejudge else (_load_json(DIFF_JUDGE_CACHE) or {})

    def ckey(rec: dict[str, Any]) -> str:
        return f"{rec['dataset']}||{rec['query']}||{rec['judge_id']}"

    for pass_name, _model, prompt in PASSES:
        pending = [r for r in diff_records if pass_name not in cache.get(ckey(r), {})]
        if not pending:
            continue
        batches = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]

        def run_batch(bi: int, batch: list[dict[str, Any]]) -> dict[str, Any]:
            keyed = [(bi * 1000 + j, r) for j, r in enumerate(batch)]
            res = call_judge(prompt, keyed, api_key)
            if not res.get("ok"):
                return {}
            out: dict[str, Any] = {}
            for j, r in enumerate(batch):
                rid = bi * 1000 + j
                if rid in res["results"]:
                    out[ckey(r)] = res["results"][rid]
            return out

        with ThreadPoolExecutor(max_workers=max(1, workers)) as ex:
            futs = {ex.submit(run_batch, bi, b): b for bi, b in enumerate(batches)}
            for fut in as_completed(futs):
                for k, v in fut.result().items():
                    cache.setdefault(k, {})[pass_name] = v
        _save_json(DIFF_JUDGE_CACHE, cache)
        covered = sum(1 for r in diff_records if pass_name in cache.get(ckey(r), {}))
        print(f"  {pass_name}: covered={covered}/{len(diff_records)}", flush=True)
    return cache


def _final_label(votes: dict[str, Any]) -> str:
    labels = [votes.get(p, {}).get("label") for p in ("pass1", "pass2", "pass3")]
    labels = [l for l in labels if l]
    if not labels:
        return "no_consensus"
    counts = Counter(labels)
    label, count = counts.most_common(1)[0]
    if len(labels) >= 2 and count >= 2:
        return label
    return "no_consensus"


# ---------------------------------------------------------------- report

def build_report(
    queries: list[dict[str, str]],
    round5_rows: list[dict[str, str]],
    ai_map: dict[str, Any],
    diff_cache: dict[str, Any],
) -> None:
    # index round5 by (dataset, query)
    r5: dict[str, dict[str, str]] = {}
    for row in round5_rows:
        r5[f"{row['dataset']}||{row['query']}"] = row

    records: list[dict[str, Any]] = []
    for q in queries:
        k = qkey(q)
        off = r5.get(k)
        ai = ai_map.get(k)
        if off is None or ai is None:
            continue
        off_label = off.get("final_label", "")
        off_id = off.get("top_homba_id", "")
        ai_id = ai.get("ai_best_id", "")
        ai_rel = ai.get("ai_best_relation", "")
        changed = bool(ai_id) and (ai_id != off_id)
        # AI-on final label: if unchanged, inherit off label; if changed, use diff judge
        if not changed:
            ai_label = off_label if off_id else off_label
            ai_judged = False
        else:
            ck = f"{q['dataset']}||{q['query']}||{ai_id}"
            ai_label = _final_label(diff_cache.get(ck, {}))
            ai_judged = True
        records.append(
            {
                "dataset": q["dataset"],
                "query_kind": q["query_kind"],
                "query": q["query"],
                "off_id": off_id,
                "off_name": off.get("top_name", ""),
                "off_label": off_label,
                "ai_id": ai_id,
                "ai_name": ai.get("ai_best_name", ""),
                "ai_relation": ai_rel,
                "ai_label": ai_label,
                "changed": changed,
                "ai_judged": ai_judged,
                "ai_error": ai.get("ai_error"),
                "preprocess_error": ai.get("preprocess_error"),
                "roi_query": ai.get("roi_query", ""),
                "removed": ai.get("removed", []),
                "ai_all": ai.get("ai_results", []),
                "ai_rcs_top1_name": ai.get("rcs_top1_name", ""),
            }
        )

    # aggregate
    def label_counts(recs: list[dict[str, Any]], field: str) -> dict[str, int]:
        return dict(Counter(r[field] for r in recs))

    def useful(recs: list[dict[str, Any]], field: str) -> int:
        return sum(1 for r in recs if r[field] in ("aligned", "broader_parent"))

    off_counts = label_counts(records, "off_label")
    ai_counts = label_counts(records, "ai_label")
    n = len(records)
    changed_recs = [r for r in records if r["changed"]]
    n_changed = len(changed_recs)

    # improvement among changed
    def score(lbl: str) -> int:
        return {
            "aligned": 3,
            "broader_parent": 2,
            "partial_or_narrower": 1,
            "wrong": 0,
            "source_or_ontology_issue": 0,
            "ambiguous": 0,
            "no_consensus": 0,
        }.get(lbl, 0)

    improved = sum(1 for r in changed_recs if score(r["ai_label"]) > score(r["off_label"]))
    regressed = sum(1 for r in changed_recs if score(r["ai_label"]) < score(r["off_label"]))
    same = n_changed - improved - regressed

    # relation consistency (changed + judged)
    rel_rows = [r for r in changed_recs if r["ai_judged"] and r["ai_relation"] in RELATION_EXPECT]
    rel_consistent = sum(
        1 for r in rel_rows if r["ai_label"] == RELATION_EXPECT[r["ai_relation"]]
    )
    rel_by = {}
    for rel in RELATION_EXPECT:
        sub = [r for r in rel_rows if r["ai_relation"] == rel]
        if sub:
            ok = sum(1 for r in sub if r["ai_label"] == RELATION_EXPECT[rel])
            rel_by[rel] = {"n": len(sub), "consistent": ok, "rate": round(ok / len(sub), 4)}

    # no_match handling: off_label source_or_ontology_issue with no off_id
    off_nomatch = sum(1 for r in records if not r["off_id"])
    ai_nomatch = sum(1 for r in records if not r["ai_id"])

    summary = {
        "n": n,
        "off_label_counts": off_counts,
        "ai_label_counts": ai_counts,
        "off_useful": useful(records, "off_label"),
        "ai_useful": useful(records, "ai_label"),
        "off_aligned": off_counts.get("aligned", 0),
        "ai_aligned": ai_counts.get("aligned", 0),
        "off_nomatch": off_nomatch,
        "ai_nomatch": ai_nomatch,
        "changed": n_changed,
        "improved": improved,
        "regressed": regressed,
        "same_label_changed": same,
        "relation_consistency": {
            "n": len(rel_rows),
            "consistent": rel_consistent,
            "rate": round(rel_consistent / len(rel_rows), 4) if rel_rows else None,
            "by_relation": rel_by,
        },
    }

    _save_json(OUT_DIR / "records.json", records)
    _save_json(OUT_DIR / "summary.json", summary)
    _write_html(records, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)


def _write_html(records: list[dict[str, Any]], s: dict[str, Any]) -> None:
    import html as _html

    def esc(x: Any) -> str:
        return _html.escape(str(x))

    PILL = {
        "aligned": "ok",
        "broader_parent": "parent",
        "partial_or_narrower": "warn",
        "wrong": "bad",
        "source_or_ontology_issue": "issue",
        "ambiguous": "unknown",
        "no_consensus": "soft",
        "no_match": "nm",
        "": "unknown",
    }

    def pill(label: str) -> str:
        cls = PILL.get(label, "unknown")
        return f"<span class='pill {cls}'>{esc(label or '(none)')}</span>"

    def delta_pill(d: int, good_when_down: bool = False) -> str:
        if d == 0:
            return "<span class='pill unknown'>0</span>"
        good = (d < 0) if good_when_down else (d > 0)
        cls = "ok" if good else "bad"
        return f"<span class='pill {cls}'>{'+' if d > 0 else ''}{d}</span>"

    LABEL_ORDER = [
        "aligned",
        "broader_parent",
        "partial_or_narrower",
        "wrong",
        "source_or_ontology_issue",
        "ambiguous",
        "no_consensus",
        "no_match",
    ]

    BAR_SEG = {
        "aligned": "ok",
        "broader_parent": "parent",
        "partial_or_narrower": "warn",
        "wrong": "bad",
        "source_or_ontology_issue": "issue",
        "ambiguous": "unknown",
        "no_consensus": "soft",
        "no_match": "nm",
    }

    def disp_label(label: str, hid: str) -> str:
        return label if hid else "no_match"

    def dist_bar_pair(subset: list[dict[str, Any]]) -> str:
        n = max(len(subset), 1)
        rows = []
        for tag, field, nm in (("AI off", "off_label", "off_id"), ("AI on", "ai_label", "ai_id")):
            counts = Counter(disp_label(r[field], r[nm]) for r in subset)
            segs = []
            for lab in LABEL_ORDER:
                c = counts.get(lab, 0)
                if not c:
                    continue
                segs.append(
                    f"<div class='bar-seg {BAR_SEG[lab]}' style='width:{c / n * 100:.2f}%' "
                    f"title='{esc(lab)}: {c}'></div>"
                )
            rows.append(
                f"<div class='bar-row'><div class='bar-tag'>{tag}</div>"
                f"<div class='bar'>{''.join(segs)}</div>"
                f"<div class='bar-note'>{esc(str(n))}件</div></div>"
            )
        return "".join(rows)

    def dist_table(subset: list[dict[str, Any]]) -> str:
        off_c = Counter(disp_label(r["off_label"], r["off_id"]) for r in subset)
        ai_c = Counter(disp_label(r["ai_label"], r["ai_id"]) for r in subset)
        rows = []
        for lab in LABEL_ORDER:
            o, a = off_c.get(lab, 0), ai_c.get(lab, 0)
            rows.append(
                f"<tr><td>{pill(lab)}</td><td class='num'>{o}</td>"
                f"<td class='num'>{a}</td><td class='num'>{delta_pill(a - o, good_when_down=(lab in ('wrong', 'ambiguous', 'source_or_ontology_issue', 'no_consensus', 'no_match')))}</td></tr>"
            )
        return (
            "<div class='table-wrap'><table><thead><tr>"
            "<th>label</th><th class='num'>AI off</th><th class='num'>AI on</th><th class='num'>Δ</th>"
            "</tr></thead><tbody>" + "".join(rows) + "</tbody></table></div>"
        )

    abbrev = [r for r in records if r["query_kind"] == "abbrev"]
    fullname = [r for r in records if r["query_kind"] == "fullname"]

    def score(lbl: str) -> int:
        return {
            "aligned": 3,
            "broader_parent": 2,
            "partial_or_narrower": 1,
        }.get(lbl, 0)

    changed = [r for r in records if r["changed"]]
    improved = [r for r in changed if score(r["ai_label"]) > score(r["off_label"])]
    regressed = [r for r in changed if score(r["ai_label"]) < score(r["off_label"])]

    def case_cell(label: str, name: str, hid: str, rel: str = "") -> str:
        if not hid:
            return f"{pill('no_match')}<div class='muted small'>(AI 該当なし)</div>"
        rel_html = f" <span class='rel'>{esc(rel)}</span>" if rel else ""
        return f"{pill(label)}{rel_html}<div class='muted small'>{esc(name)}</div>"

    def case_table(rows: list[dict[str, Any]], limit: int = 40) -> str:
        body_rows = "".join(
            "<tr>"
            f"<td>{esc(r['query_kind'])}</td>"
            f"<td class='query-cell'><code>{esc(r['query'])}</code></td>"
            f"<td>{case_cell(r['off_label'], r['off_name'], r['off_id'])}</td>"
            f"<td>{case_cell(r['ai_label'], r['ai_name'], r['ai_id'], r['ai_relation'])}</td>"
            "</tr>"
            for r in rows[:limit]
        )
        return (
            "<div class='table-wrap'><table><thead><tr>"
            "<th>kind</th><th>query</th><th>AI off</th><th>AI on</th>"
            "</tr></thead><tbody>" + body_rows + "</tbody></table></div>"
        )

    def card_delta(d: int, good_when_down: bool = False) -> str:
        if d == 0:
            return "<span class='delta-flat'>±0</span>"
        good = (d < 0) if good_when_down else (d > 0)
        cls = "delta-up" if good else "delta-down"
        return f"<span class='{cls}'>{'+' if d > 0 else ''}{d}</span>"

    # no_match transitions
    nm_recovered = [r for r in records if not r["off_id"] and r["ai_id"]]
    nm_rejected = [r for r in records if r["off_id"] and not r["ai_id"]]
    nm_both = sum(1 for r in records if not r["off_id"] and not r["ai_id"])

    def nm_recovered_table(rows: list[dict[str, Any]]) -> str:
        body_rows = "".join(
            "<tr>"
            f"<td class='query-cell'><code>{esc(r['query'])}</code></td>"
            f"<td>{case_cell(r['ai_label'], r['ai_name'], r['ai_id'], r['ai_relation'])}</td>"
            f"<td class='muted small'>{esc(r['roi_query'])}</td>"
            "</tr>"
            for r in rows
        )
        return (
            "<div class='table-wrap'><table><thead><tr>"
            "<th>query</th><th>AI on の最良（判定）</th><th>preprocess 後クエリ</th>"
            "</tr></thead><tbody>" + body_rows + "</tbody></table></div>"
        )

    def nm_rejected_table(rows: list[dict[str, Any]]) -> str:
        body_rows = "".join(
            "<tr>"
            f"<td class='query-cell'><code>{esc(r['query'])}</code></td>"
            f"<td>{case_cell(r['off_label'], r['off_name'], r['off_id'])}</td>"
            f"<td class='muted small'>RCS top1: {esc(r['ai_rcs_top1_name'])}<br>roi: {esc(r['roi_query'])}</td>"
            "</tr>"
            for r in rows
        )
        return (
            "<div class='table-wrap'><table><thead><tr>"
            "<th>query</th><th>AI off の top1（判定）</th><th>AI on の検索状況</th>"
            "</tr></thead><tbody>" + body_rows + "</tbody></table></div>"
        )

    rel = s["relation_consistency"]
    rel_rows_html = "".join(
        f"<tr><td><code>{esc(k)}</code></td><td class='muted'>{esc(RELATION_EXPECT[k])}</td>"
        f"<td class='num'>{v['n']}</td><td class='num'>{v['consistent']}</td>"
        f"<td class='num'>{v['rate']*100:.1f}%</td></tr>"
        for k, v in rel["by_relation"].items()
    )

    changed_all_html = "".join(
        "<tr>"
        f"<td class='query-cell'><code>{esc(r['query'])}</code></td>"
        f"<td>{case_cell(r['off_label'], r['off_name'], r['off_id'])}</td>"
        f"<td>{case_cell(r['ai_label'], r['ai_name'], r['ai_id'], r['ai_relation'])}</td>"
        "</tr>"
        for r in changed
    )

    body = f"""<!doctype html>
<html lang="ja">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI on/off 比較 — RCS AI 統合評価</title>
<style>
:root {{ --bg:#f4f6f9; --panel:#fff; --text:#1a2332; --muted:#667085; --line:#d8dee8;
  --ok:#0b7a4b; --parent:#2f6fed; --warn:#b7791f; --bad:#b42318; --issue:#7a3fb4; --unknown:#475467; }}
* {{ box-sizing:border-box; }}
body {{ margin:0; font-family:"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif; background:var(--bg); color:var(--text); }}
header {{ padding:28px 32px 20px; background:linear-gradient(135deg,#0f172a 0%,#1e3a5f 100%); color:#fff; }}
header h1 {{ margin:0 0 8px; font-size:24px; }}
header p {{ margin:0; color:#cbd5e1; max-width:1000px; line-height:1.65; font-size:14px; }}
main {{ padding:22px 32px 56px; max-width:1400px; margin:0 auto; }}
section {{ background:var(--panel); border:1px solid var(--line); border-radius:12px; padding:18px 20px; margin:0 0 16px; }}
h2 {{ margin:0 0 12px; font-size:18px; }}
h3 {{ margin:16px 0 8px; font-size:14px; color:var(--muted); }}
.cards {{ display:grid; grid-template-columns:repeat(4,minmax(140px,1fr)); gap:10px; margin:12px 0 4px; }}
.card {{ border:1px solid var(--line); border-radius:10px; padding:12px 14px; background:#fafbfd; }}
.card-title {{ color:var(--muted); font-size:12px; }}
.card-value {{ font-size:24px; font-weight:700; margin-top:2px; font-variant-numeric:tabular-nums; }}
.card-sub {{ color:var(--muted); font-size:12px; margin-top:2px; }}
.delta-up {{ color:var(--ok); font-weight:700; }}
.delta-down {{ color:var(--bad); font-weight:700; }}
.delta-flat {{ color:var(--muted); }}
table {{ width:100%; border-collapse:collapse; }}
th,td {{ border-bottom:1px solid var(--line); padding:8px 10px; text-align:left; vertical-align:top; font-size:13px; }}
th {{ background:#f2f4f7; font-size:12px; }}
.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
.muted {{ color:var(--muted); }} .small {{ font-size:12px; }}
.note {{ color:var(--muted); line-height:1.65; font-size:13px; }}
.pill {{ display:inline-block; padding:2px 8px; border-radius:999px; color:#fff; font-size:11px; font-weight:600; }}
.pill.ok {{ background:var(--ok); }} .pill.parent {{ background:var(--parent); }}
.pill.warn {{ background:var(--warn); }} .pill.bad {{ background:var(--bad); }}
.pill.issue {{ background:var(--issue); }} .pill.unknown {{ background:var(--unknown); }}
.pill.soft {{ background:#98a2b3; }} .pill.nm {{ background:#111827; }}
code {{ background:#eef2f6; border-radius:4px; padding:1px 5px; font-size:12px; }}
.query-cell {{ font-weight:600; }}
.table-wrap {{ max-height:480px; overflow:auto; border:1px solid var(--line); border-radius:10px; }}
.rel {{ font-weight:700; color:var(--parent); margin-left:4px; }}
ol.tight li {{ margin:6px 0; line-height:1.6; }}
.bar-row {{ display:grid; grid-template-columns:64px 1fr auto; gap:10px; align-items:center; margin:6px 0 10px; }}
.bar-tag {{ font-size:12px; font-weight:700; color:var(--muted); }}
.bar {{ display:flex; height:14px; background:#eef2f6; border-radius:999px; overflow:hidden; }}
.bar-seg.ok {{ background:var(--ok); }} .bar-seg.parent {{ background:var(--parent); }}
.bar-seg.warn {{ background:var(--warn); }} .bar-seg.bad {{ background:var(--bad); }}
.bar-seg.issue {{ background:var(--issue); }} .bar-seg.unknown {{ background:var(--unknown); }}
.bar-seg.soft {{ background:#98a2b3; }} .bar-seg.nm {{ background:#111827; }}
.bar-note {{ font-size:12px; color:var(--muted); white-space:nowrap; }}
.legend {{ display:flex; flex-wrap:wrap; gap:8px 14px; margin:8px 0 0; font-size:12px; color:var(--muted); }}
.legend span {{ display:inline-flex; align-items:center; gap:6px; }}
.dot {{ width:10px; height:10px; border-radius:50%; display:inline-block; }}
.dot.ok {{ background:var(--ok); }} .dot.parent {{ background:var(--parent); }}
.dot.warn {{ background:var(--warn); }} .dot.bad {{ background:var(--bad); }}
.dot.issue {{ background:var(--issue); }} .dot.unknown {{ background:var(--unknown); }}
.dot.soft {{ background:#98a2b3; }} .dot.nm {{ background:#111827; }}
</style>
</head>
<body>
<header>
  <h1>RCS AI 統合評価 — AI on / off 比較</h1>
  <p>
    AI off = round5（engine v0.8.5）の既存結果を流用。AI on = preprocess（本質外除去）+
    postprocess（候補裁定 0–4 件、relation <code>'=</code>/<code>&lt;</code>/<code>&gt;</code>）、
    モデルは deepseek-v4-flash。top1 が変わった {s['changed']} 件のみ Flash×3-pass で判定し、
    変更なしは round5 ラベルを継承（安価・平等）。n={s['n']}。
  </p>
</header>
<main>
<section>
  <h2>サマリー</h2>
  <div class="cards">
    <div class="card"><div class="card-title">aligned</div>
      <div class="card-value">{s['ai_aligned']}</div>
      <div class="card-sub">off {s['off_aligned']} → {card_delta(s['ai_aligned']-s['off_aligned'])}</div></div>
    <div class="card"><div class="card-title">useful (aligned+parent)</div>
      <div class="card-value">{s['ai_useful']}</div>
      <div class="card-sub">off {s['off_useful']} → {card_delta(s['ai_useful']-s['off_useful'])}</div></div>
    <div class="card"><div class="card-title">no_match（AI 該当なし）</div>
      <div class="card-value">{s['ai_nomatch']}</div>
      <div class="card-sub">off {s['off_nomatch']} → {card_delta(s['ai_nomatch']-s['off_nomatch'], good_when_down=True)}</div></div>
    <div class="card"><div class="card-title">AI changed top1 / 改善 / 悪化</div>
      <div class="card-value">{s['changed']} / <span class="delta-up">{s['improved']}</span> / <span class="delta-down">{s['regressed']}</span></div>
      <div class="card-sub">同ラベル {s['same_label_changed']}</div></div>
  </div>
  <h3>ラベル分布（全体）</h3>
  {dist_bar_pair(records)}
  <div class="legend">
    <span><span class="dot ok"></span>aligned</span>
    <span><span class="dot parent"></span>broader_parent</span>
    <span><span class="dot warn"></span>partial_or_narrower</span>
    <span><span class="dot bad"></span>wrong</span>
    <span><span class="dot issue"></span>source_or_ontology_issue</span>
    <span><span class="dot unknown"></span>ambiguous</span>
    <span><span class="dot soft"></span>no_consensus</span>
    <span><span class="dot nm"></span>no_match</span>
  </div>
  <h3>全体ラベル（AI off → AI on）数値表</h3>
  {dist_table(records)}
  <h3>abbrev のみ（数値）</h3>
  {dist_table(abbrev)}
  <h3>fullname のみ（数値）</h3>
  {dist_table(fullname)}
</section>

<section>
  <h2>Relation と 3-pass 判定の整合性</h2>
  <p class="note">
    AI の relation 主張が判定ラベルと一致するか。期待:
    <code>'=</code>→aligned、<code>&lt;</code>→broader_parent、<code>&gt;</code>→partial_or_narrower。
    全体 {rel['consistent']}/{rel['n']}（{rel['rate']*100:.1f}%）。
  </p>
  <div class="table-wrap"><table>
    <thead><tr><th>relation</th><th>期待ラベル</th><th class="num">n</th><th class="num">consistent</th><th class="num">rate</th></tr></thead>
    <tbody>{rel_rows_html}</tbody>
  </table></div>
</section>

<section>
  <h2>no_match の変化</h2>
  <p class="note">
    AI off で no_match だったものを AI が回復したケースと、
    AI off に候補があったのに AI が「妥当なし」（0 件）としたケース。
    両方 no_match は {nm_both} 件。
  </p>
  <h3>回復（off no_match → AI あり）: {len(nm_recovered)} 件</h3>
  {nm_recovered_table(nm_recovered) if nm_recovered else "<p class='note'>なし</p>"}
  <h3>脱落（off あり → AI no_match）: {len(nm_rejected)} 件</h3>
  {nm_rejected_table(nm_rejected) if nm_rejected else "<p class='note'>なし</p>"}
</section>

<section style="display:grid;grid-template-columns:1fr 1fr;gap:16px;padding:0;border:none;background:transparent">
  <div style="background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px">
    <h2>改善例（{len(improved)}）</h2>
    {case_table(improved)}
  </div>
  <div style="background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px 20px">
    <h2>悪化例（{len(regressed)}）</h2>
    {case_table(regressed)}
  </div>
</section>

<section>
  <h2>AI が top1 を変えた全レコード（{len(changed)}）</h2>
  <div class="table-wrap"><table>
    <thead><tr><th>query</th><th>AI off</th><th>AI on</th></tr></thead>
    <tbody>{changed_all_html}</tbody>
  </table></div>
</section>
</main>
</body>
</html>"""
    (OUT_DIR / "ai_eval_report.html").write_text(body, encoding="utf-8")


def main() -> int:
    args = parse_args()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    queries = load_queries(args.input, args.limit)
    print(f"queries={len(queries)}", flush=True)

    round5_rows: list[dict[str, str]] = []
    with (ROUND5_DIR / "validation_results.csv").open(encoding="utf-8-sig") as fh:
        round5_rows = list(csv.DictReader(fh))
    print(f"round5 rows={len(round5_rows)}", flush=True)

    ai_map: dict[str, Any] = {}
    if args.stage in ("ai", "all"):
        ai_map = run_ai_on(queries, args.workers, args.remap_ai)
    else:
        ai_map = _load_json(AI_RESULTS_PATH) or {}

    # build diff records
    r5: dict[str, dict[str, str]] = {}
    for row in round5_rows:
        r5[f"{row['dataset']}||{row['query']}"] = row

    diff_records: list[dict[str, Any]] = []
    for q in queries:
        k = qkey(q)
        off = r5.get(k)
        ai = ai_map.get(k)
        if off is None or ai is None:
            continue
        off_id = off.get("top_homba_id", "")
        ai_id = ai.get("ai_best_id", "")
        if ai_id and ai_id != off_id:
            diff_records.append(
                {
                    "dataset": q["dataset"],
                    "query": q["query"],
                    "query_kind": q["query_kind"],
                    "structure_name": q["structure_name"],
                    "fullname": q["fullname"],
                    "judge_id": ai_id,
                    "judge_name": ai.get("ai_best_name", ""),
                }
            )
    print(f"diff records={len(diff_records)}", flush=True)

    diff_cache: dict[str, Any] = {}
    if args.stage in ("judge", "all"):
        diff_cache = judge_diff(diff_records, args.workers, args.batch_size, args.rejudge)
    else:
        diff_cache = _load_json(DIFF_JUDGE_CACHE) or {}

    if args.stage in ("report", "all"):
        build_report(queries, round5_rows, ai_map, diff_cache)
        print(f"Report: {OUT_DIR / 'ai_eval_report.html'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
