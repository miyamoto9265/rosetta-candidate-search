#!/usr/bin/env python3
"""Classify projection corpus names as neocortex / non-neocortex via DeepSeek.

Pipeline (no RCS):
  1) Optional seed remap from a prior cortical/subcortical classified CSV
     (subcortical→non_neocortex, other→other, allo/meso keywords→non_neocortex)
  2) deepseek-v4-flash × 3 independent passes on remaining records
  3) If flash has no majority (>=2/3), deepseek-v4-pro × 3 passes
  4) If still no majority → region_class=unresolved

Writes classified CSV + HTML report under build_testdata/projection_region_class/.
Pass caches use neo_* prefixes to avoid reusing old cortical/subcortical caches.

Example:
  set DEEPSEEK_API_KEY=...
  python build_testdata/classify_projection_corpus_deepseek.py --workers 128 \\
    --seed-classified build_testdata/projection_region_class/classified_full_cortical_backup.csv
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import shutil
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_INPUT = ROOT / "rcs_projection_corpus.csv"
OUT_DIR = ROOT / "projection_region_class"
API_URL = "https://api.deepseek.com/chat/completions"
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"

LABELS = {"neocortex", "non_neocortex", "other", "ambiguous"}
CERTAINTY = {"high", "medium", "low"}

# Explicit allo/mesocortex markers → non_neocortex without API (cortical seed only).
ALLO_MESO_KEYWORDS = (
    "piriform",
    "entorhinal",
    "perirhinal",
    "parahippocamp",
    "olfactory cortex",
    "olfactory bulb",
    "anterior olfactory",
    "hippocamp",
    "dentate gyrus",
    "subiculum",
    "presubicul",
    "parasubicul",
    "indusium",
    "taenia tecta",
    "allocort",
    "mesocort",
)

PROMPT_BASE = """You classify mammalian brain region names for neural-circuit literature.

Task: assign ONE label to each record using `structure_name` and optional `fullname`.

Labels:
- neocortex: isocortex / cerebral neocortex (typically 6-layered). Includes primary and
  association neocortical areas and common acronyms (M1, S1, V1, A1, PFC, mPFC, PL, IL,
  OFC, PPC, IT, etc.), named neocortical gyri when clearly isocortex.
  Borderline mesocortical areas (cingulate, insula, retrosplenial) may be neocortex or
  non_neocortex — decide from conventional isocortex vs transitional usage; if truly
  unclear use ambiguous.
- non_neocortex: everything that is neural gray matter but not neocortex — thalamus,
  hypothalamus, basal ganglia/striatum, amygdala, hippocampal formation (CA1–CA3, DG,
  subiculum), brainstem, midbrain, spinal cord, septum, claustrum, cerebellum,
  AND allocortex/mesocortex such as piriform, entorhinal, perirhinal, parahippocampal,
  olfactory cortex/bulb.
- other: white-matter tracts/fibers, ventricles, cranial nerves, retina/PNS,
  whole-brain umbrella terms without locus ("brain", "CNS", bare "cortex" when too
  vague to place), non-neural tissue, multi-region compounds mixing neocortex with
  non-neocortex inseparably, or not a region.
- ambiguous: genuinely cannot decide from the name alone (conflicting expansions,
  or unclear whether neocortex vs allocortex/mesocortex).

Rules:
- Do NOT use RCS/HOMBA or any external mapping; judge from structure_name + fullname.
- If fullname is present and clearer than the short name/acronym, prefer fullname.
- Prefer neocortex vs non_neocortex when a conventional expansion is clear.
- Return STRICT JSON only (no markdown).

Schema:
{
  "results": [
    {
      "record_id": <int>,
      "label": "neocortex|non_neocortex|other|ambiguous",
      "certainty": "high|medium|low",
      "confidence": <float 0..1>,
      "reason": "<max 180 chars>"
    }
  ]
}
"""

PROMPT_FLASH_A = PROMPT_BASE + """
Bias: strict anatomical locus. Fiber tracts / vague umbrellas → other.
Allocortex (piriform, entorhinal, hippocampus) → non_neocortex.
"""

PROMPT_FLASH_B = PROMPT_BASE + """
Bias: favor conventional circuit usage of acronyms
(M1/S1/V1/PFC → neocortex; VTA/BLA/NAc/LC/EC/Pir → non_neocortex).
"""

PROMPT_FLASH_C = PROMPT_BASE + """
Bias: when between neocortex and allo/mesocortex, follow definitions above
(piriform/entorhinal/hippocampal = non_neocortex; typical isocortex = neocortex).
"""

PROMPT_PRO_A = PROMPT_BASE + """
Bias: expert adjudication. Resolve acronyms conservatively; use ambiguous only if two
equally common expansions disagree on neocortex vs non_neocortex.
"""

PROMPT_PRO_B = PROMPT_BASE + """
Bias: circuit-mapping pragmatism. Prefer the locus most used as a projection endpoint.
"""

PROMPT_PRO_C = PROMPT_BASE + """
Bias: final conservative vote. Prefer other over guessing for tracts/compounds.
Return pure JSON, no markdown.
"""


@dataclass(frozen=True)
class Record:
    record_id: int
    structure_name: str
    fullname: str
    species: str
    paper: str
    n_mentions: str
    n_papers: str


@dataclass(frozen=True)
class SeedDecision:
    needs_api: bool
    region_class: str = ""
    decision_stage: str = ""
    reason: str = ""
    old_label: str = ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--batch-size", type=int, default=6)
    p.add_argument("--workers", type=int, default=128)
    p.add_argument(
        "--limit",
        type=int,
        default=0,
        help="If >0, only first N rows (smoke test).",
    )
    p.add_argument(
        "--report-only",
        action="store_true",
        help="Rebuild CSV/HTML from cached pass JSON without API calls.",
    )
    p.add_argument(
        "--seed-classified",
        type=Path,
        default=None,
        help=(
            "Prior cortical/subcortical classified_full.csv to remap; "
            "only uncertain rows are sent to the API."
        ),
    )
    return p.parse_args()


def load_records(path: Path, limit: int = 0) -> list[Record]:
    rows: list[Record] = []
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for i, row in enumerate(csv.DictReader(fh)):
            name = (row.get("structure_name") or "").strip()
            if not name:
                continue
            rows.append(
                Record(
                    record_id=i,
                    structure_name=name,
                    fullname=(row.get("fullname") or "").strip(),
                    species=(row.get("species") or "").strip(),
                    paper=(row.get("paper") or "").strip(),
                    n_mentions=(row.get("n_mentions") or "").strip(),
                    n_papers=(row.get("n_papers") or "").strip(),
                )
            )
            if limit and len(rows) >= limit:
                break
    return rows


def chunked(items: list[Any], size: int) -> list[list[Any]]:
    return [items[i : i + size] for i in range(0, len(items), size)]


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
    seen: set[int] = set()
    for item in obj["results"]:
        rid = item.get("record_id")
        try:
            rid_i = int(rid)
        except Exception:  # noqa: BLE001
            return False, f"bad record_id {rid!r}"
        if rid_i not in ids:
            return False, f"unknown record_id {rid_i}"
        if rid_i in seen:
            return False, f"duplicate record_id {rid_i}"
        seen.add(rid_i)
        if item.get("label") not in LABELS:
            return False, f"invalid label {item.get('label')!r}"
        if item.get("certainty") not in CERTAINTY:
            return False, f"invalid certainty {item.get('certainty')!r}"
        try:
            c = float(item.get("confidence"))
        except Exception:  # noqa: BLE001
            return False, f"invalid confidence {rid_i}"
        if not 0.0 <= c <= 1.0:
            return False, f"confidence out of range {rid_i}"
    if seen != ids:
        return False, f"missing ids {sorted(ids - seen)}"
    return True, ""


def call_deepseek(
    model: str,
    prompt: str,
    batch: list[Record],
    api_key: str,
    retries: int = 5,
) -> dict[str, Any]:
    payload = [
        {
            "record_id": r.record_id,
            "structure_name": r.structure_name,
            "fullname": r.fullname,
            "species": r.species,
            "n_mentions": r.n_mentions,
        }
        for r in batch
    ]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Classify these records.\nrecords="
                + json.dumps(payload, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "max_tokens": 2400,
    }
    data_bytes = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last_error = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            API_URL,
            data=data_bytes,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            content = data["choices"][0]["message"]["content"]
            obj = extract_json_obj(content)
            ok, why = validate(batch, obj)
            if not ok:
                raise ValueError(why)
            return {"ok": True, "response": obj, "usage": data.get("usage", {})}
        except urllib.error.HTTPError as exc:
            body_txt = exc.read().decode("utf-8", errors="replace")[:300]
            last_error = f"HTTP {exc.code}: {body_txt}"
            sleep_s = (
                min(2**attempt, 30)
                if exc.code in (429, 500, 502, 503)
                else min(2**attempt, 12)
            )
            time.sleep(sleep_s)
        except Exception as exc:  # noqa: BLE001
            last_error = str(exc)
            time.sleep(min(2**attempt, 12))
    return {"ok": False, "error": last_error}


def run_pass(
    records: list[Record],
    model: str,
    prompt: str,
    api_key: str,
    pass_name: str,
    batch_size: int,
    workers: int,
) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    outputs: dict[int, dict[str, Any]] = {}
    logs: list[dict[str, Any]] = []
    batches = chunked(records, batch_size)
    total = len(batches)
    done_batches = 0
    print(
        f"  {pass_name}: model={model} records={len(records)} "
        f"batches={total} workers={workers}",
        flush=True,
    )
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {
            ex.submit(call_deepseek, model, prompt, batch, api_key): batch
            for batch in batches
        }
        for fut in as_completed(futs):
            batch = futs[fut]
            ids = [r.record_id for r in batch]
            res = fut.result()
            done_batches += 1
            if not res["ok"]:
                logs.append(
                    {
                        "pass": pass_name,
                        "model": model,
                        "record_ids": ids,
                        "ok": False,
                        "error": res["error"],
                    }
                )
            else:
                for item in res["response"]["results"]:
                    outputs[int(item["record_id"])] = {
                        "label": item["label"],
                        "certainty": item["certainty"],
                        "confidence": float(item["confidence"]),
                        "reason": (item.get("reason") or "").strip(),
                    }
                logs.append(
                    {
                        "pass": pass_name,
                        "model": model,
                        "record_ids": ids,
                        "ok": True,
                        "usage": res.get("usage", {}),
                    }
                )
            if done_batches % 50 == 0 or done_batches == total:
                print(
                    f"    {pass_name}: batches {done_batches}/{total} "
                    f"valid={len(outputs)} fail={sum(1 for x in logs if not x['ok'])}",
                    flush=True,
                )
    return outputs, logs


def majority_decision(votes: list[dict[str, Any]]) -> dict[str, Any]:
    present = [v for v in votes if v and v.get("label")]
    labels = [v["label"] for v in present]
    if not labels:
        return {
            "label": "unresolved",
            "agreement": "0/3",
            "vote_split_pattern": "missing",
            "has_majority": False,
            "confidence": 0.0,
            "certainty": "low",
            "reason": "",
        }
    counts = Counter(labels)
    label, count = counts.most_common(1)[0]
    avg_conf = sum(float(v.get("confidence", 0)) for v in present) / len(present)
    reasons = [v.get("reason", "") for v in present if v.get("reason")]
    if count >= 2:
        return {
            "label": label,
            "agreement": f"{count}/{len(labels)}",
            "vote_split_pattern": "3-0" if count == 3 else "2-1",
            "has_majority": True,
            "confidence": round(avg_conf, 4),
            "certainty": "high" if count == 3 and avg_conf >= 0.8 else "medium",
            "reason": " | ".join(reasons[:3])[:700],
        }
    return {
        "label": "unresolved",
        "agreement": f"{count}/{len(labels)}",
        "vote_split_pattern": "1-1-1" if len(counts) >= 3 else "split",
        "has_majority": False,
        "confidence": round(avg_conf, 4),
        "certainty": "low",
        "reason": " | ".join(reasons[:3])[:700],
    }


def load_pass_cache(path: Path) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    if not path.exists():
        return {}, []
    data = json.loads(path.read_text(encoding="utf-8"))
    out = {int(k): v for k, v in data.get("outputs", {}).items()}
    return out, data.get("logs", [])


def save_pass_cache(
    path: Path,
    outputs: dict[int, dict[str, Any]],
    logs: list[dict[str, Any]],
) -> None:
    path.write_text(
        json.dumps(
            {"outputs": {str(k): v for k, v in outputs.items()}, "logs": logs},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def ensure_pass(
    records: list[Record],
    pass_name: str,
    model: str,
    prompt: str,
    api_key: str,
    out_dir: Path,
    batch_size: int,
    workers: int,
) -> dict[int, dict[str, Any]]:
    cache_path = out_dir / f"{pass_name}_raw.json"
    out, logs = load_pass_cache(cache_path)
    missing = [r for r in records if r.record_id not in out]
    if not missing:
        print(f"  reuse {pass_name}: valid={len(out)}", flush=True)
        return out

    if out:
        print(f"  resume {pass_name}: have={len(out)} missing={len(missing)}", flush=True)

    new_out, new_logs = run_pass(
        missing, model, prompt, api_key, pass_name, batch_size, workers
    )
    out.update(new_out)
    logs.extend(new_logs)

    missing = [r for r in records if r.record_id not in out]
    if missing:
        print(f"  {pass_name}: retry missing={len(missing)}", flush=True)
        retry_out, retry_logs = run_pass(
            missing,
            model,
            prompt,
            api_key,
            pass_name + "_retry",
            max(1, min(3, batch_size)),
            max(8, min(workers, 64)),
        )
        out.update(retry_out)
        logs.extend(retry_logs)

    save_pass_cache(cache_path, out, logs)
    print(
        f"  {pass_name}: valid={len(out)}/{len(records)} "
        f"failures={sum(1 for x in logs if not x.get('ok'))}",
        flush=True,
    )
    return out


def matches_allo_meso(structure_name: str, fullname: str) -> str | None:
    blob = f"{structure_name} {fullname}".casefold()
    for key in ALLO_MESO_KEYWORDS:
        if key in blob:
            return key
    return None


def load_seed_labels(path: Path) -> dict[int, str]:
    out: dict[int, str] = {}
    with path.open(newline="", encoding="utf-8-sig") as fh:
        for row in csv.DictReader(fh):
            try:
                rid = int(row["record_id"])
            except (KeyError, ValueError):
                continue
            out[rid] = (row.get("region_class") or "").strip()
    return out


def decide_seed(record: Record, old_label: str) -> SeedDecision:
    if old_label == "subcortical":
        return SeedDecision(
            needs_api=False,
            region_class="non_neocortex",
            decision_stage="seed_remap",
            reason="seed: subcortical → non_neocortex",
            old_label=old_label,
        )
    if old_label == "other":
        return SeedDecision(
            needs_api=False,
            region_class="other",
            decision_stage="seed_remap",
            reason="seed: other kept",
            old_label=old_label,
        )
    if old_label == "cortical":
        hit = matches_allo_meso(record.structure_name, record.fullname)
        if hit:
            return SeedDecision(
                needs_api=False,
                region_class="non_neocortex",
                decision_stage="seed_keyword",
                reason=f"seed: cortical + keyword '{hit}' → non_neocortex",
                old_label=old_label,
            )
        return SeedDecision(needs_api=True, old_label=old_label)
    if old_label in {"ambiguous", "unresolved", ""}:
        return SeedDecision(needs_api=True, old_label=old_label or "missing")
    # Already-new schema labels in seed: keep without API.
    if old_label in LABELS:
        return SeedDecision(
            needs_api=False,
            region_class=old_label,
            decision_stage="seed_remap",
            reason=f"seed: keep {old_label}",
            old_label=old_label,
        )
    return SeedDecision(needs_api=True, old_label=old_label)


def empty_vote_fields() -> dict[str, Any]:
    return {
        "flash_a_label": "",
        "flash_b_label": "",
        "flash_c_label": "",
        "flash_agreement": "",
        "flash_vote_split": "",
        "pro_a_label": "",
        "pro_b_label": "",
        "pro_c_label": "",
        "pro_agreement": "",
        "pro_vote_split": "",
        "flash_a_reason": "",
        "flash_b_reason": "",
        "flash_c_reason": "",
        "pro_a_reason": "",
        "pro_b_reason": "",
        "pro_c_reason": "",
    }


def row_from_seed(record: Record, seed: SeedDecision) -> dict[str, Any]:
    base = {
        "record_id": record.record_id,
        "structure_name": record.structure_name,
        "fullname": record.fullname,
        "species": record.species,
        "paper": record.paper,
        "n_mentions": record.n_mentions,
        "n_papers": record.n_papers,
        "region_class": seed.region_class,
        "decision_stage": seed.decision_stage,
        "final_certainty": "high",
        "final_confidence": 1.0,
        "final_reason": seed.reason,
        "seed_old_label": seed.old_label,
    }
    base.update(empty_vote_fields())
    return base


def build_api_row(
    record: Record,
    flash: dict[str, dict[int, dict[str, Any]]],
    pro: dict[str, dict[int, dict[str, Any]]],
    seed_old_label: str = "",
) -> dict[str, Any]:
    f_votes = [
        flash["neo_flash_a"].get(record.record_id, {}),
        flash["neo_flash_b"].get(record.record_id, {}),
        flash["neo_flash_c"].get(record.record_id, {}),
    ]
    flash_dec = majority_decision(f_votes)
    used_pro = not flash_dec["has_majority"]
    if used_pro:
        p_votes = [
            pro["neo_pro_a"].get(record.record_id, {}),
            pro["neo_pro_b"].get(record.record_id, {}),
            pro["neo_pro_c"].get(record.record_id, {}),
        ]
        pro_dec = majority_decision(p_votes)
        final = pro_dec
        stage = "pro" if pro_dec["has_majority"] else "unresolved"
    else:
        p_votes = [{}, {}, {}]
        pro_dec = {
            "label": "",
            "agreement": "",
            "vote_split_pattern": "",
            "has_majority": False,
            "confidence": "",
            "certainty": "",
            "reason": "",
        }
        final = flash_dec
        stage = "flash"

    region_class = final["label"] if final["has_majority"] else "unresolved"
    return {
        "record_id": record.record_id,
        "structure_name": record.structure_name,
        "fullname": record.fullname,
        "species": record.species,
        "paper": record.paper,
        "n_mentions": record.n_mentions,
        "n_papers": record.n_papers,
        "region_class": region_class,
        "decision_stage": stage,
        "flash_a_label": f_votes[0].get("label", ""),
        "flash_b_label": f_votes[1].get("label", ""),
        "flash_c_label": f_votes[2].get("label", ""),
        "flash_agreement": flash_dec["agreement"],
        "flash_vote_split": flash_dec["vote_split_pattern"],
        "pro_a_label": p_votes[0].get("label", ""),
        "pro_b_label": p_votes[1].get("label", ""),
        "pro_c_label": p_votes[2].get("label", ""),
        "pro_agreement": pro_dec.get("agreement", ""),
        "pro_vote_split": pro_dec.get("vote_split_pattern", ""),
        "final_certainty": final.get("certainty", ""),
        "final_confidence": final.get("confidence", ""),
        "final_reason": final.get("reason", ""),
        "flash_a_reason": f_votes[0].get("reason", ""),
        "flash_b_reason": f_votes[1].get("reason", ""),
        "flash_c_reason": f_votes[2].get("reason", ""),
        "pro_a_reason": p_votes[0].get("reason", ""),
        "pro_b_reason": p_votes[1].get("reason", ""),
        "pro_c_reason": p_votes[2].get("reason", ""),
        "seed_old_label": seed_old_label,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def write_slim_corpus(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "structure_name",
        "fullname",
        "species",
        "paper",
        "n_mentions",
        "n_papers",
        "region_class",
        "decision_stage",
        "final_certainty",
        "final_confidence",
    ]
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def esc(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def write_html(path: Path, rows: list[dict[str, Any]], summary: dict[str, Any]) -> None:
    class_counts = Counter(r["region_class"] for r in rows)
    stage_counts = Counter(r["decision_stage"] for r in rows)
    total = len(rows)

    def bars(counter: Counter[str]) -> str:
        parts = []
        for label, count in counter.most_common():
            pct = 0 if total == 0 else count * 100 / total
            parts.append(
                f"<tr><td>{esc(label)}</td><td class='num'>{count}</td>"
                f"<td class='num'>{pct:.1f}%</td>"
                f"<td><div class='bar'><span style='width:{pct:.2f}%'></span></div></td></tr>"
            )
        return "\n".join(parts)

    unresolved = [r for r in rows if r["region_class"] == "unresolved"]
    pro_resolved = [r for r in rows if r["decision_stage"] == "pro"]
    seed_keyword = [r for r in rows if r["decision_stage"] == "seed_keyword"][:40]
    samples = {
        "neocortex": [r for r in rows if r["region_class"] == "neocortex"][:40],
        "non_neocortex": [r for r in rows if r["region_class"] == "non_neocortex"][:40],
        "other": [r for r in rows if r["region_class"] == "other"][:40],
        "ambiguous": [r for r in rows if r["region_class"] == "ambiguous"][:40],
        "unresolved": unresolved[:80],
        "pro_resolved": pro_resolved[:40],
        "seed_keyword": seed_keyword,
    }

    def sample_table(items: list[dict[str, Any]], extra_cols: list[str] | None = None) -> str:
        cols = [
            "structure_name",
            "fullname",
            "species",
            "n_mentions",
            "region_class",
            "decision_stage",
        ]
        if extra_cols:
            cols.extend(extra_cols)
        head = "".join(f"<th>{esc(c)}</th>" for c in cols)
        body = []
        for r in items:
            tds = "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols)
            body.append(f"<tr>{tds}</tr>")
        if not body:
            body.append("<tr><td colspan='99'>(none)</td></tr>")
        return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    seed_kept = summary.get("seed_kept", 0)
    api_n = summary.get("api_records", 0)
    doc = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<title>Projection corpus — neocortex / non-neocortex</title>
<style>
:root {{
  --bg: #f6f3ee; --ink: #1c1a17; --muted: #5c564e; --line: #d9d0c4;
  --card: #fffdf9; --accent: #0b6e4f; --warn: #9a3412; --bad: #7f1d1d;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  color: var(--ink); background:
    radial-gradient(1200px 500px at 10% -10%, #e7f2ec 0%, transparent 55%),
    radial-gradient(900px 400px at 100% 0%, #f3e7dc 0%, transparent 50%),
    var(--bg);
  line-height: 1.45;
}}
main {{ max-width: 1100px; margin: 0 auto; padding: 32px 20px 64px; }}
h1 {{ font-size: 1.7rem; margin: 0 0 8px; letter-spacing: -0.02em; }}
h2 {{ font-size: 1.15rem; margin: 36px 0 12px; }}
.lead {{ color: var(--muted); margin: 0 0 24px; max-width: 70ch; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: 12px; }}
.card {{
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 16px;
}}
.card-title {{ font-size: 0.78rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
.card-value {{ font-size: 1.55rem; font-weight: 650; margin-top: 4px; }}
.card-sub {{ font-size: 0.8rem; color: var(--muted); margin-top: 2px; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); }}
th, td {{ padding: 8px 10px; border-bottom: 1px solid var(--line); text-align: left; font-size: 0.9rem; vertical-align: top; }}
th {{ background: #f0ebe3; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.03em; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.bar {{ background: #ece6dc; height: 8px; border-radius: 99px; overflow: hidden; }}
.bar span {{ display: block; height: 100%; background: var(--accent); }}
.note {{ color: var(--muted); font-size: 0.88rem; }}
code {{ background: #efe9df; padding: 1px 5px; border-radius: 4px; }}
.section {{ margin-top: 8px; }}
</style>
</head>
<body>
<main>
  <h1>Projection corpus — neocortex / non-neocortex</h1>
  <p class="lead">
    <code>structure_name</code> + <code>fullname</code>。旧 cortical/subcortical 結果をシード再利用
    （保持 {seed_kept} / API再検証 {api_n}）。
    DeepSeek <code>v4-flash</code> 3-pass → 票割れのみ <code>v4-pro</code> 3-pass。
    なお割れは <code>unresolved</code>。生成: {esc(generated)}
  </p>

  <div class="grid">
    <div class="card"><div class="card-title">Total</div><div class="card-value">{total}</div></div>
    <div class="card"><div class="card-title">Neocortex</div><div class="card-value">{class_counts.get('neocortex', 0)}</div></div>
    <div class="card"><div class="card-title">Non-neocortex</div><div class="card-value">{class_counts.get('non_neocortex', 0)}</div></div>
    <div class="card"><div class="card-title">Other</div><div class="card-value">{class_counts.get('other', 0)}</div></div>
    <div class="card"><div class="card-title">Ambiguous</div><div class="card-value">{class_counts.get('ambiguous', 0)}</div></div>
    <div class="card"><div class="card-title">Unresolved</div><div class="card-value">{class_counts.get('unresolved', 0)}</div>
      <div class="card-sub">pro 後も多数決なし</div></div>
  </div>

  <h2>Region class</h2>
  <table>
    <thead><tr><th>Label</th><th class="num">N</th><th class="num">%</th><th></th></tr></thead>
    <tbody>{bars(class_counts)}</tbody>
  </table>

  <h2>Decision stage</h2>
  <table>
    <thead><tr><th>Stage</th><th class="num">N</th><th class="num">%</th><th></th></tr></thead>
    <tbody>{bars(stage_counts)}</tbody>
  </table>
  <p class="note">seed_remap / seed_keyword / flash / pro / unresolved。</p>

  <h2>Flash vote patterns (API rows only)</h2>
  <table>
    <thead><tr><th>Pattern</th><th class="num">N</th><th class="num">%</th><th></th></tr></thead>
    <tbody>{bars(Counter(r['flash_vote_split'] for r in rows if r.get('flash_vote_split')))}</tbody>
  </table>

  <h2>Summary JSON</h2>
  <pre style="background:#fffdf9;border:1px solid var(--line);padding:12px;overflow:auto;font-size:0.8rem;">{esc(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>

  <h2 class="section">Samples — neocortex</h2>
  {sample_table(samples['neocortex'])}
  <h2>Samples — non_neocortex</h2>
  {sample_table(samples['non_neocortex'])}
  <h2>Samples — other</h2>
  {sample_table(samples['other'])}
  <h2>Samples — ambiguous</h2>
  {sample_table(samples['ambiguous'])}
  <h2>Seed keyword → non_neocortex</h2>
  {sample_table(samples['seed_keyword'], ['final_reason','seed_old_label'])}
  <h2>Pro-resolved (flash split → pro majority)</h2>
  {sample_table(samples['pro_resolved'], ['flash_a_label','flash_b_label','flash_c_label','pro_a_label','pro_b_label','pro_c_label'])}
  <h2>Unresolved</h2>
  {sample_table(samples['unresolved'], ['flash_a_label','flash_b_label','flash_c_label','pro_a_label','pro_b_label','pro_c_label','final_reason'])}
</main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def backup_if_needed(path: Path, backup_name: str) -> None:
    if not path.is_file():
        return
    backup = path.with_name(backup_name)
    if backup.exists():
        return
    shutil.copy2(path, backup)
    print(f"backed up {path.name} → {backup.name}", flush=True)


def main() -> int:
    args = parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Prefer explicit seed path; else use cortical backup if present.
    seed_path = args.seed_classified
    classified_path = out_dir / "classified_full.csv"
    if seed_path is None and (out_dir / "classified_full_cortical_backup.csv").is_file():
        seed_path = out_dir / "classified_full_cortical_backup.csv"
    if seed_path is not None and classified_path.is_file():
        backup_if_needed(classified_path, "classified_full_cortical_backup.csv")
        # If user pointed --seed-classified at the live file before backup existed,
        # ensure we still have a stable seed file.
        if seed_path.resolve() == classified_path.resolve():
            seed_path = out_dir / "classified_full_cortical_backup.csv"

    records = load_records(args.input, args.limit)
    print(f"records={len(records)} input={args.input}", flush=True)

    seeds: dict[int, SeedDecision] = {}
    if seed_path is not None:
        if not seed_path.is_file():
            print(f"seed file not found: {seed_path}", flush=True)
            return 2
        old_labels = load_seed_labels(seed_path)
        for r in records:
            seeds[r.record_id] = decide_seed(r, old_labels.get(r.record_id, ""))
        kept = sum(1 for s in seeds.values() if not s.needs_api)
        api_n = sum(1 for s in seeds.values() if s.needs_api)
        print(
            f"seed={seed_path} kept_without_api={kept} api_records={api_n}",
            flush=True,
        )
        stage_seed = Counter(
            s.decision_stage for s in seeds.values() if not s.needs_api
        )
        print(f"seed_stages={dict(stage_seed)}", flush=True)
    else:
        seeds = {
            r.record_id: SeedDecision(needs_api=True, old_label="") for r in records
        }
        print("no seed: classifying all records via API", flush=True)

    api_records = [r for r in records if seeds[r.record_id].needs_api]
    flash_specs = [
        ("neo_flash_a", FLASH_MODEL, PROMPT_FLASH_A),
        ("neo_flash_b", FLASH_MODEL, PROMPT_FLASH_B),
        ("neo_flash_c", FLASH_MODEL, PROMPT_FLASH_C),
    ]
    pro_specs = [
        ("neo_pro_a", PRO_MODEL, PROMPT_PRO_A),
        ("neo_pro_b", PRO_MODEL, PROMPT_PRO_B),
        ("neo_pro_c", PRO_MODEL, PROMPT_PRO_C),
    ]

    flash_out: dict[str, dict[int, dict[str, Any]]] = {
        k: {} for k, _, _ in flash_specs
    }
    pro_out: dict[str, dict[int, dict[str, Any]]] = {k: {} for k, _, _ in pro_specs}

    if api_records and not args.report_only:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY is not set.", flush=True)
            return 2

        for name, model, prompt in flash_specs:
            flash_out[name] = ensure_pass(
                api_records,
                name,
                model,
                prompt,
                api_key,
                out_dir,
                args.batch_size,
                args.workers,
            )

        split_records: list[Record] = []
        for r in api_records:
            dec = majority_decision(
                [
                    flash_out["neo_flash_a"].get(r.record_id, {}),
                    flash_out["neo_flash_b"].get(r.record_id, {}),
                    flash_out["neo_flash_c"].get(r.record_id, {}),
                ]
            )
            if not dec["has_majority"]:
                split_records.append(r)
        print(f"flash splits for pro: {len(split_records)}", flush=True)
        (out_dir / "neo_flash_split_ids.json").write_text(
            json.dumps([r.record_id for r in split_records], indent=2),
            encoding="utf-8",
        )

        if split_records:
            for name, model, prompt in pro_specs:
                pro_out[name] = ensure_pass(
                    split_records,
                    name,
                    model,
                    prompt,
                    api_key,
                    out_dir,
                    args.batch_size,
                    args.workers,
                )
    elif args.report_only:
        for name, _, _ in flash_specs:
            flash_out[name], _ = load_pass_cache(out_dir / f"{name}_raw.json")
        for name, _, _ in pro_specs:
            pro_out[name], _ = load_pass_cache(out_dir / f"{name}_raw.json")

    rows: list[dict[str, Any]] = []
    for r in records:
        seed = seeds[r.record_id]
        if seed.needs_api:
            rows.append(
                build_api_row(r, flash_out, pro_out, seed_old_label=seed.old_label)
            )
        else:
            rows.append(row_from_seed(r, seed))

    seed_kept = sum(1 for s in seeds.values() if not s.needs_api)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema": "neocortex_non_neocortex_v1",
        "input": str(args.input),
        "seed_classified": str(seed_path) if seed_path else None,
        "total_records": len(rows),
        "seed_kept": seed_kept,
        "api_records": len(api_records),
        "seed_stage_counts": dict(
            Counter(s.decision_stage for s in seeds.values() if not s.needs_api)
        ),
        "region_class_counts": dict(Counter(r["region_class"] for r in rows)),
        "decision_stage_counts": dict(Counter(r["decision_stage"] for r in rows)),
        "flash_vote_split_counts": dict(
            Counter(r["flash_vote_split"] for r in rows if r.get("flash_vote_split"))
        ),
        "pro_vote_split_counts": dict(
            Counter(
                r["pro_vote_split"]
                for r in rows
                if r["decision_stage"] in {"pro", "unresolved"} and r.get("pro_vote_split")
            )
        ),
        "models": {"flash": FLASH_MODEL, "pro": PRO_MODEL},
        "workers": args.workers,
        "batch_size": args.batch_size,
    }

    slim_path = ROOT / "rcs_projection_corpus_classified.csv"
    html_path = out_dir / "region_class_report.html"
    summary_path = out_dir / "summary.json"

    write_csv(classified_path, rows)
    write_slim_corpus(slim_path, rows)
    summary_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_html(html_path, rows, summary)

    print(json.dumps(summary["region_class_counts"], ensure_ascii=False), flush=True)
    print(
        f"seed_kept={seed_kept} api_records={len(api_records)}",
        flush=True,
    )
    print(f"wrote {classified_path}", flush=True)
    print(f"wrote {slim_path}", flush=True)
    print(f"wrote {html_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
