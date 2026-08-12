#!/usr/bin/env python3
"""Curate projection corpus: audit neocortex labels + test-data suitability.

Pipeline
--------
1. Load rcs_projection_corpus_classified.csv (+ optional classified_full.csv).
2. Rule-based suitability / suspicion flags (no API).
3. DeepSeek flash × 3 on audit targets (suspect non_neocortex contamination,
   weak-certainty neocortex, flash 2-1, rule-uncertain suitability).
4. Flash splits → deepseek-v4-pro × 3.
5. Apply corrections; write curated CSVs + HTML report.

Outputs under build_testdata/projection_corpus_curation/:
  curated_full.csv          all rows with audit + suitability fields
  curated_suitable.csv      suitable rows only (any region_class)
  curated_non_neocortex.csv suitable + confirmed non_neocortex
  summary.json
  curation_report.html

Example:
  set DEEPSEEK_API_KEY=...
  python build_testdata/curate_projection_corpus.py --workers 128
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import time
import urllib.error
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DEFAULT_SLIM = ROOT / "rcs_projection_corpus_classified.csv"
DEFAULT_FULL = ROOT / "projection_region_class" / "classified_full.csv"
OUT_DIR = ROOT / "projection_corpus_curation"

API_URL = "https://api.deepseek.com/chat/completions"
FLASH_MODEL = "deepseek-v4-flash"
PRO_MODEL = "deepseek-v4-pro"

REGION_LABELS = {"neocortex", "non_neocortex", "other", "ambiguous"}
SUIT_LABELS = {"suitable", "unsuitable"}
UNSUIT_REASONS = {
    "layer_only",
    "too_broad",
    "not_anatomical",
    "cell_type_or_marker",
    "fiber_tract_or_ventricle",
    "compound_multi_region",
    "ambiguous_name",
    "acronym_unresolved",
    "other",
}
CERTAINTY = {"high", "medium", "low"}

# Allo/meso that are correctly non_neocortex (not contamination).
ALLO_MESO_OK = (
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
    "cerebellar cortex",
    "ectorhinal",
)

# Borderline / possible neocortex contamination markers in non_neocortex.
BORDER_MARKERS = (
    "cingulate",
    "insula",
    "insular",
    "retrosplenial",
    "prostriata",
    "prefrontal",
    "prelimbic",
    "infralimbic",
    "orbitofrontal",
    "motor cortex",
    "somatosensory",
    "visual cortex",
    "auditory cortex",
    "parietal cortex",
    "temporal cortex",
    "neocortex",
    "isocortex",
    "primary motor",
    "primary visual",
    "primary somatosensory",
)

LAYER_ONLY_RE = re.compile(
    r"^(?:L(?:[1-6]|I{1,3}|IV|V{1,2}|VI)[A-Za-z]?|"
    r"layer\s*[1-6IVX]+|"
    r"layers?\s*[1-6IVX]+(?:\s*/\s*[1-6IVX]+)?)$",
    re.IGNORECASE,
)
LAYER_TOKEN_RE = re.compile(
    r"(?:^|[^A-Za-z0-9])(?:L(?:[1-6]|I{1,3}|IV|V{1,2}|VI)[A-Za-z]?|"
    r"layer\s*[1-6IVX]+|layers?\b)",
    re.IGNORECASE,
)
CELL_MARKER_RE = re.compile(
    r"(?:\b(?:neuron|neurons|interneuron|pyramidal|motoneuron|motoneurons|"
    r"granule cell|purkinje|SST|PV\+|VIP\+|NDNF|Rbp4|IT\b|CT\b|PT\b|"
    r"cell type|cells?)\b)|(?:^[A-Za-z0-9]+\+)$",
    re.IGNORECASE,
)
FIBER_RE = re.compile(
    r"\b(?:tract|fasciculus|commissure|lemniscus|capsule|callosum|"
    r"peduncle|radiation|bundle|fiber|fibre|white matter|nerve)\b",
    re.IGNORECASE,
)
TOO_BROAD = {
    "cortex",
    "cerebral cortex",
    "brain",
    "cns",
    "central nervous system",
    "nervous system",
    "forebrain",
    "telencephalon",
    "contralateral cortex",
    "ipsilateral cortex",
    "whole brain",
    "brain tissue",
    "neural tissue",
}
COMPOUND_RE = re.compile(
    r"\b(?:and|/|&|\+|versus|vs\.?)\b|,\s*(?:and\s+)?[a-z]",
    re.IGNORECASE,
)
CRYPTIC_ACRONYM_RE = re.compile(r"^[A-Za-z]{1,3}\d{0,2}[A-Za-z]?$")

PROMPT_BASE = """Audit brain region names. Return STRICT JSON only. No markdown.

Fields per record: structure_name, fullname, species, current_region_class, rule_flags.

For EACH record output:
- region_class: neocortex | non_neocortex | other | ambiguous
- class_ok: yes | no  (yes if current_region_class equals your region_class)
- suitability: suitable | unsuitable
- unsuitable_reason: one of
  layer_only | too_broad | not_anatomical | cell_type_or_marker |
  fiber_tract_or_ventricle | compound_multi_region | ambiguous_name |
  acronym_unresolved | other
  OR empty string when suitability=suitable
- certainty: high | medium | low
- confidence: float 0..1
- reason: max 120 chars

Definitions:
- neocortex: isocortex / clear neo acronyms (M1,S1,V1,A1,PFC,mPFC,PL,IL,OFC,PPC).
  Standard projection ROIs ACC/insula/retrosplenial treated as isocortex in
  rodent atlases → neocortex. Never put M1/S1/V1/PFC in non_neocortex.
- non_neocortex: thalamus, hypothalamus, striatum, amygdala, hippocampus
  (CA1-CA3,DG,subiculum), brainstem, midbrain, spinal cord, septum, claustrum,
  cerebellum, and clear allocortex (piriform, entorhinal, perirhinal, olfactory).
- other: tracts, ventricles, nerves, retina/PNS, cell-type-only, umbrellas
  (brain/CNS/bare cortex), inseparable compounds.
- ambiguous: cannot decide neo vs non-neo from the name alone.

suitable = concrete gray-matter ROI / standard acronym for RCS mapping.
unsuitable = layer-only, too broad, not anatomical, cell-type/marker-only,
  fiber/ventricle, multi-region compound, unresolved acronym, etc.

Contamination check: if current=non_neocortex but name is clear isocortex →
region_class=neocortex, class_ok=no. Clear allocortex in non_neocortex is OK.

Schema:
{"results":[{"record_id":0,"region_class":"non_neocortex","class_ok":"yes",
"suitability":"suitable","unsuitable_reason":"","certainty":"high",
"confidence":0.95,"reason":"..."}]}
"""

PROMPT_FLASH_A = PROMPT_BASE + "\nBias: strict anatomy; unsuitable for vague/layer/cell-type."
PROMPT_FLASH_B = (
    PROMPT_BASE
    + "\nBias: circuit ROIs; ACC/AI/RSC often neocortex if isocortex-like; "
    "allocortex stays non_neocortex."
)
PROMPT_FLASH_C = (
    PROMPT_BASE
    + "\nBias: catch neo wrongly labeled non_neocortex; catch bad test rows."
)
PROMPT_PRO_A = PROMPT_BASE + "\nBias: expert adjudication; ambiguous only if truly split."
PROMPT_PRO_B = PROMPT_BASE + "\nBias: prefer unsuitable over noisy RCS queries."
PROMPT_PRO_C = PROMPT_BASE + "\nBias: conservative final vote. Pure JSON only."


@dataclass
class Row:
    record_id: int
    structure_name: str
    fullname: str
    species: str
    paper: str
    n_mentions: str
    n_papers: str
    region_class: str
    decision_stage: str
    final_certainty: str
    final_confidence: str
    flash_vote_split: str = ""
    final_reason: str = ""
    rule_flags: list[str] = field(default_factory=list)
    needs_api: bool = False
    api_priority: str = ""


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, default=DEFAULT_SLIM)
    p.add_argument("--full", type=Path, default=DEFAULT_FULL)
    p.add_argument("--out-dir", type=Path, default=OUT_DIR)
    p.add_argument("--batch-size", type=int, default=6)
    p.add_argument("--workers", type=int, default=128)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--spotcheck-n", type=int, default=120,
                   help="Extra high-confidence non_neocortex spot-check size.")
    p.add_argument("--report-only", action="store_true")
    return p.parse_args()


def load_rows(slim: Path, full: Path | None, limit: int = 0) -> list[Row]:
    full_by_key: dict[tuple[str, str, str], dict[str, str]] = {}
    if full and full.is_file():
        with full.open(newline="", encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                key = (
                    (r.get("structure_name") or "").strip(),
                    (r.get("fullname") or "").strip(),
                    (r.get("species") or "").strip(),
                )
                full_by_key[key] = r

    rows: list[Row] = []
    with slim.open(newline="", encoding="utf-8-sig") as fh:
        for i, r in enumerate(csv.DictReader(fh)):
            name = (r.get("structure_name") or "").strip()
            if not name:
                continue
            key = (
                name,
                (r.get("fullname") or "").strip(),
                (r.get("species") or "").strip(),
            )
            fr = full_by_key.get(key, {})
            rid = i
            if fr.get("record_id") not in (None, ""):
                try:
                    rid = int(fr["record_id"])
                except ValueError:
                    rid = i
            rows.append(
                Row(
                    record_id=rid,
                    structure_name=name,
                    fullname=(r.get("fullname") or "").strip(),
                    species=(r.get("species") or "").strip(),
                    paper=(r.get("paper") or "").strip(),
                    n_mentions=(r.get("n_mentions") or "").strip(),
                    n_papers=(r.get("n_papers") or "").strip(),
                    region_class=(r.get("region_class") or "").strip(),
                    decision_stage=(r.get("decision_stage") or "").strip(),
                    final_certainty=(r.get("final_certainty") or "").strip(),
                    final_confidence=(r.get("final_confidence") or "").strip(),
                    flash_vote_split=(fr.get("flash_vote_split") or "").strip(),
                    final_reason=(fr.get("final_reason") or "").strip(),
                )
            )
            if limit and len(rows) >= limit:
                break
    return rows


def blob(row: Row) -> str:
    return f"{row.structure_name} {row.fullname}".casefold()


def rule_flags(row: Row) -> list[str]:
    flags: list[str] = []
    b = blob(row)
    name = row.structure_name.strip()
    full = row.fullname.strip()
    name_cf = name.casefold()
    full_cf = full.casefold()

    if LAYER_ONLY_RE.match(name) or LAYER_ONLY_RE.match(full):
        flags.append("rule_layer_only")
    elif LAYER_TOKEN_RE.search(name) or LAYER_TOKEN_RE.search(full):
        # layer mentioned; may still be region+layer
        regionish = re.sub(
            r"(?:L(?:[1-6]|I{1,3}|IV|V{1,2}|VI)[A-Za-z]?|layer\s*[1-6IVX]+|layers?)",
            " ",
            f"{name} {full}",
            flags=re.I,
        )
        regionish = re.sub(r"[^A-Za-z]+", " ", regionish).strip()
        if len(regionish) < 3:
            flags.append("rule_layer_only")
        else:
            flags.append("rule_has_layer")

    if name_cf in TOO_BROAD or full_cf in TOO_BROAD:
        flags.append("rule_too_broad")

    if FIBER_RE.search(b):
        flags.append("rule_fiber")

    if CELL_MARKER_RE.search(name) or CELL_MARKER_RE.search(full):
        # cell-type heavy; may still be region+cell
        flags.append("rule_cell_type")

    if COMPOUND_RE.search(name) or COMPOUND_RE.search(full):
        flags.append("rule_compound")

    if not full and CRYPTIC_ACRONYM_RE.match(name) and row.region_class in {
        "ambiguous",
        "unresolved",
        "other",
    }:
        flags.append("rule_cryptic_acronym")

    if row.region_class in {"ambiguous", "unresolved"}:
        flags.append("rule_prior_ambiguous")
    if row.region_class == "other":
        flags.append("rule_prior_other")

    allo = any(k in b for k in ALLO_MESO_OK)
    border = any(k in b for k in BORDER_MARKERS)
    has_cortex_word = bool(re.search(r"\bcortex\b|\bcortical\b|\bgyrus\b", b))

    if row.region_class == "non_neocortex":
        if border and not allo:
            flags.append("suspect_border_in_non_neo")
        elif has_cortex_word and not allo and "cerebellar" not in b:
            # "cortex" in non_neocortex without allo keyword
            flags.append("suspect_cortex_word_in_non_neo")

    if row.region_class == "neocortex" and row.final_certainty != "high":
        flags.append("weak_neocortex_certainty")

    if row.flash_vote_split in {"2-1", "1-1-1"}:
        flags.append("flash_split")

    if allo and row.region_class == "neocortex":
        flags.append("suspect_allo_in_neocortex")

    return flags


def decide_api(row: Row, spotcheck_ids: set[int]) -> tuple[bool, str]:
    """API only for label-risk rows; suitability mostly handled by rules."""
    f = set(row.rule_flags)
    # Label-risk first (even if also layer/cell noisy)
    if "suspect_border_in_non_neo" in f or "suspect_cortex_word_in_non_neo" in f:
        return True, "contamination_suspect"
    if "suspect_allo_in_neocortex" in f:
        return True, "allo_in_neocortex"
    if "weak_neocortex_certainty" in f:
        return True, "weak_neocortex"
    if "flash_split" in f:
        return True, "flash_split"
    # Decisive unsuitable rules → no API
    if f & {
        "rule_layer_only",
        "rule_has_layer",
        "rule_too_broad",
        "rule_prior_ambiguous",
        "rule_prior_other",
        "rule_cell_type",
        "rule_cryptic_acronym",
        "rule_compound",
    }:
        return False, ""
    if row.record_id in spotcheck_ids:
        return True, "spotcheck"
    return False, ""


def rule_suitability_seed(row: Row) -> tuple[str, str]:
    """Deterministic unsuitable when rules are decisive; else empty."""
    f = set(row.rule_flags)
    if "rule_layer_only" in f or "rule_has_layer" in f:
        return "unsuitable", "layer_only"
    if "rule_too_broad" in f:
        return "unsuitable", "too_broad"
    if "rule_prior_ambiguous" in f:
        return "unsuitable", "ambiguous_name"
    if "rule_fiber" in f and row.region_class == "other":
        return "unsuitable", "fiber_tract_or_ventricle"
    if "rule_cell_type" in f and row.region_class in {"other", "ambiguous", "unresolved"}:
        return "unsuitable", "cell_type_or_marker"
    if "rule_cell_type" in f and row.region_class in {"neocortex", "non_neocortex"}:
        # Region+cell-type hybrids are noisy as RCS queries
        return "unsuitable", "cell_type_or_marker"
    if "rule_cryptic_acronym" in f:
        return "unsuitable", "acronym_unresolved"
    if "rule_compound" in f:
        return "unsuitable", "compound_multi_region"
    if "rule_prior_other" in f:
        return "unsuitable", "other"
    return "", ""


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


def _norm_region_class(value: object) -> str | None:
    s = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    aliases = {
        "neo": "neocortex",
        "neocortical": "neocortex",
        "isocortex": "neocortex",
        "non_neo": "non_neocortex",
        "nonneocortex": "non_neocortex",
        "subcortical": "non_neocortex",
        "allocortex": "non_neocortex",
    }
    s = aliases.get(s, s)
    return s if s in REGION_LABELS else None


def _norm_suitability(value: object) -> str | None:
    s = str(value or "").strip().casefold()
    if s in SUIT_LABELS:
        return s
    if s in {"yes", "ok", "keep", "good"}:
        return "suitable"
    if s in {"no", "bad", "drop", "reject"}:
        return "unsuitable"
    return None


def _norm_unsuitable_reason(value: object, suitability: str) -> str:
    if suitability != "unsuitable":
        return ""
    s = str(value or "").strip().casefold().replace("-", "_").replace(" ", "_")
    if s in UNSUIT_REASONS:
        return s
    # Map free-text / truncated reasons to nearest bucket
    blob = str(value or "").casefold()
    mapping = (
        ("layer", "layer_only"),
        ("broad", "too_broad"),
        ("umbrella", "too_broad"),
        ("cell", "cell_type_or_marker"),
        ("marker", "cell_type_or_marker"),
        ("neuron", "cell_type_or_marker"),
        ("fiber", "fiber_tract_or_ventricle"),
        ("tract", "fiber_tract_or_ventricle"),
        ("ventric", "fiber_tract_or_ventricle"),
        ("compound", "compound_multi_region"),
        ("multi", "compound_multi_region"),
        ("acronym", "acronym_unresolved"),
        ("abbrev", "acronym_unresolved"),
        ("ambiguous", "ambiguous_name"),
        ("unclear", "ambiguous_name"),
        ("anatom", "not_anatomical"),
    )
    for key, label in mapping:
        if key in blob or key in s:
            return label
    return "other"


def normalize_result_item(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        rid = int(item.get("record_id"))
    except Exception:  # noqa: BLE001
        return None
    rc = _norm_region_class(item.get("region_class"))
    if rc is None:
        return None
    class_ok_raw = str(item.get("class_ok", "")).strip().casefold()
    if class_ok_raw in {"yes", "true", "1"}:
        class_ok = "yes"
    elif class_ok_raw in {"no", "false", "0"}:
        class_ok = "no"
    else:
        class_ok = "no"
    suit = _norm_suitability(item.get("suitability"))
    if suit is None:
        return None
    reason = _norm_unsuitable_reason(item.get("unsuitable_reason"), suit)
    cert = str(item.get("certainty") or "medium").strip().casefold()
    if cert not in CERTAINTY:
        cert = "medium"
    try:
        conf = float(item.get("confidence", 0.5))
    except Exception:  # noqa: BLE001
        conf = 0.5
    conf = min(1.0, max(0.0, conf))
    return {
        "record_id": rid,
        "region_class": rc,
        "class_ok": class_ok,
        "suitability": suit,
        "unsuitable_reason": reason,
        "certainty": cert,
        "confidence": conf,
        "reason": str(item.get("reason") or "").strip()[:180],
    }


def validate(batch: list[Row], obj: dict[str, Any]) -> tuple[bool, str]:
    if not isinstance(obj.get("results"), list):
        return False, "missing results[]"
    ids = {r.record_id for r in batch}
    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for item in obj["results"]:
        if not isinstance(item, dict):
            return False, "non-object result"
        norm = normalize_result_item(item)
        if norm is None:
            return False, f"unnormalizable item {item!r}"[:220]
        rid = norm["record_id"]
        if rid not in ids:
            return False, f"unknown record_id {rid}"
        if rid in seen:
            return False, f"duplicate {rid}"
        seen.add(rid)
        normalized.append(norm)
    if seen != ids:
        return False, f"missing {sorted(ids - seen)}"
    obj["results"] = normalized
    return True, ""


def call_deepseek(
    model: str,
    prompt: str,
    batch: list[Row],
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
            "current_region_class": r.region_class,
            "rule_flags": r.rule_flags,
        }
        for r in batch
    ]
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Audit these records.\nrecords="
                + json.dumps(payload, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        # flash uses many reasoning tokens; keep headroom for JSON content
        "max_tokens": 8192,
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
    records: list[Row],
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
    done = 0
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
            done += 1
            if not res["ok"]:
                logs.append(
                    {
                        "pass": pass_name,
                        "record_ids": ids,
                        "ok": False,
                        "error": res["error"],
                    }
                )
            else:
                for item in res["response"]["results"]:
                    outputs[int(item["record_id"])] = {
                        "region_class": item["region_class"],
                        "class_ok": item["class_ok"],
                        "suitability": item["suitability"],
                        "unsuitable_reason": (item.get("unsuitable_reason") or "").strip(),
                        "certainty": item["certainty"],
                        "confidence": float(item["confidence"]),
                        "reason": (item.get("reason") or "").strip(),
                    }
                logs.append(
                    {
                        "pass": pass_name,
                        "record_ids": ids,
                        "ok": True,
                        "usage": res.get("usage", {}),
                    }
                )
            if done % 40 == 0 or done == total:
                print(
                    f"    {pass_name}: {done}/{total} "
                    f"valid={len(outputs)} fail={sum(1 for x in logs if not x['ok'])}",
                    flush=True,
                )
    return outputs, logs


def majority_decision(votes: list[dict[str, Any]]) -> dict[str, Any]:
    present = [v for v in votes if v and v.get("region_class")]
    n = len(present)
    if not present:
        return {
            "region_class": "ambiguous",
            "class_ok": "no",
            "suitability": "unsuitable",
            "unsuitable_reason": "ambiguous_name",
            "has_majority": False,
            "agreement": "0/0",
            "vote_split_pattern": "missing",
            "confidence": 0.0,
            "certainty": "low",
            "reason": "",
        }

    rc_counts = Counter(v["region_class"] for v in present)
    rc, rc_n = rc_counts.most_common(1)[0]
    suit_counts = Counter(v["suitability"] for v in present)
    suit, suit_n = suit_counts.most_common(1)[0]
    ok_counts = Counter(v["class_ok"] for v in present)
    class_ok, ok_n = ok_counts.most_common(1)[0]

    reason_counts = Counter(
        (v.get("unsuitable_reason") or "")
        for v in present
        if v.get("suitability") == "unsuitable" and v.get("unsuitable_reason")
    )
    unsuit_reason = reason_counts.most_common(1)[0][0] if reason_counts else ""
    if suit != "unsuitable":
        unsuit_reason = ""

    avg_conf = sum(float(v.get("confidence", 0)) for v in present) / n
    reasons = [v.get("reason", "") for v in present if v.get("reason")]

    # Accept majority from available votes:
    # 3 votes → need >=2; 2 votes → need unanimous 2/2; 1 vote → no majority
    if n >= 3:
        has_maj = rc_n >= 2
        split = "3-0" if rc_n == 3 else ("2-1" if rc_n == 2 else "1-1-1")
    elif n == 2:
        has_maj = rc_n == 2
        split = "2-0" if has_maj else "1-1"
    else:
        has_maj = False
        split = "1-0"

    if not has_maj:
        return {
            "region_class": "ambiguous",
            "class_ok": "no",
            "suitability": "unsuitable",
            "unsuitable_reason": "ambiguous_name",
            "has_majority": False,
            "agreement": f"{rc_n}/{n}",
            "vote_split_pattern": split,
            "confidence": round(avg_conf, 4),
            "certainty": "low",
            "reason": " | ".join(reasons[:3])[:700],
        }

    # Suitability: majority among available votes; tie → unsuitable
    need_suit = 2 if n >= 2 else 1
    if suit_n < need_suit:
        suit = "unsuitable"
        unsuit_reason = unsuit_reason or "other"
    if ok_n < need_suit:
        class_ok = "no" if any(v.get("class_ok") == "no" for v in present) else "yes"

    certainty = "high" if (rc_n == n and avg_conf >= 0.8) else "medium"
    return {
        "region_class": rc,
        "class_ok": class_ok,
        "suitability": suit,
        "unsuitable_reason": unsuit_reason,
        "has_majority": True,
        "agreement": f"{rc_n}/{n}",
        "vote_split_pattern": split,
        "confidence": round(avg_conf, 4),
        "certainty": certainty,
        "reason": " | ".join(reasons[:3])[:700],
        "suit_agreement": f"{suit_n}/{n}",
    }


def load_pass_cache(path: Path) -> tuple[dict[int, dict[str, Any]], list[dict[str, Any]]]:
    if not path.exists():
        return {}, []
    data = json.loads(path.read_text(encoding="utf-8"))
    return {int(k): v for k, v in data.get("outputs", {}).items()}, data.get("logs", [])


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
    records: list[Row],
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
    print(f"  {pass_name}: valid={len(out)}/{len(records)}", flush=True)
    return out


def pick_spotcheck(rows: list[Row], n: int) -> set[int]:
    """Stratified high-confidence non_neocortex names without suspicion flags."""
    cands = [
        r
        for r in rows
        if r.region_class == "non_neocortex"
        and r.final_certainty == "high"
        and not any(
            x.startswith("suspect_") or x == "flash_split" for x in r.rule_flags
        )
    ]
    cands.sort(key=lambda r: (-int(r.n_mentions or 0), r.structure_name.casefold()))
    # diversify by first letter / prefix
    picked: list[Row] = []
    seen_prefix: set[str] = set()
    for r in cands:
        pref = r.structure_name[:2].casefold()
        if pref in seen_prefix and len(picked) < n:
            continue
        seen_prefix.add(pref)
        picked.append(r)
        if len(picked) >= n:
            break
    if len(picked) < n:
        have = {r.record_id for r in picked}
        for r in cands:
            if r.record_id not in have:
                picked.append(r)
            if len(picked) >= n:
                break
    return {r.record_id for r in picked}


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fields = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def esc(v: object) -> str:
    return html.escape(str(v or ""), quote=True)


def write_html(
    path: Path,
    rows: list[dict[str, Any]],
    summary: dict[str, Any],
) -> None:
    total = len(rows)
    class_before = Counter(r["region_class_before"] for r in rows)
    class_after = Counter(r["region_class"] for r in rows)
    suit = Counter(r["suitability"] for r in rows)
    unsuit_reasons = Counter(
        r["unsuitable_reason"] for r in rows if r["suitability"] == "unsuitable"
    )
    corrected = [r for r in rows if r["class_corrected"] == "yes"]
    contam = [
        r
        for r in rows
        if r["region_class_before"] == "non_neocortex"
        and r["region_class"] == "neocortex"
    ]
    allo_flip = [
        r
        for r in rows
        if r["region_class_before"] == "neocortex"
        and r["region_class"] == "non_neocortex"
    ]
    suitable_nn = [
        r
        for r in rows
        if r["suitability"] == "suitable" and r["region_class"] == "non_neocortex"
    ]
    suitable_neo = [
        r
        for r in rows
        if r["suitability"] == "suitable" and r["region_class"] == "neocortex"
    ]

    def bars(counter: Counter[str], denom: int | None = None) -> str:
        d = total if denom is None else denom
        parts = []
        for label, count in counter.most_common():
            pct = 0 if d == 0 else count * 100 / d
            parts.append(
                f"<tr><td>{esc(label)}</td><td class='num'>{count}</td>"
                f"<td class='num'>{pct:.1f}%</td>"
                f"<td><div class='bar'><span style='width:{pct:.2f}%'></span></div></td></tr>"
            )
        return "\n".join(parts) if parts else "<tr><td colspan='4'>(none)</td></tr>"

    def table(items: list[dict[str, Any]], cols: list[str], limit: int = 80) -> str:
        head = "".join(f"<th>{esc(c)}</th>" for c in cols)
        body = []
        for r in items[:limit]:
            tds = "".join(f"<td>{esc(r.get(c, ''))}</td>" for c in cols)
            body.append(f"<tr>{tds}</tr>")
        if not body:
            body.append("<tr><td colspan='99'>(none)</td></tr>")
        note = (
            f"<p class='note'>showing {min(limit, len(items))} / {len(items)}</p>"
            if len(items) > limit
            else ""
        )
        return (
            f"{note}<table><thead><tr>{head}</tr></thead>"
            f"<tbody>{''.join(body)}</tbody></table>"
        )

    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    sample_cols = [
        "structure_name",
        "fullname",
        "n_mentions",
        "region_class_before",
        "region_class",
        "suitability",
        "unsuitable_reason",
        "audit_stage",
        "audit_reason",
    ]

    doc = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<title>Projection corpus curation — label audit &amp; suitability</title>
<style>
:root {{
  --bg: #f4f1ec; --ink: #1a1916; --muted: #5a544c; --line: #d6cec2;
  --card: #fffdf8; --accent: #0b5f4b; --warn: #9a3412; --bad: #7f1d1d;
}}
* {{ box-sizing: border-box; }}
body {{
  margin: 0; font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
  color: var(--ink); background:
    radial-gradient(1100px 480px at 8% -8%, #e3f0ea 0%, transparent 55%),
    radial-gradient(900px 400px at 100% 0%, #f1e6da 0%, transparent 50%),
    var(--bg);
  line-height: 1.45;
}}
main {{ max-width: 1140px; margin: 0 auto; padding: 32px 20px 72px; }}
h1 {{ font-size: 1.65rem; margin: 0 0 8px; letter-spacing: -0.02em; }}
h2 {{ font-size: 1.12rem; margin: 34px 0 10px; }}
.lead {{ color: var(--muted); margin: 0 0 22px; max-width: 78ch; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }}
.card {{
  background: var(--card); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 16px;
}}
.card-title {{ font-size: 0.75rem; color: var(--muted); text-transform: uppercase; letter-spacing: 0.04em; }}
.card-value {{ font-size: 1.5rem; font-weight: 650; margin-top: 4px; }}
.card-sub {{ font-size: 0.78rem; color: var(--muted); margin-top: 2px; }}
table {{ width: 100%; border-collapse: collapse; background: var(--card); border: 1px solid var(--line); }}
th, td {{ padding: 7px 9px; border-bottom: 1px solid var(--line); text-align: left; font-size: 0.86rem; vertical-align: top; }}
th {{ background: #efe9df; font-size: 0.74rem; text-transform: uppercase; letter-spacing: 0.03em; }}
.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
.bar {{ background: #ebe4d8; height: 8px; border-radius: 99px; overflow: hidden; }}
.bar span {{ display: block; height: 100%; background: var(--accent); }}
.note {{ color: var(--muted); font-size: 0.86rem; }}
code {{ background: #efe9df; padding: 1px 5px; border-radius: 4px; }}
.bad {{ color: var(--bad); }}
.warn {{ color: var(--warn); }}
</style>
</head>
<body>
<main>
  <h1>Projection corpus curation</h1>
  <p class="lead">
    ラベル監査（特に <code>non_neocortex</code> への新皮質混入）と、RCSテストデータ適性の精査。
    ルール事前フラグ + DeepSeek <code>v4-flash</code> 3-pass（票割れのみ <code>v4-pro</code>）。
    生成: {esc(generated)}。
    flash 3-pass + 票割れ pro 完了。未合意のみ事前ラベル保持（<code>audit_stage=unresolved</code>）。
  </p>

  <div class="grid">
    <div class="card"><div class="card-title">Total</div><div class="card-value">{total}</div></div>
    <div class="card"><div class="card-title">API audited</div><div class="card-value">{summary.get('api_records', 0)}</div>
      <div class="card-sub">rule-only {summary.get('rule_only_records', 0)}</div></div>
    <div class="card"><div class="card-title">Class corrected</div><div class="card-value">{len(corrected)}</div>
      <div class="card-sub">label changed</div></div>
    <div class="card"><div class="card-title bad">Neo in non-neo</div><div class="card-value">{len(contam)}</div>
      <div class="card-sub">contamination fixed</div></div>
    <div class="card"><div class="card-title warn">Neo→non-neo</div><div class="card-value">{len(allo_flip)}</div>
      <div class="card-sub">allo/meso flips</div></div>
    <div class="card"><div class="card-title">Suitable</div><div class="card-value">{suit.get('suitable', 0)}</div></div>
    <div class="card"><div class="card-title">Suitable non-neo</div><div class="card-value">{len(suitable_nn)}</div>
      <div class="card-sub">improvement-loop set</div></div>
    <div class="card"><div class="card-title">Suitable neo</div><div class="card-value">{len(suitable_neo)}</div></div>
  </div>

  <h2>Region class — before</h2>
  <table><thead><tr><th>Label</th><th class="num">N</th><th class="num">%</th><th></th></tr></thead>
  <tbody>{bars(class_before)}</tbody></table>

  <h2>Region class — after audit</h2>
  <table><thead><tr><th>Label</th><th class="num">N</th><th class="num">%</th><th></th></tr></thead>
  <tbody>{bars(class_after)}</tbody></table>

  <h2>Suitability</h2>
  <table><thead><tr><th>Label</th><th class="num">N</th><th class="num">%</th><th></th></tr></thead>
  <tbody>{bars(suit)}</tbody></table>

  <h2>Unsuitable reasons</h2>
  <table><thead><tr><th>Reason</th><th class="num">N</th><th class="num">%</th><th></th></tr></thead>
  <tbody>{bars(unsuit_reasons, suit.get('unsuitable', 0) or 1)}</tbody></table>

  <h2>API priority mix</h2>
  <table><thead><tr><th>Priority</th><th class="num">N</th><th class="num">%</th><th></th></tr></thead>
  <tbody>{bars(Counter(r['api_priority'] for r in rows if r.get('api_priority')), summary.get('api_records', 1) or 1)}</tbody></table>

  <h2 class="bad">Contamination fixed — non_neocortex → neocortex</h2>
  {table(contam, sample_cols, 100)}

  <h2 class="warn">Flips — neocortex → non_neocortex</h2>
  {table(allo_flip, sample_cols, 80)}

  <h2>All class corrections</h2>
  {table(corrected, sample_cols, 120)}

  <h2>Suitable non_neocortex (top by mentions)</h2>
  {table(sorted(suitable_nn, key=lambda r: -int(r.get('n_mentions') or 0)), [
      'structure_name','fullname','species','n_mentions','n_papers',
      'region_class','audit_stage','final_certainty'
  ], 60)}

  <h2>Unsuitable samples</h2>
  {table([r for r in rows if r['suitability']=='unsuitable'], [
      'structure_name','fullname','n_mentions','region_class',
      'unsuitable_reason','audit_stage','audit_reason'
  ], 80)}

  <h2>Summary JSON</h2>
  <pre style="background:#fffdf8;border:1px solid var(--line);padding:12px;overflow:auto;font-size:0.78rem;">{esc(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>
</main>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def main() -> int:
    args = parse_args()
    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    rows = load_rows(args.input, args.full, args.limit)
    print(f"records={len(rows)} input={args.input}", flush=True)

    for r in rows:
        r.rule_flags = rule_flags(r)

    spot_ids = pick_spotcheck(rows, args.spotcheck_n)
    for r in rows:
        need, why = decide_api(r, spot_ids)
        r.needs_api = need
        r.api_priority = why

    api_rows = [r for r in rows if r.needs_api]
    print(
        f"api_targets={len(api_rows)} rule_only={len(rows) - len(api_rows)}",
        flush=True,
    )
    print(
        "api_priority="
        + json.dumps(dict(Counter(r.api_priority for r in api_rows)), ensure_ascii=False),
        flush=True,
    )
    print(
        "rule_flag_top="
        + json.dumps(Counter(f for r in rows for f in r.rule_flags).most_common(20), ensure_ascii=False),
        flush=True,
    )

    flash_specs = [
        ("cur_flash_a", FLASH_MODEL, PROMPT_FLASH_A),
        ("cur_flash_b", FLASH_MODEL, PROMPT_FLASH_B),
        ("cur_flash_c", FLASH_MODEL, PROMPT_FLASH_C),
    ]
    pro_specs = [
        ("cur_pro_a", PRO_MODEL, PROMPT_PRO_A),
        ("cur_pro_b", PRO_MODEL, PROMPT_PRO_B),
        ("cur_pro_c", PRO_MODEL, PROMPT_PRO_C),
    ]
    flash_out: dict[str, dict[int, dict[str, Any]]] = {k: {} for k, _, _ in flash_specs}
    pro_out: dict[str, dict[int, dict[str, Any]]] = {k: {} for k, _, _ in pro_specs}

    if api_rows and not args.report_only:
        api_key = os.environ.get("DEEPSEEK_API_KEY")
        if not api_key:
            print("DEEPSEEK_API_KEY is not set.", flush=True)
            return 2
        for name, model, prompt in flash_specs:
            flash_out[name] = ensure_pass(
                api_rows, name, model, prompt, api_key, out_dir,
                args.batch_size, args.workers,
            )
        split_rows: list[Row] = []
        for r in api_rows:
            dec = majority_decision(
                [
                    flash_out["cur_flash_a"].get(r.record_id, {}),
                    flash_out["cur_flash_b"].get(r.record_id, {}),
                    flash_out["cur_flash_c"].get(r.record_id, {}),
                ]
            )
            if not dec["has_majority"]:
                split_rows.append(r)
        print(f"flash splits for pro: {len(split_rows)}", flush=True)
        (out_dir / "cur_flash_split_ids.json").write_text(
            json.dumps([r.record_id for r in split_rows], indent=2),
            encoding="utf-8",
        )
        if split_rows:
            for name, model, prompt in pro_specs:
                pro_out[name] = ensure_pass(
                    split_rows, name, model, prompt, api_key, out_dir,
                    args.batch_size, args.workers,
                )
    elif args.report_only:
        for name, _, _ in flash_specs:
            flash_out[name], _ = load_pass_cache(out_dir / f"{name}_raw.json")
        for name, _, _ in pro_specs:
            pro_out[name], _ = load_pass_cache(out_dir / f"{name}_raw.json")

    out_rows: list[dict[str, Any]] = []
    for r in rows:
        before = r.region_class
        seed_suit, seed_reason = rule_suitability_seed(r)

        if r.needs_api:
            f_votes = [
                flash_out["cur_flash_a"].get(r.record_id, {}),
                flash_out["cur_flash_b"].get(r.record_id, {}),
                flash_out["cur_flash_c"].get(r.record_id, {}),
            ]
            flash_dec = majority_decision(f_votes)
            if flash_dec["has_majority"]:
                dec = flash_dec
                stage = "flash"
            else:
                p_votes = [
                    pro_out["cur_pro_a"].get(r.record_id, {}),
                    pro_out["cur_pro_b"].get(r.record_id, {}),
                    pro_out["cur_pro_c"].get(r.record_id, {}),
                ]
                pro_dec = majority_decision(p_votes)
                if pro_dec["has_majority"]:
                    dec = pro_dec
                    stage = "pro"
                else:
                    # No consensus.
                    # Contamination suspects with clear border isocortex markers
                    # → neocortex (matches flash majority on ACC/insula/RSC siblings).
                    # Else keep prior class.
                    prior = before if before in REGION_LABELS else "ambiguous"
                    if prior == "unresolved":
                        prior = "ambiguous"
                    b = blob(r)
                    allo = any(k in b for k in ALLO_MESO_OK)
                    border_neo = any(
                        k in b
                        for k in (
                            "cingulate",
                            "insula",
                            "insular",
                            "retrosplenial",
                            "prostriata",
                            "prelimbic",
                            "infralimbic",
                            "orbitofrontal",
                            "prefrontal",
                        )
                    )
                    if (
                        r.api_priority == "contamination_suspect"
                        and prior == "non_neocortex"
                        and border_neo
                        and not allo
                    ):
                        prior = "neocortex"
                        class_ok_keep = "no"
                        reason_prefix = (
                            "no_vote_majority; contamination_suspect → neocortex. "
                        )
                    else:
                        class_ok_keep = "yes"
                        reason_prefix = "no_vote_majority; keep prior. "
                    seed_s, seed_r = rule_suitability_seed(r)
                    if seed_s:
                        suitability_keep = seed_s
                        unsuit_keep = seed_r
                    elif prior in {"neocortex", "non_neocortex"}:
                        suitability_keep = "suitable"
                        unsuit_keep = ""
                    else:
                        suitability_keep = "unsuitable"
                        unsuit_keep = "ambiguous_name"
                    dec = {
                        "region_class": prior,
                        "class_ok": class_ok_keep,
                        "suitability": suitability_keep,
                        "unsuitable_reason": unsuit_keep,
                        "certainty": "low",
                        "confidence": 0.45,
                        "reason": (
                            reason_prefix + (flash_dec.get("reason") or "")
                        )[:700],
                        "agreement": flash_dec.get("agreement", ""),
                        "vote_split_pattern": flash_dec.get(
                            "vote_split_pattern", "missing"
                        ),
                    }
                    stage = "unresolved"
            region_class = dec["region_class"]
            suitability = dec["suitability"]
            unsuit_reason = dec["unsuitable_reason"]
            certainty = dec["certainty"]
            confidence = dec["confidence"]
            reason = dec["reason"]
            class_ok_vote = dec["class_ok"]
            agreement = dec.get("agreement", "")
            vote_split = dec.get("vote_split_pattern", "")
        else:
            region_class = before if before in REGION_LABELS | {"unresolved"} else "ambiguous"
            if region_class == "unresolved":
                region_class = "ambiguous"
                suitability = "unsuitable"
                unsuit_reason = "ambiguous_name"
            elif seed_suit:
                suitability = seed_suit
                unsuit_reason = seed_reason
            else:
                # Keep high-confidence neo / non-neo as suitable by default
                if region_class in {"neocortex", "non_neocortex"}:
                    suitability = "suitable"
                    unsuit_reason = ""
                else:
                    suitability = "unsuitable"
                    unsuit_reason = "other" if region_class == "other" else "ambiguous_name"
            certainty = r.final_certainty or "high"
            confidence = r.final_confidence or "1.0"
            reason = "rule_keep: " + (",".join(r.rule_flags) if r.rule_flags else "clean")
            class_ok_vote = "yes"
            agreement = ""
            vote_split = ""
            stage = "rule"

        # If API says suitable but region is other/ambiguous → force unsuitable
        if region_class in {"other", "ambiguous"} and suitability == "suitable":
            suitability = "unsuitable"
            unsuit_reason = unsuit_reason or (
                "other" if region_class == "other" else "ambiguous_name"
            )

        corrected = "yes" if region_class != before else "no"
        out_rows.append(
            {
                "record_id": r.record_id,
                "structure_name": r.structure_name,
                "fullname": r.fullname,
                "species": r.species,
                "paper": r.paper,
                "n_mentions": r.n_mentions,
                "n_papers": r.n_papers,
                "region_class_before": before,
                "region_class": region_class,
                "class_corrected": corrected,
                "class_ok_vote": class_ok_vote,
                "suitability": suitability,
                "unsuitable_reason": unsuit_reason,
                "audit_stage": stage,
                "api_priority": r.api_priority,
                "rule_flags": "|".join(r.rule_flags),
                "final_certainty": certainty,
                "final_confidence": confidence,
                "audit_agreement": agreement,
                "audit_vote_split": vote_split,
                "audit_reason": reason,
                "prior_decision_stage": r.decision_stage,
                "prior_certainty": r.final_certainty,
                "prior_reason": r.final_reason[:300],
            }
        )

    # Sort by mentions desc for readable CSVs
    out_rows.sort(key=lambda r: (-int(r["n_mentions"] or 0), r["structure_name"].casefold()))

    suitable = [r for r in out_rows if r["suitability"] == "suitable"]
    suitable_nn = [
        r for r in suitable if r["region_class"] == "non_neocortex"
    ]
    suitable_neo = [r for r in suitable if r["region_class"] == "neocortex"]

    slim_fields = [
        "structure_name",
        "fullname",
        "species",
        "paper",
        "n_mentions",
        "n_papers",
        "region_class",
        "suitability",
        "unsuitable_reason",
        "class_corrected",
        "region_class_before",
        "audit_stage",
        "final_certainty",
        "final_confidence",
    ]

    def slim(rows_in: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [{k: r.get(k, "") for k in slim_fields} for r in rows_in]

    summary = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "schema": "projection_corpus_curation_v1",
        "input": str(args.input),
        "total_records": len(out_rows),
        "api_records": len(api_rows),
        "rule_only_records": len(rows) - len(api_rows),
        "api_priority_counts": dict(Counter(r.api_priority for r in api_rows)),
        "region_class_before": dict(Counter(r["region_class_before"] for r in out_rows)),
        "region_class_after": dict(Counter(r["region_class"] for r in out_rows)),
        "class_corrected_n": sum(1 for r in out_rows if r["class_corrected"] == "yes"),
        "contamination_non_neo_to_neo": sum(
            1
            for r in out_rows
            if r["region_class_before"] == "non_neocortex"
            and r["region_class"] == "neocortex"
        ),
        "flip_neo_to_non_neo": sum(
            1
            for r in out_rows
            if r["region_class_before"] == "neocortex"
            and r["region_class"] == "non_neocortex"
        ),
        "suitability_counts": dict(Counter(r["suitability"] for r in out_rows)),
        "unsuitable_reason_counts": dict(
            Counter(
                r["unsuitable_reason"]
                for r in out_rows
                if r["suitability"] == "unsuitable"
            )
        ),
        "suitable_total": len(suitable),
        "suitable_non_neocortex": len(suitable_nn),
        "suitable_neocortex": len(suitable_neo),
        "audit_stage_counts": dict(Counter(r["audit_stage"] for r in out_rows)),
        "models": {"flash": FLASH_MODEL, "pro": PRO_MODEL},
        "workers": args.workers,
        "batch_size": args.batch_size,
        "spotcheck_n": args.spotcheck_n,
        "notes": [
            "DeepSeek flash 3-pass + pro on splits completed (resume after top-up).",
            "Majority accepted from available flash votes (incl. 2/2 when a pass missing).",
            "No-majority rows keep prior region_class (audit_stage=unresolved).",
        ],
    }

    write_csv(out_dir / "curated_full.csv", out_rows)
    write_csv(out_dir / "curated_suitable.csv", slim(suitable))
    write_csv(out_dir / "curated_non_neocortex.csv", slim(suitable_nn))
    write_csv(out_dir / "curated_neocortex.csv", slim(suitable_neo))
    # Convenience copy at build_testdata root for improvement loop
    write_csv(ROOT / "rcs_projection_corpus_curated_non_neocortex.csv", slim(suitable_nn))
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_html(out_dir / "curation_report.html", out_rows, summary)

    print(json.dumps({
        "class_corrected": summary["class_corrected_n"],
        "contamination_non_neo_to_neo": summary["contamination_non_neo_to_neo"],
        "flip_neo_to_non_neo": summary["flip_neo_to_non_neo"],
        "suitable_non_neocortex": summary["suitable_non_neocortex"],
        "suitable_neocortex": summary["suitable_neocortex"],
        "suitable_total": summary["suitable_total"],
    }, ensure_ascii=False), flush=True)
    print(f"wrote {out_dir / 'curation_report.html'}", flush=True)
    print(f"wrote {ROOT / 'rcs_projection_corpus_curated_non_neocortex.csv'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
