#!/usr/bin/env python3
"""DeepSeek review: does each RCS top-1 candidate align with the query?

This task is independent from improvement_02 diff analysis.  It reviews the
LLM review input CSVs as records in their own right:

  query  vs  top_name / top_homba_id

There is no established answer dataset.  The output is a new LLM consistency
review, using three independent API passes:

  pass_1: deepseek-v4-flash, prompt A
  pass_2: deepseek-v4-flash, prompt B
  pass_3: deepseek-v4-pro,   prompt C

Each API call contains up to 5 records and calls are parallelized.
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
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
INPUT_DIR = HERE / "llm_review_inputs"
OUT_DIR = HERE / "output" / "top1_consistency_review"
API_URL = "https://api.deepseek.com/chat/completions"
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"

INPUT_FILES = [
    "1_highconf_correct.csv",
    "2_highconf_incorrect.csv",
    "3_unresolved_correct.csv",
    "4_unresolved_incorrect.csv",
]

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


@dataclass(frozen=True)
class Record:
    record_id: int
    source_file: str
    source_row: int
    dataset: str
    query: str
    top_homba_id: str
    top_name: str
    review_flag: str
    score: str
    matched_query: str
    matched_alias: str
    modifier_terms: str
    previous_review_label: str
    previous_review_note: str
    raw: dict[str, str]


def load_records() -> list[Record]:
    records: list[Record] = []
    rid = 0
    for fname in INPUT_FILES:
        path = INPUT_DIR / fname
        with path.open(newline="", encoding="utf-8-sig") as fh:
            for idx, row in enumerate(csv.DictReader(fh), start=2):
                records.append(
                    Record(
                        record_id=rid,
                        source_file=fname,
                        source_row=idx,
                        dataset=row.get("dataset", ""),
                        query=row.get("query", ""),
                        top_homba_id=row.get("top_homba_id", ""),
                        top_name=row.get("top_name", ""),
                        review_flag=row.get("review_flag", ""),
                        score=row.get("score", ""),
                        matched_query=row.get("matched_query", ""),
                        matched_alias=row.get("matched_alias", ""),
                        modifier_terms=row.get("modifier_terms", ""),
                        previous_review_label=(
                            row.get("llm_check")
                            or row.get("_category")
                            or ""
                        ),
                        previous_review_note=(
                            row.get("_mechanism")
                            or ""
                        ),
                        raw=row,
                    )
                )
                rid += 1
    return records


def chunked(items: list[Record], size: int) -> list[list[Record]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


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


def validate(batch: list[Record], obj: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(obj.get("results"), list):
        return False, "missing results[]"
    ids = {r.record_id for r in batch}
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
        except Exception:  # noqa: BLE001
            return False, f"invalid confidence {rid}"
        if not 0 <= c <= 1:
            return False, f"confidence out of range {rid}"
    if seen != ids:
        return False, f"missing ids {sorted(ids - seen)}"
    return True, ""


def call_deepseek(model: str, prompt: str, batch: list[Record], api_key: str,
                  retries: int = 3) -> dict[str, Any]:
    payload_records = [
        {
            "record_id": r.record_id,
            "source_file": r.source_file,
            "dataset": r.dataset,
            "query": r.query,
            "top1_name": r.top_name,
            "top1_id": r.top_homba_id,
            "review_flag": r.review_flag,
            "score": r.score,
            "matched_query": r.matched_query,
            "matched_alias": r.matched_alias,
            "modifier_terms": r.modifier_terms,
        }
        for r in batch
    ]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (
                    "Review these records.\nrecords="
                    + json.dumps(payload_records, ensure_ascii=False)
                ),
            },
        ],
        "temperature": 0,
        "max_tokens": 2200,
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
    batches = chunked(records, batch_size)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(call_deepseek, model, prompt, batch, api_key): batch
            for batch in batches
        }
        for fut in as_completed(futs):
            batch = futs[fut]
            ids = [r.record_id for r in batch]
            res = fut.result()
            if not res["ok"]:
                logs.append({"pass": pass_name, "model": model, "record_ids": ids, "ok": False, "error": res["error"]})
                continue
            for item in res["response"]["results"]:
                outputs[int(item["record_id"])] = {
                    "label": item["label"],
                    "certainty": item["certainty"],
                    "confidence": float(item["confidence"]),
                    "reason": (item.get("reason") or "").strip(),
                }
            logs.append({"pass": pass_name, "model": model, "record_ids": ids, "ok": True, "usage": res.get("usage", {})})
    return outputs, logs


def final_decision(votes: list[dict[str, Any]]) -> dict[str, Any]:
    labels = [v.get("label", "") for v in votes if v]
    certainties = [v.get("certainty", "") for v in votes if v]
    confidences = [float(v.get("confidence", 0)) for v in votes if v]
    reasons = [v.get("reason", "") for v in votes if v]
    counts = Counter(labels)
    if not labels:
        return {
            "label": "no_consensus",
            "certainty": "low",
            "confidence": 0.0,
            "agreement": "0/3",
            "has_disagreement": True,
            "vote_split_pattern": "missing",
            "uncertainty_tag": "api_missing",
            "reason": "No valid LLM result.",
        }
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
        uncertainty = uncertainty + "+low_certainty"
        if certainty == "high":
            certainty = "medium"
    return {
        "label": label,
        "certainty": certainty,
        "confidence": round(avg_conf, 4),
        "agreement": f"{count}/3" if labels else "0/3",
        "has_disagreement": has_disagreement,
        "vote_split_pattern": vote_split_pattern,
        "uncertainty_tag": uncertainty,
        "reason": " | ".join(reasons[:3])[:700],
    }


def write_outputs(records: list[Record], pass_outputs: dict[str, dict[int, dict[str, Any]]],
                  logs: list[dict[str, Any]]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for r in records:
        p1 = pass_outputs["pass_1_flash_a"].get(r.record_id, {})
        p2 = pass_outputs["pass_2_flash_b"].get(r.record_id, {})
        p3 = pass_outputs["pass_3_pro_c"].get(r.record_id, {})
        final = final_decision([p1, p2, p3])
        base = dict(r.raw)
        base.update(
            {
                "review_record_id": r.record_id,
                "source_file": r.source_file,
                "source_row": r.source_row,
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
                "final_consistency_label": final["label"],
                "final_certainty": final["certainty"],
                "final_confidence": final["confidence"],
                "vote_agreement": final["agreement"],
                "has_vote_disagreement": final["has_disagreement"],
                "vote_split_pattern": final["vote_split_pattern"],
                "uncertainty_tag": final["uncertainty_tag"],
                "final_reason": final["reason"],
            }
        )
        rows.append(base)

    all_path = OUT_DIR / "all_records_top1_consistency.csv"
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with all_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    for fname in INPUT_FILES:
        subset = [r for r in rows if r["source_file"] == fname]
        out_name = "tagged_" + fname
        with (OUT_DIR / out_name).open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(subset)

    summary = {
        "total_records": len(rows),
        "label_counts": dict(Counter(r["final_consistency_label"] for r in rows)),
        "label_counts_by_source_file": {
            fname: dict(Counter(r["final_consistency_label"] for r in rows if r["source_file"] == fname))
            for fname in INPUT_FILES
        },
        "certainty_counts": dict(Counter(r["final_certainty"] for r in rows)),
        "has_vote_disagreement_counts": dict(Counter(str(r["has_vote_disagreement"]) for r in rows)),
        "vote_split_pattern_counts": dict(Counter(r["vote_split_pattern"] for r in rows)),
        "uncertainty_tag_counts": dict(Counter(r["uncertainty_tag"] for r in rows)),
        "api_log_entries": len(logs),
        "api_failures": sum(1 for x in logs if not x.get("ok")),
    }
    (OUT_DIR / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT_DIR / "api_logs.json").write_text(
        json.dumps(logs, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=5)
    parser.add_argument("--workers", type=int, default=10)
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is not set.")
        return 2
    records = load_records()
    print(f"records={len(records)}", flush=True)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    all_logs: list[dict[str, Any]] = []
    outputs: dict[str, dict[int, dict[str, Any]]] = {}

    passes = [
        ("pass_1_flash_a", FLASH_MODEL, PROMPT_A, args.workers),
        ("pass_2_flash_b", FLASH_MODEL, PROMPT_B, args.workers),
        ("pass_3_pro_c", PRO_MODEL, PROMPT_C, max(4, args.workers // 2)),
    ]
    for pass_name, model, prompt, workers in passes:
        cache_path = OUT_DIR / f"{pass_name}_raw.json"
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
                print(
                    f"{pass_name}: retry_round={retry_round} missing={len(missing)}",
                    flush=True,
                )
                retry_out, retry_logs = run_pass(
                    missing,
                    model,
                    prompt,
                    api_key,
                    pass_name + f"_retry{retry_round}",
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
    print(f"wrote outputs to {OUT_DIR}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

