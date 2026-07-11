#!/usr/bin/env python3
"""DeepSeek-based record-by-record comparison review for improvement_02.

This script does NOT assume any established ground-truth dataset. It reviews
baseline vs improved top-1 candidates per query, using strict labels:
  - improved_better
  - improved_worse
  - no_material_change
  - both_wrong
  - needs_human_review
  - homba_gap_or_source_issue

Workflow
--------
1) calibrate: compare two prompt variants on a small sanity set.
2) run      : flash pass on all records, then pro pass on uncertain subset.

Requirements
------------
Set environment variable DEEPSEEK_API_KEY before running.
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
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any


HERE = Path(__file__).resolve().parent
OUT = HERE / "output"
INPUT_CSV = OUT / "improved_full_results.csv"
API_URL = "https://api.deepseek.com/chat/completions"
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"

LABELS = {
    "improved_better",
    "improved_worse",
    "no_material_change",
    "both_wrong",
    "needs_human_review",
    "homba_gap_or_source_issue",
}


PROMPT_A = """You are reviewing RCS candidate quality.

Important:
- There is NO established ground-truth dataset in this project.
- Judge only from each query and the two candidate names.

Task:
For each record, compare `baseline_top1_name` vs `improved_top1_name` for the query.
Return ONE label from:
improved_better, improved_worse, no_material_change, both_wrong,
needs_human_review, homba_gap_or_source_issue

Guidelines:
- improved_better: improved candidate is anatomically/semantically closer.
- improved_worse: improved candidate is clearly farther/wronger.
- no_material_change: effectively same target or no meaningful difference.
- both_wrong: both candidates look wrong for the query.
- needs_human_review: uncertain or debatable even for a specialist.
- homba_gap_or_source_issue: query likely outside ontology granularity
  or appears to be a source-label issue/typo.

Output STRICT JSON only:
{
  "results": [
    {
      "record_id": <int>,
      "label": "<one label>",
      "confidence": <float 0..1>,
      "reason": "<max 220 chars>"
    }
  ]
}
Do not add any extra keys or text.
"""


PROMPT_B = """You are an expert neuroanatomy reviewer for RCS diff analysis.

Context constraints:
- Do NOT assume a gold answer exists.
- Use only the query text and two candidate names.
- Prefer conservative labels when uncertain.

Label definitions:
1) improved_better: improved candidate is more specific/correct than baseline.
2) improved_worse: improved candidate is less correct than baseline.
3) no_material_change: candidate difference is nominal/alias-level only.
4) both_wrong: neither candidate reasonably matches the query.
5) needs_human_review: ambiguous naming or multiple plausible mappings.
6) homba_gap_or_source_issue: concept likely missing in ontology or source text issue.

Decision rules:
- If baseline and improved candidate names are equivalent concepts: no_material_change.
- If one is plausible parent and the other plausible child, and child matches
  query detail better: improved_better.
- If both look off-lobe/off-structure: both_wrong.
- If uncertain between 2+ plausible structures: needs_human_review.

Return JSON only:
{
  "results":[
    {"record_id": 0, "label":"...", "confidence":0.0, "reason":"..."}
  ]
}
"""


CALIBRATION_EXPECTED: dict[str, str] = {
    # clearly better
    "Ventrolateral thalamic nucleus": "improved_better",
    "Ventromedial thalamic nucleus": "improved_better",
    "Laterodorsal thalamic nucleus": "improved_better",
    "Dorsal Lateral Leminscus Nucleus": "improved_better",
    "Medial dorsal thalamic nucleus": "improved_better",
    # typically worsened/suspicious
    "Lateral Dorsal Thalamus": "improved_worse",
    "Lateral Dorsal Amygdaloid Nucleus": "improved_worse",
    "Cuneate Gracile Nuclei": "needs_human_review",
    "Ventroposterior Medial and Lateral Thalamus": "needs_human_review",
    # usually unchanged
    "Abducens nucleus": "no_material_change",
    "Accessory facial nucleus": "no_material_change",
    "Inferior olive": "no_material_change",
    # likely out-of-scope source / ontology gap style
    "Prefrontal area 46": "homba_gap_or_source_issue",
}


@dataclass
class Record:
    record_id: int
    dataset: str
    query: str
    role: str
    baseline_top1_id: str
    baseline_top1_name: str
    baseline_flag: str
    improved_top1_id: str
    improved_top1_name: str
    improved_flag: str


def load_records() -> list[Record]:
    rows = list(csv.DictReader(INPUT_CSV.open(encoding="utf-8-sig")))
    out: list[Record] = []
    for i, r in enumerate(rows):
        out.append(
            Record(
                record_id=i,
                dataset=r["dataset"],
                query=r["query"],
                role=r.get("role", ""),
                baseline_top1_id=r["base_id"],
                baseline_top1_name=r["base_name"],
                baseline_flag=r["base_flag"],
                improved_top1_id=r["impr_id"],
                improved_top1_name=r["impr_name"],
                improved_flag=r["impr_flag"],
            )
        )
    return out


def _extract_json_obj(text: str) -> dict[str, Any]:
    text = text.strip()
    # happy path
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # fallback: grab first {...} block
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object found in model output.")
    return json.loads(m.group(0))


def _call_deepseek(model: str, prompt: str, batch: list[Record], api_key: str,
                   retries: int = 3) -> dict[str, Any]:
    batch_payload = [
        {
            "record_id": r.record_id,
            "dataset": r.dataset,
            "query": r.query,
            "baseline_top1_name": r.baseline_top1_name,
            "improved_top1_name": r.improved_top1_name,
            "baseline_flag": r.baseline_flag,
            "improved_flag": r.improved_flag,
            "role_hint": r.role,
        }
        for r in batch
    ]
    user_msg = (
        "Review the following records and classify each.\n"
        f"records={json.dumps(batch_payload, ensure_ascii=False)}"
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0,
        "max_tokens": 2200,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                body = json.loads(resp.read().decode("utf-8"))
            txt = body["choices"][0]["message"]["content"]
            obj = _extract_json_obj(txt)
            return {"ok": True, "response": obj, "raw": txt, "usage": body.get("usage", {})}
        except urllib.error.HTTPError as exc:
            err = exc.read().decode("utf-8", errors="replace")
            last_err = f"HTTP {exc.code}: {err[:300]}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        time.sleep(min(2 ** attempt, 8))
    return {"ok": False, "error": last_err or "unknown error"}


def _chunked(items: list[Record], size: int) -> list[list[Record]]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def _validate_batch_results(batch: list[Record], obj: dict[str, Any]) -> tuple[bool, str]:
    if "results" not in obj or not isinstance(obj["results"], list):
        return False, "missing results[]"
    ids = {r.record_id for r in batch}
    seen = set()
    for item in obj["results"]:
        rid = item.get("record_id")
        label = item.get("label")
        conf = item.get("confidence")
        if rid not in ids:
            return False, f"unknown record_id {rid}"
        if rid in seen:
            return False, f"duplicate record_id {rid}"
        seen.add(rid)
        if label not in LABELS:
            return False, f"invalid label {label!r}"
        try:
            c = float(conf)
        except Exception:  # noqa: BLE001
            return False, f"invalid confidence for {rid}"
        if not (0.0 <= c <= 1.0):
            return False, f"confidence out of range for {rid}"
    if seen != ids:
        missing = sorted(ids - seen)
        return False, f"missing record_id(s) {missing}"
    return True, ""


def run_batches(records: list[Record], prompt: str, model: str, api_key: str,
                batch_size: int = 5, workers: int = 8) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    batches = _chunked(records, batch_size)
    results_by_id: dict[int, dict[str, Any]] = {}
    raw_logs: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=workers) as ex:
        fut_map = {
            ex.submit(_call_deepseek, model, prompt, batch, api_key): batch
            for batch in batches
        }
        for fut in as_completed(fut_map):
            batch = fut_map[fut]
            call = fut.result()
            batch_ids = [r.record_id for r in batch]
            if not call["ok"]:
                raw_logs.append(
                    {"model": model, "record_ids": batch_ids, "ok": False, "error": call["error"]}
                )
                continue
            obj = call["response"]
            ok, why = _validate_batch_results(batch, obj)
            raw_logs.append(
                {
                    "model": model,
                    "record_ids": batch_ids,
                    "ok": ok,
                    "error": "" if ok else why,
                    "usage": call.get("usage", {}),
                }
            )
            if not ok:
                continue
            for item in obj["results"]:
                rid = int(item["record_id"])
                results_by_id[rid] = {
                    "label": item["label"],
                    "confidence": float(item["confidence"]),
                    "reason": (item.get("reason") or "").strip(),
                }
    return results_by_id, raw_logs


def _accuracy_proxy(records: list[Record], outputs: dict[int, dict[str, Any]]) -> tuple[float, int, int]:
    by_query = {r.query: r.record_id for r in records}
    hit = total = 0
    for q, expected in CALIBRATION_EXPECTED.items():
        rid = by_query.get(q)
        if rid is None or rid not in outputs:
            continue
        total += 1
        if outputs[rid]["label"] == expected:
            hit += 1
    return ((hit / total) if total else 0.0, hit, total)


def cmd_calibrate(args: argparse.Namespace) -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is not set.")
        return 2
    records = load_records()
    cal_queries = set(CALIBRATION_EXPECTED)
    cal_records = [r for r in records if r.query in cal_queries]
    print(f"calibration records found: {len(cal_records)}")
    out_dir = OUT / "deepseek_review"
    out_dir.mkdir(parents=True, exist_ok=True)

    oa, loga = run_batches(cal_records, PROMPT_A, FLASH_MODEL, api_key, batch_size=5, workers=4)
    ob, logb = run_batches(cal_records, PROMPT_B, FLASH_MODEL, api_key, batch_size=5, workers=4)
    acc_a, hit_a, tot_a = _accuracy_proxy(cal_records, oa)
    acc_b, hit_b, tot_b = _accuracy_proxy(cal_records, ob)

    summary = {
        "prompt_a": {"proxy_accuracy": acc_a, "hit": hit_a, "total": tot_a, "resolved": len(oa)},
        "prompt_b": {"proxy_accuracy": acc_b, "hit": hit_b, "total": tot_b, "resolved": len(ob)},
        "chosen_prompt": "B" if acc_b >= acc_a else "A",
    }
    (out_dir / "calibration_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "calibration_logs_a.json").write_text(
        json.dumps(loga, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out_dir / "calibration_logs_b.json").write_text(
        json.dumps(logb, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _select_prompt(which: str) -> str:
    if which == "A":
        return PROMPT_A
    if which == "B":
        return PROMPT_B
    # auto
    path = OUT / "deepseek_review" / "calibration_summary.json"
    if path.exists():
        s = json.loads(path.read_text(encoding="utf-8"))
        if s.get("chosen_prompt") == "A":
            return PROMPT_A
    return PROMPT_B


def cmd_run(args: argparse.Namespace) -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY is not set.")
        return 2
    records = load_records()
    prompt = _select_prompt(args.prompt)
    out_dir = OUT / "deepseek_review"
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"flash pass: {len(records)} records")
    flash_res, flash_logs = run_batches(
        records, prompt, FLASH_MODEL, api_key, batch_size=args.batch_size, workers=args.workers
    )
    (out_dir / "flash_logs.json").write_text(
        json.dumps(flash_logs, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    unresolved = []
    for r in records:
        item = flash_res.get(r.record_id)
        if not item:
            unresolved.append(r)
            continue
        if (
            item["confidence"] < args.pro_threshold
            or item["label"] == "needs_human_review"
            or (r.role == "llm_accept_top1" and item["label"] in {"improved_worse", "both_wrong"})
        ):
            unresolved.append(r)
    print(f"pro escalation: {len(unresolved)} records")

    pro_res: dict[int, dict[str, Any]] = {}
    pro_logs: list[dict[str, Any]] = []
    if unresolved:
        pro_res, pro_logs = run_batches(
            unresolved, prompt, PRO_MODEL, api_key, batch_size=args.batch_size, workers=max(2, args.workers // 2)
        )
        (out_dir / "pro_logs.json").write_text(
            json.dumps(pro_logs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    final = dict(flash_res)
    final.update(pro_res)  # pro override

    rows = []
    for r in records:
        fres = flash_res.get(r.record_id, {})
        pres = pro_res.get(r.record_id, {})
        chosen = final.get(r.record_id, {})
        rows.append(
            {
                "record_id": r.record_id,
                "dataset": r.dataset,
                "query": r.query,
                "role": r.role,
                "baseline_top1_id": r.baseline_top1_id,
                "baseline_top1_name": r.baseline_top1_name,
                "improved_top1_id": r.improved_top1_id,
                "improved_top1_name": r.improved_top1_name,
                "flash_label": fres.get("label", ""),
                "flash_confidence": fres.get("confidence", ""),
                "flash_reason": fres.get("reason", ""),
                "pro_label": pres.get("label", ""),
                "pro_confidence": pres.get("confidence", ""),
                "pro_reason": pres.get("reason", ""),
                "final_label": chosen.get("label", ""),
                "final_confidence": chosen.get("confidence", ""),
                "final_reason": chosen.get("reason", ""),
                "used_pro": "yes" if r.record_id in pro_res else "",
            }
        )

    final_csv = out_dir / "final_review.csv"
    with final_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)

    # summary
    by_label: dict[str, int] = {}
    by_role_label: dict[str, dict[str, int]] = {}
    for row in rows:
        lb = row["final_label"] or "missing"
        by_label[lb] = by_label.get(lb, 0) + 1
        rl = row["role"]
        by_role_label.setdefault(rl, {})
        by_role_label[rl][lb] = by_role_label[rl].get(lb, 0) + 1

    summary = {
        "total_records": len(records),
        "flash_resolved": len(flash_res),
        "pro_escalated": len(unresolved),
        "pro_resolved": len(pro_res),
        "final_resolved": sum(1 for r in rows if r["final_label"]),
        "final_label_counts": by_label,
        "final_label_counts_by_role": by_role_label,
    }
    (out_dir / "final_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"wrote: {final_csv}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("calibrate", help="Run prompt calibration on sanity set")
    c.set_defaults(func=cmd_calibrate)

    r = sub.add_parser("run", help="Run full review (flash -> selective pro)")
    r.add_argument("--prompt", choices=["A", "B", "auto"], default="auto")
    r.add_argument("--batch-size", type=int, default=5)
    r.add_argument("--workers", type=int, default=8)
    r.add_argument("--pro-threshold", type=float, default=0.70)
    r.set_defaults(func=cmd_run)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

