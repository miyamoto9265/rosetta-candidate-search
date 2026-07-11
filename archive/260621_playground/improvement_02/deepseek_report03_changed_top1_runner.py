#!/usr/bin/env python3
"""Report 03 DeepSeek review for the 55 changed top-1 records.

This review intentionally ignores previous improvement-comparison labels.
It re-evaluates only records whose top-1 changed between baseline and
improvement_02, using three independent API passes:

  pass_1: deepseek-v4-flash, prompt A
  pass_2: deepseek-v4-flash, prompt B
  pass_3: deepseek-v4-pro,   prompt C

The recent absolute top-1 consistency review is joined as reference context for
the baseline candidate, but the improvement judgment is newly generated from
query + baseline candidate + improved candidate.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
FULL_RESULTS_CSV = OUT / "improved_full_results.csv"
CHANGED_TOP1_CSV = OUT / "deepseek_review" / "changed_top1_with_deepseek.csv"
ABS_CSV = OUT / "top1_consistency_review" / "all_records_top1_consistency.csv"
REVIEW_DIR = OUT / "report_03_changed_top1_review"
API_URL = "https://api.deepseek.com/chat/completions"
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"

CONSISTENCY_LABELS = {
    "aligned",
    "broader_parent",
    "partial_or_narrower",
    "wrong",
    "ambiguous",
    "source_or_ontology_issue",
}

IMPROVEMENT_LABELS = {
    "improved_better",
    "improved_worse",
    "no_material_change",
    "both_wrong",
    "needs_human_review",
    "homba_gap_or_source_issue",
}

CERTAINTY = {"high", "medium", "low"}


PROMPT_BASE = """You are re-reviewing changed RCS top-1 candidates.

Important:
- This is an independent Report 03 review.
- Ignore all previous improvement-comparison judgments.
- Judge only these three fields: original query, baseline top-1 candidate,
  and improved top-1 candidate.
- The optional baseline_abs_reference is a prior absolute LLM consistency
  review of the baseline candidate. It is context only, not ground truth.

For each record:
1. Assign baseline_consistency_label.
2. Assign improved_consistency_label.
3. Assign improvement_label.

Consistency labels:
- aligned: candidate directly names the same structure, accepted synonym, or
  same named entity.
- broader_parent: candidate is broader than the query but anatomically the
  right parent/container.
- partial_or_narrower: candidate covers only part of a compound query, or is
  too narrow for the query.
- wrong: candidate is anatomically different/off-structure/off-lobe.
- ambiguous: multiple plausible interpretations; cannot decide confidently.
- source_or_ontology_issue: source spelling/granularity or HOMBA coverage makes
  strict judgment inappropriate.

Improvement labels:
- improved_better: improved candidate is meaningfully closer or more correct.
- improved_worse: improved candidate is meaningfully farther or less correct.
- no_material_change: both candidates are effectively equivalent, or both are
  acceptable with no clear material preference.
- both_wrong: both candidates are wrong for the query.
- needs_human_review: uncertain or specialist judgment needed.
- homba_gap_or_source_issue: source or HOMBA granularity dominates the case.

Return STRICT JSON only:
{
  "results": [
    {
      "record_id": <int>,
      "baseline_consistency_label": "<consistency label>",
      "improved_consistency_label": "<consistency label>",
      "improvement_label": "<improvement label>",
      "certainty": "high|medium|low",
      "confidence": <float 0..1>,
      "reason": "<max 260 chars>"
    }
  ]
}
"""

PROMPT_A = PROMPT_BASE + """
Bias: be strict. Prefer improved_better only when the improved candidate is
clearly closer to the query, not merely different.
"""

PROMPT_B = PROMPT_BASE + """
Bias: compare specificity carefully. Moving from a valid parent to a more
specific exact structure is better; moving from an exact/compound structure to
only one component is worse.
"""

PROMPT_C = PROMPT_BASE + """
Bias: expert conservative adjudication. Use no_material_change for equivalent
or similarly acceptable candidates. Return pure JSON, no markdown fences.
"""


@dataclass(frozen=True)
class Record:
    record_id: int
    dataset: str
    query: str
    role: str
    baseline_top1_id: str
    baseline_top1_name: str
    baseline_score: str
    baseline_flag: str
    improved_top1_id: str
    improved_top1_name: str
    improved_score: str
    improved_flag: str
    baseline_abs_label: str
    baseline_abs_certainty: str
    baseline_abs_reason: str


def load_abs_review() -> dict[tuple[str, str, str, str], dict[str, str]]:
    out: dict[tuple[str, str, str, str], dict[str, str]] = {}
    with ABS_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            key = (
                row.get("dataset", ""),
                row.get("query", ""),
                row.get("top_homba_id", ""),
                row.get("top_name", ""),
            )
            out[key] = row
    return out


def load_records() -> list[Record]:
    abs_review = load_abs_review()
    records: list[Record] = []
    full_index: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    with FULL_RESULTS_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            full_index[
                (
                    row.get("dataset", ""),
                    row.get("query", ""),
                    row.get("role", ""),
                    row.get("base_id", ""),
                    row.get("impr_id", ""),
                )
            ] = row

    with CHANGED_TOP1_CSV.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            key = (
                row.get("dataset", ""),
                row.get("query", ""),
                row.get("baseline_top1_id", ""),
                row.get("baseline_top1_name", ""),
            )
            abs_row = abs_review.get(key, {})
            full_row = full_index.get(
                (
                    row.get("dataset", ""),
                    row.get("query", ""),
                    row.get("role", ""),
                    row.get("baseline_top1_id", ""),
                    row.get("improved_top1_id", ""),
                ),
                {},
            )
            records.append(
                Record(
                    record_id=len(records),
                    dataset=row.get("dataset", ""),
                    query=row.get("query", ""),
                    role=row.get("role", ""),
                    baseline_top1_id=row.get("baseline_top1_id", ""),
                    baseline_top1_name=row.get("baseline_top1_name", ""),
                    baseline_score=full_row.get("base_score", ""),
                    baseline_flag=row.get("baseline_flag", ""),
                    improved_top1_id=row.get("improved_top1_id", ""),
                    improved_top1_name=row.get("improved_top1_name", ""),
                    improved_score=full_row.get("impr_score", ""),
                    improved_flag=row.get("improved_flag", ""),
                    baseline_abs_label=abs_row.get("final_consistency_label", ""),
                    baseline_abs_certainty=abs_row.get("final_certainty", ""),
                    baseline_abs_reason=abs_row.get("final_reason", ""),
                )
            )
    return records


def chunked(items: list[Record], size: int) -> list[list[Record]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def extract_json_obj(text: str) -> dict[str, Any]:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", text, re.S)
    if not match:
        raise ValueError("No JSON object found")
    return json.loads(match.group(0))


def validate(batch: list[Record], obj: dict[str, Any]) -> tuple[bool, str]:
    results = obj.get("results")
    if not isinstance(results, list):
        return False, "missing results[]"
    ids = {r.record_id for r in batch}
    seen = set()
    for item in results:
        rid = item.get("record_id")
        if rid not in ids:
            return False, f"unknown record_id {rid}"
        if rid in seen:
            return False, f"duplicate record_id {rid}"
        seen.add(rid)
        if item.get("baseline_consistency_label") not in CONSISTENCY_LABELS:
            return False, f"invalid baseline label {item.get('baseline_consistency_label')!r}"
        if item.get("improved_consistency_label") not in CONSISTENCY_LABELS:
            return False, f"invalid improved label {item.get('improved_consistency_label')!r}"
        if item.get("improvement_label") not in IMPROVEMENT_LABELS:
            return False, f"invalid improvement label {item.get('improvement_label')!r}"
        if item.get("certainty") not in CERTAINTY:
            return False, f"invalid certainty {item.get('certainty')!r}"
        try:
            confidence = float(item.get("confidence"))
        except Exception:  # noqa: BLE001
            return False, f"invalid confidence {rid}"
        if not 0 <= confidence <= 1:
            return False, f"confidence out of range {rid}"
    if seen != ids:
        return False, f"missing ids {sorted(ids - seen)}"
    return True, ""


def call_deepseek(model: str, prompt: str, batch: list[Record], api_key: str,
                  retries: int = 3) -> dict[str, Any]:
    payload_records = [
        {
            "record_id": r.record_id,
            "dataset": r.dataset,
            "query": r.query,
            "role": r.role,
            "baseline_top1_name": r.baseline_top1_name,
            "baseline_top1_id": r.baseline_top1_id,
            "baseline_score": r.baseline_score,
            "baseline_flag": r.baseline_flag,
            "baseline_abs_reference": {
                "label": r.baseline_abs_label,
                "certainty": r.baseline_abs_certainty,
            },
            "improved_top1_name": r.improved_top1_name,
            "improved_top1_id": r.improved_top1_id,
            "improved_score": r.improved_score,
            "improved_flag": r.improved_flag,
        }
        for r in batch
    ]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Review records=" + json.dumps(payload_records, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "max_tokens": 2600,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_error = ""
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            obj = extract_json_obj(content)
            ok, why = validate(batch, obj)
            if not ok:
                raise ValueError(why)
            return {"ok": True, "response": obj, "usage": data.get("usage", {})}
        except urllib.error.HTTPError as exc:
            last_error = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}"
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
        time.sleep(min(2 ** attempt, 8))
    return {"ok": False, "error": last_error}


def run_pass(records: list[Record], model: str, prompt: str, api_key: str,
             pass_name: str, batch_size: int, workers: int) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    outputs: dict[int, dict[str, Any]] = {}
    logs: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = {
            ex.submit(call_deepseek, model, prompt, batch, api_key): batch
            for batch in chunked(records, batch_size)
        }
        for fut in as_completed(futures):
            batch = futures[fut]
            ids = [r.record_id for r in batch]
            res = fut.result()
            if not res["ok"]:
                logs.append({"pass": pass_name, "model": model, "record_ids": ids, "ok": False, "error": res["error"]})
                continue
            for item in res["response"]["results"]:
                outputs[int(item["record_id"])] = {
                    "baseline_consistency_label": item["baseline_consistency_label"],
                    "improved_consistency_label": item["improved_consistency_label"],
                    "improvement_label": item["improvement_label"],
                    "certainty": item["certainty"],
                    "confidence": float(item["confidence"]),
                    "reason": (item.get("reason") or "").strip(),
                }
            logs.append({"pass": pass_name, "model": model, "record_ids": ids, "ok": True, "usage": res.get("usage", {})})
    return outputs, logs


def majority(values: list[str], fallback: str) -> tuple[str, int]:
    clean = [v for v in values if v]
    if not clean:
        return fallback, 0
    return Counter(clean).most_common(1)[0]


def final_decision(votes: list[dict[str, Any]]) -> dict[str, Any]:
    improvement_label, improvement_count = majority(
        [v.get("improvement_label", "") for v in votes if v],
        "needs_human_review",
    )
    baseline_label, _ = majority(
        [v.get("baseline_consistency_label", "") for v in votes if v],
        "ambiguous",
    )
    improved_label, _ = majority(
        [v.get("improved_consistency_label", "") for v in votes if v],
        "ambiguous",
    )
    certainties = [v.get("certainty", "") for v in votes if v]
    confidences = [float(v.get("confidence", 0)) for v in votes if v]
    reasons = [v.get("reason", "") for v in votes if v]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0

    if not votes:
        final_certainty = "low"
        uncertainty = "api_missing"
        agreement = "0/3"
    elif improvement_count == 3 and avg_conf >= 0.8:
        final_certainty = "high"
        uncertainty = "stable"
        agreement = "3/3"
    elif improvement_count >= 2:
        final_certainty = "medium"
        uncertainty = "majority_vote"
        agreement = f"{improvement_count}/3"
    else:
        improvement_label = "needs_human_review"
        final_certainty = "low"
        uncertainty = "split_vote"
        agreement = "1/3"
    if "low" in certainties:
        uncertainty += "+low_certainty"
        if final_certainty == "high":
            final_certainty = "medium"

    return {
        "final_baseline_consistency_label": baseline_label,
        "final_improved_consistency_label": improved_label,
        "final_improvement_label": improvement_label,
        "final_certainty": final_certainty,
        "final_confidence": round(avg_conf, 4),
        "vote_agreement": agreement,
        "uncertainty_tag": uncertainty,
        "final_reason": " | ".join(reasons)[:900],
    }


def write_outputs(records: list[Record], pass_outputs: dict[str, dict[int, dict[str, Any]]],
                  logs: list[dict[str, Any]]) -> None:
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, Any]] = []
    for r in records:
        p1 = pass_outputs["pass_1_flash_a"].get(r.record_id, {})
        p2 = pass_outputs["pass_2_flash_b"].get(r.record_id, {})
        p3 = pass_outputs["pass_3_pro_c"].get(r.record_id, {})
        final = final_decision([p1, p2, p3])
        rows.append(
            {
                "record_id": r.record_id,
                "dataset": r.dataset,
                "query": r.query,
                "role": r.role,
                "baseline_top1_id": r.baseline_top1_id,
                "baseline_top1_name": r.baseline_top1_name,
                "baseline_score": r.baseline_score,
                "baseline_flag": r.baseline_flag,
                "baseline_abs_label_from_top1_consistency_review": r.baseline_abs_label,
                "baseline_abs_certainty_from_top1_consistency_review": r.baseline_abs_certainty,
                "improved_top1_id": r.improved_top1_id,
                "improved_top1_name": r.improved_top1_name,
                "improved_score": r.improved_score,
                "improved_flag": r.improved_flag,
                "pass1_baseline_label": p1.get("baseline_consistency_label", ""),
                "pass1_improved_label": p1.get("improved_consistency_label", ""),
                "pass1_improvement_label": p1.get("improvement_label", ""),
                "pass1_certainty": p1.get("certainty", ""),
                "pass1_confidence": p1.get("confidence", ""),
                "pass1_reason": p1.get("reason", ""),
                "pass2_baseline_label": p2.get("baseline_consistency_label", ""),
                "pass2_improved_label": p2.get("improved_consistency_label", ""),
                "pass2_improvement_label": p2.get("improvement_label", ""),
                "pass2_certainty": p2.get("certainty", ""),
                "pass2_confidence": p2.get("confidence", ""),
                "pass2_reason": p2.get("reason", ""),
                "pass3_baseline_label": p3.get("baseline_consistency_label", ""),
                "pass3_improved_label": p3.get("improved_consistency_label", ""),
                "pass3_improvement_label": p3.get("improvement_label", ""),
                "pass3_certainty": p3.get("certainty", ""),
                "pass3_confidence": p3.get("confidence", ""),
                "pass3_reason": p3.get("reason", ""),
                **final,
            }
        )

    fields = list(rows[0].keys())
    with (REVIEW_DIR / "changed_top1_report03_review.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    summary = {
        "total_records": len(rows),
        "valid_3pass_records": sum(
            1
            for r in rows
            if r["pass1_improvement_label"] and r["pass2_improvement_label"] and r["pass3_improvement_label"]
        ),
        "improvement_label_counts": dict(Counter(r["final_improvement_label"] for r in rows)),
        "baseline_consistency_counts": dict(Counter(r["final_baseline_consistency_label"] for r in rows)),
        "improved_consistency_counts": dict(Counter(r["final_improved_consistency_label"] for r in rows)),
        "certainty_counts": dict(Counter(r["final_certainty"] for r in rows)),
        "uncertainty_tag_counts": dict(Counter(r["uncertainty_tag"] for r in rows)),
        "api_log_entries": len(logs),
        "api_failures": sum(1 for x in logs if not x.get("ok")),
    }
    (REVIEW_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (REVIEW_DIR / "api_logs.json").write_text(
        json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is not set.")
        return 2
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    records = load_records()
    print(f"records={len(records)}", flush=True)

    passes = [
        ("pass_1_flash_a", FLASH_MODEL, PROMPT_A, args.workers),
        ("pass_2_flash_b", FLASH_MODEL, PROMPT_B, args.workers),
        ("pass_3_pro_c", PRO_MODEL, PROMPT_C, max(3, args.workers // 2)),
    ]
    outputs: dict[str, dict[int, dict[str, Any]]] = {}
    all_logs: list[dict[str, Any]] = []
    for pass_name, model, prompt, workers in passes:
        cache_path = REVIEW_DIR / f"{pass_name}_raw.json"
        if cache_path.exists():
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            out = {int(k): v for k, v in cached["outputs"].items()}
            logs = cached.get("logs", [])
            print(f"reusing {pass_name}: valid={len(out)}", flush=True)
        else:
            print(f"running {pass_name} model={model} workers={workers}", flush=True)
            out, logs = run_pass(records, model, prompt, api_key, pass_name, args.batch_size, workers)
            missing = [r for r in records if r.record_id not in out]
            retry_round = 1
            while missing and retry_round <= 2:
                print(f"{pass_name}: retry_round={retry_round} missing={len(missing)}", flush=True)
                retry_out, retry_logs = run_pass(
                    missing,
                    model,
                    prompt,
                    api_key,
                    f"{pass_name}_retry{retry_round}",
                    max(1, min(3, args.batch_size)),
                    max(2, min(4, workers)),
                )
                out.update(retry_out)
                logs.extend(retry_logs)
                missing = [r for r in records if r.record_id not in out]
                retry_round += 1
            cache_path.write_text(
                json.dumps({"outputs": out, "logs": logs}, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        print(f"{pass_name}: valid={len(out)} failures={sum(1 for x in logs if not x.get('ok'))}", flush=True)
        outputs[pass_name] = out
        all_logs.extend(logs)

    write_outputs(records, outputs, all_logs)
    print(f"wrote outputs to {REVIEW_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

