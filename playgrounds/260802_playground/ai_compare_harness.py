#!/usr/bin/env python3
"""RCS vs 3-AI comparison on rcs_ai_compare.csv (full HOMBA catalog in prompt).

Pipeline
--------
1. map      — RCS (reuseable) + DeepSeek flash/pro + GPT-5.6 Luna
             AI prompts include the full HOMBA catalog (~2342 entries)
2. validate — deepseek-v4-flash × 3-pass majority (same as eval_harness)
3. report   — HTML comparison report with inference costs

Purpose: measure whether catalog-in-context LLMs can replace RCS for
HOMBA grounding — not an AI ops deployment path.

Usage (repo root):
    python playgrounds/260802_playground/ai_compare_harness.py --stage all --workers 8
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.rosetta_candidate_generator import RosettaCandidateGenerator  # noqa: E402

RCS_DIR = REPO_ROOT / "rcs"
HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
INPUT_CSV = REPO_ROOT / "build_testdata" / "rcs_ai_compare.csv"
RUNS_DIR = HERE / "runs" / "ai_compare"
CACHE_DIR = HERE / "cache"
MAP_CACHE = CACHE_DIR / "ai_compare_mapping.json"
JUDGE_CACHE = CACHE_DIR / "ai_compare_judgements.json"
RCS_RESULTS_PATH = RUNS_DIR / "rcs_results.json"

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
OPENAI_URL = "https://api.openai.com/v1/chat/completions"

SYSTEMS = (
    "rcs",
    "deepseek_v4_flash",
    "deepseek_v4_pro",
    "gpt56_luna",
)

AI_MODELS: dict[str, dict[str, Any]] = {
    "deepseek_v4_flash": {
        "provider": "deepseek",
        "model": "deepseek-v4-flash",
        "label": "DeepSeek V4 Flash",
        # smaller batches: catalog (~30k tok) is in every request
        "batch_size": 5,
    },
    "deepseek_v4_pro": {
        "provider": "deepseek",
        "model": "deepseek-v4-pro",
        "label": "DeepSeek V4 Pro",
        "batch_size": 5,
    },
    "gpt56_luna": {
        "provider": "openai",
        "model": "gpt-5.6-luna",
        "label": "GPT-5.6 Luna",
        "batch_size": 5,
    },
}

# Official regular rates (USD / 1M tokens), Aug 2026
PRICING: dict[str, dict[str, float]] = {
    "deepseek-v4-flash": {
        "input_miss": 0.14,
        "input_hit": 0.0028,
        "output": 0.28,
    },
    "deepseek-v4-pro": {
        "input_miss": 0.435,
        "input_hit": 0.003625,
        "output": 0.87,
    },
    "gpt-5.6-luna": {
        "input_miss": 0.20,
        "input_hit": 0.02,
        "output": 1.20,
    },
}

MAP_SYSTEM_PREFIX = """You map mammalian brain-region queries to HOMBA ontology entries.

Task: given a short query (full name or abbreviation), choose the single best
entry from the HOMBA CATALOG below (no paper context).

Rules:
- You MUST pick homba_id from the catalog. Do not invent IDs.
- Prefer the conventional neuroanatomy sense used in mammalian literature.
- `name` must be the catalog's unified_ontology_name for the chosen ID.
- If multiple catalog rows are plausible, pick the most common literature sense
  and lower confidence. Still return a catalog ID (best effort).
- Return STRICT JSON only, no markdown.

Schema:
{
  "results": [
    {
      "record_id": <int>,
      "homba_id": "<HOMBA:... from catalog>",
      "name": "<catalog unified_ontology_name>",
      "confidence": <float 0..1>,
      "reason": "<max 160 chars>"
    }
  ]
}

HOMBA CATALOG (format: id|acronym|name ; one entry per line):
"""

_CATALOG_TEXT: str | None = None


def load_homba_catalog_text() -> str:
    global _CATALOG_TEXT
    if _CATALOG_TEXT is not None:
        return _CATALOG_TEXT
    lines: list[str] = []
    with HOMBA_CSV.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            hid = (row.get("unified_ontology_id") or "").strip()
            name = (row.get("unified_ontology_name") or "").strip()
            acr = (row.get("unified_ontology_acronym") or "").strip()
            if not hid or not name:
                continue
            lines.append(f"{hid}|{acr}|{name}")
    _CATALOG_TEXT = "\n".join(lines)
    return _CATALOG_TEXT


def map_system_prompt() -> str:
    return MAP_SYSTEM_PREFIX + load_homba_catalog_text()

# Reuse eval_harness judge prompts
JUDGE_BASE = """You are reviewing top-1 candidate consistency for mammalian brain regions.

Important:
- There is NO established ground-truth dataset in this project.
- Judge whether `top1_name` is consistent with the `query` being evaluated.
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
JUDGE_PASSES = [
    ("pass1", "deepseek-v4-flash", PROMPT_A),
    ("pass2", "deepseek-v4-flash", PROMPT_B),
    ("pass3", "deepseek-v4-flash", PROMPT_C),
]
JUDGE_LABELS = {
    "aligned",
    "broader_parent",
    "partial_or_narrower",
    "wrong",
    "ambiguous",
    "source_or_ontology_issue",
}


@dataclass
class UsageAccum:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0
    cache_miss_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: float = 0.0
    errors: int = 0

    def add(self, model: str, usage: dict[str, Any]) -> None:
        self.calls += 1
        prompt = int(usage.get("prompt_tokens") or 0)
        completion = int(usage.get("completion_tokens") or 0)
        details = usage.get("prompt_tokens_details") or {}
        cached = int(
            usage.get("prompt_cache_hit_tokens")
            or details.get("cached_tokens")
            or 0
        )
        miss = int(
            usage.get("prompt_cache_miss_tokens")
            or max(0, prompt - cached)
        )
        reasoning = int(
            (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
            or 0
        )
        self.prompt_tokens += prompt
        self.completion_tokens += completion
        self.cached_tokens += cached
        self.cache_miss_tokens += miss
        self.reasoning_tokens += reasoning
        price = PRICING.get(model, {})
        self.cost_usd += (
            (miss / 1_000_000) * price.get("input_miss", 0.0)
            + (cached / 1_000_000) * price.get("input_hit", 0.0)
            + (completion / 1_000_000) * price.get("output", 0.0)
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "cached_tokens": self.cached_tokens,
            "cache_miss_tokens": self.cache_miss_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "errors": self.errors,
        }


@dataclass
class RowPred:
    id: str
    structure_name: str
    fullname: str
    expected_homba_id: str
    expected_homba_name: str
    difficulty: str
    query_kind: str
    source: str
    gt_status: str
    n_mentions: str
    notes: str
    systems: dict[str, dict[str, Any]] = field(default_factory=dict)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--stage", choices=["map", "validate", "report", "all"], default="all")
    p.add_argument("--input", type=Path, default=INPUT_CSV)
    p.add_argument("--workers", type=int, default=32)
    p.add_argument("--judge-batch-size", type=int, default=4)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--remap", action="store_true", help="Ignore mapping cache.")
    p.add_argument("--revalidate", action="store_true", help="Ignore judge cache.")
    p.add_argument(
        "--systems",
        default=",".join(SYSTEMS),
        help="Comma-separated systems to run for map stage.",
    )
    return p.parse_args()


def _load_json(path: Path) -> dict[str, Any]:
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {}


def _save_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def extract_json_obj(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise ValueError("Empty content")
    # strip markdown fences
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError("No JSON object found")
    return json.loads(m.group(0))


def load_dataset(path: Path, limit: int = 0) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            rows.append(dict(row))
            if limit and len(rows) >= limit:
                break
    return rows


def http_chat(
    *,
    url: str,
    api_key: str,
    body: dict[str, Any],
    retries: int = 5,
) -> dict[str, Any]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt in range(1, retries + 1):
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:400]}"
            if exc.code not in (429, 500, 502, 503) and attempt >= 2:
                break
            time.sleep(min(2**attempt, 30))
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
            time.sleep(min(2**attempt, 12))
    raise RuntimeError(last)


def run_rcs(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]]:
    gen = RosettaCandidateGenerator(
        HOMBA_CSV,
        token_rules_csv=RCS_DIR / "homba_token_rules.csv",
        alias_rules_csv=RCS_DIR / "homba_alias_rules.csv",
        abbrev_rules_csv=RCS_DIR / "homba_abbrev_rules.csv",
    )
    out: dict[str, dict[str, Any]] = {}
    for i, row in enumerate(rows, 1):
        q = row["structure_name"].strip()
        cands = gen.generate(q, top_k=3)
        if cands:
            top = cands[0]
            out[row["id"]] = {
                "homba_id": str(top.get("homba_id") or ""),
                "name": str(top.get("name") or ""),
                "confidence": float(top.get("score") or 0),
                "reason": f"rcs methods={top.get('methods')}",
                "top3": [
                    {
                        "homba_id": c.get("homba_id"),
                        "name": c.get("name"),
                        "score": c.get("score"),
                    }
                    for c in cands[:3]
                ],
            }
        else:
            out[row["id"]] = {
                "homba_id": "",
                "name": "",
                "confidence": 0.0,
                "reason": "rcs_no_match",
                "top3": [],
            }
        if i % 25 == 0 or i == len(rows):
            print(f"  RCS {i}/{len(rows)}", flush=True)
    return out


def _normalize_map_item(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        rid = int(item.get("record_id"))
    except Exception:  # noqa: BLE001
        return None
    hid = str(item.get("homba_id") or "").strip()
    if hid and not hid.upper().startswith("HOMBA:"):
        # allow bare numeric
        if re.fullmatch(r"(AA)?\d+", hid, re.I):
            hid = f"HOMBA:{hid}"
        else:
            hid = ""
    name = str(item.get("name") or "").strip()
    if not name and not hid:
        return None
    try:
        conf = float(item.get("confidence", 0.5))
    except Exception:  # noqa: BLE001
        conf = 0.5
    return {
        "record_id": rid,
        "homba_id": hid,
        "name": name,
        "confidence": min(1.0, max(0.0, conf)),
        "reason": str(item.get("reason") or "")[:200],
    }


def map_batch_ai(
    system_key: str,
    batch: list[dict[str, str]],
    base_id: int,
    api_keys: dict[str, str],
) -> dict[str, Any]:
    cfg = AI_MODELS[system_key]
    id_map = {base_id + i: row for i, row in enumerate(batch)}
    payload = [
        {
            "record_id": rid,
            "query": row["structure_name"],
            "fullname_hint": row.get("fullname") or "",
            "query_kind": row.get("query_kind") or "",
        }
        for rid, row in id_map.items()
    ]
    # Intentionally do NOT send expected HOMBA.
    user = (
        "Map each query to the best HOMBA structure. "
        "fullname_hint is optional corpus expansion context; judge the query itself.\n"
        "records=" + json.dumps(payload, ensure_ascii=False)
    )
    provider = cfg["provider"]
    model = cfg["model"]
    system = map_system_prompt()
    if provider == "deepseek":
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": 0,
            "max_tokens": 4096,
            "thinking": {"type": "disabled"},
        }
        url = DEEPSEEK_URL
        key = api_keys["deepseek"]
    else:
        body = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "max_completion_tokens": 4096,
            "reasoning_effort": "low",
        }
        url = OPENAI_URL
        key = api_keys["openai"]

    data = http_chat(url=url, api_key=key, body=body)
    msg = data["choices"][0]["message"]
    content = msg.get("content") or msg.get("reasoning_content") or ""
    obj = extract_json_obj(content)
    if not isinstance(obj.get("results"), list):
        raise ValueError("missing results[]")
    results: dict[str, dict[str, Any]] = {}
    for item in obj["results"]:
        norm = _normalize_map_item(item) if isinstance(item, dict) else None
        if not norm:
            continue
        row = id_map.get(norm["record_id"])
        if not row:
            continue
        results[row["id"]] = {
            "homba_id": norm["homba_id"],
            "name": norm["name"],
            "confidence": norm["confidence"],
            "reason": norm["reason"],
            "top3": [],
        }
    missing = [row["id"] for row in batch if row["id"] not in results]
    if missing:
        raise ValueError(f"incomplete batch missing={missing[:5]}")
    return {"ok": True, "results": results, "usage": data.get("usage", {}), "model": model}


def run_ai_system(
    system_key: str,
    rows: list[dict[str, str]],
    api_keys: dict[str, str],
    cache: dict[str, Any],
    workers: int,
    remap: bool,
    usage: UsageAccum,
) -> dict[str, dict[str, Any]]:
    cfg = AI_MODELS[system_key]
    sys_cache: dict[str, Any] = cache.setdefault(system_key, {})
    if remap:
        sys_cache.clear()

    pending = [r for r in rows if r["id"] not in sys_cache]
    print(
        f"  {system_key}: model={cfg['model']} "
        f"cached={len(rows)-len(pending)} pending={len(pending)}",
        flush=True,
    )
    if not pending:
        return {r["id"]: sys_cache[r["id"]] for r in rows}

    batch_size = int(cfg["batch_size"])
    batches = [pending[i : i + batch_size] for i in range(0, len(pending), batch_size)]
    done = 0
    fails = 0

    def _one(bi: int, batch: list[dict[str, str]]) -> dict[str, Any]:
        try:
            return map_batch_ai(system_key, batch, bi * 1000, api_keys)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "model": cfg["model"]}

    with ThreadPoolExecutor(max_workers=min(workers, max(1, len(batches)))) as ex:
        futs = {ex.submit(_one, i, b): b for i, b in enumerate(batches)}
        for fut in as_completed(futs):
            batch = futs[fut]
            res = fut.result()
            if not res.get("ok"):
                fails += 1
                usage.errors += 1
                print(f"    fail batch n={len(batch)}: {res.get('error')}", flush=True)
                # retry once serially with half batch
                half = max(1, len(batch) // 2)
                for j in range(0, len(batch), half):
                    sub = batch[j : j + half]
                    try:
                        r2 = map_batch_ai(system_key, sub, j * 1000, api_keys)
                        usage.add(cfg["model"], r2.get("usage") or {})
                        for rid, pred in r2["results"].items():
                            sys_cache[rid] = pred
                            done += 1
                    except Exception as exc:  # noqa: BLE001
                        usage.errors += 1
                        for row in sub:
                            sys_cache[row["id"]] = {
                                "homba_id": "",
                                "name": "",
                                "confidence": 0.0,
                                "reason": f"error: {exc}"[:200],
                                "top3": [],
                            }
                continue
            usage.add(cfg["model"], res.get("usage") or {})
            for rid, pred in res["results"].items():
                sys_cache[rid] = pred
                done += 1
            if done % 20 == 0 or done >= len(pending):
                _save_json(MAP_CACHE, cache)
                print(
                    f"    {system_key}: mapped~{done}/{len(pending)} "
                    f"cost=${usage.cost_usd:.4f} fails={fails}",
                    flush=True,
                )

    _save_json(MAP_CACHE, cache)
    return {r["id"]: sys_cache.get(r["id"], {}) for r in rows}


def load_cached_rcs(rows: list[dict[str, str]]) -> dict[str, dict[str, Any]] | None:
    """Load previously saved RCS top-1 keyed by dataset id."""
    if not RCS_RESULTS_PATH.exists():
        return None
    data = json.loads(RCS_RESULTS_PATH.read_text(encoding="utf-8"))
    by_id = {
        r["id"]: r.get("rcs") or {}
        for r in data.get("records", [])
        if r.get("id")
    }
    need = [r["id"] for r in rows]
    if not need or any(i not in by_id or not by_id[i] for i in need):
        return None
    return {i: by_id[i] for i in need}


def stage_map(args: argparse.Namespace) -> dict[str, Any]:
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_dataset(args.input, args.limit)
    wanted = [s.strip() for s in args.systems.split(",") if s.strip()]
    catalog = load_homba_catalog_text()
    print(
        f"[map] rows={len(rows)} systems={wanted} "
        f"catalog_entries={catalog.count(chr(10))+1} "
        f"catalog_chars={len(catalog)}",
        flush=True,
    )

    cache = {} if args.remap else _load_json(MAP_CACHE)
    # Drop any legacy sol cache entries
    cache.pop("gpt56_sol", None)
    api_keys = {
        "deepseek": os.environ.get("DEEPSEEK_API_KEY", ""),
        "openai": os.environ.get("OPENAI_API_KEY", ""),
    }
    usages: dict[str, UsageAccum] = {k: UsageAccum() for k in AI_MODELS}
    preds: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)

    if "rcs" in wanted:
        # --remap refreshes AI cache only; RCS is reused when available
        cached = load_cached_rcs(rows)
        if cached is not None:
            print(f"[map] reuse RCS from {RCS_RESULTS_PATH.name}", flush=True)
            for rid, pred in cached.items():
                preds[rid]["rcs"] = pred
        else:
            print("[map] running RCS...", flush=True)
            rcs = run_rcs(rows)
            for rid, pred in rcs.items():
                preds[rid]["rcs"] = pred
            # persist for future reuse
            _save_json(
                RCS_RESULTS_PATH,
                {
                    "records": [
                        {
                            "id": row["id"],
                            "structure_name": row["structure_name"],
                            "rcs": preds[row["id"]]["rcs"],
                        }
                        for row in rows
                    ]
                },
            )

    for system_key in wanted:
        if system_key == "rcs":
            continue
        if system_key not in AI_MODELS:
            raise SystemExit(f"unknown system: {system_key}")
        provider = AI_MODELS[system_key]["provider"]
        keyname = "deepseek" if provider == "deepseek" else "openai"
        if not api_keys[keyname]:
            raise SystemExit(f"{keyname.upper()}_API_KEY not set")
        print(f"[map] running {system_key} (catalog-in-context)...", flush=True)
        out = run_ai_system(
            system_key,
            rows,
            api_keys,
            cache,
            args.workers,
            args.remap,
            usages[system_key],
        )
        for rid, pred in out.items():
            preds[rid][system_key] = pred

    catalog_ids = {
        line.split("|", 1)[0].strip()
        for line in load_homba_catalog_text().splitlines()
        if line.strip()
    }

    # Assemble records
    records: list[dict[str, Any]] = []
    for row in rows:
        rec = {
            "id": row["id"],
            "structure_name": row["structure_name"],
            "fullname": row.get("fullname", ""),
            "expected_homba_id": row.get("expected_homba_id", ""),
            "expected_homba_name": row.get("expected_homba_name", ""),
            "difficulty": row.get("difficulty", ""),
            "query_kind": row.get("query_kind", ""),
            "source": row.get("source", ""),
            "gt_status": row.get("gt_status", ""),
            "n_mentions": row.get("n_mentions", ""),
            "notes": row.get("notes", ""),
            "mode": "catalog_in_context",
            "systems": preds.get(row["id"], {}),
        }
        for sk, pred in rec["systems"].items():
            eid = (rec["expected_homba_id"] or "").strip()
            pid = (pred.get("homba_id") or "").strip()
            pred["id_match"] = bool(eid and pid and eid == pid)
            en = _norm_name(rec["expected_homba_name"])
            pn = _norm_name(pred.get("name") or "")
            pred["name_match"] = bool(en and pn and (en == pn or en in pn or pn in en))
            pred["homba_id_exists"] = bool(pid and pid in catalog_ids)
            pred["raw_id_hallucinated"] = bool(pid and pid not in catalog_ids)
        records.append(rec)

    # Name → RCS resolve (ontology grounding via predicted name)
    print("[map] resolving predicted names via RCS for grounding metrics...", flush=True)
    gen = RosettaCandidateGenerator(
        HOMBA_CSV,
        token_rules_csv=RCS_DIR / "homba_token_rules.csv",
        alias_rules_csv=RCS_DIR / "homba_alias_rules.csv",
        abbrev_rules_csv=RCS_DIR / "homba_abbrev_rules.csv",
    )
    for i, rec in enumerate(records, 1):
        eid = (rec.get("expected_homba_id") or "").strip()
        scored = rec.get("gt_status") != "open" and bool(eid)
        for sk, pred in rec["systems"].items():
            name = (pred.get("name") or "").strip()
            resolved_id = ""
            if name:
                cands = gen.generate(name, top_k=1)
                if cands:
                    resolved_id = str(cands[0].get("homba_id") or "")
            pred["resolved_via_name_id"] = resolved_id
            pred["resolved_id_match"] = bool(
                scored and resolved_id and resolved_id == eid
            )
        if i % 25 == 0 or i == len(records):
            print(f"  resolve {i}/{len(records)}", flush=True)

    costs = {
        "mode": "catalog_in_context",
        "catalog_entries": load_homba_catalog_text().count("\n") + 1,
        "pricing_note": (
            "USD regular rates Aug 2026; DeepSeek cache hit/miss; "
            "OpenAI cache read as input_hit. Peak-hour surcharges not applied. "
            "Full HOMBA catalog is included in every AI mapping prompt."
        ),
        "pricing": PRICING,
        "inference": {k: v.as_dict() for k, v in usages.items() if k in wanted},
        "inference_total_usd": round(
            sum(v.cost_usd for k, v in usages.items() if k in wanted), 6
        ),
    }
    _save_json(RUNS_DIR / "mapping_results.json", {"records": records})
    _save_json(RUNS_DIR / "costs.json", costs)
    print(
        f"[map] wrote mapping_results.json  inference_total=${costs['inference_total_usd']}",
        flush=True,
    )
    return {"records": records, "costs": costs}


def _norm_name(s: str) -> str:
    s = (s or "").casefold()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def judge_cache_key(system: str, query: str, top_id: str, top_name: str) -> str:
    return f"{system}||{query}||{top_id}||{top_name}"


def normalize_judge_item(item: dict[str, Any]) -> dict[str, Any] | None:
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
        "ontology": "source_or_ontology_issue",
        "source": "source_or_ontology_issue",
    }
    label = aliases.get(label, label)
    if label not in JUDGE_LABELS:
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


def final_decision(p1: dict, p2: dict, p3: dict) -> dict[str, Any]:
    votes = [v for v in (p1, p2, p3) if v and v.get("label")]
    n = len(votes)
    if not votes:
        return {
            "label": "no_consensus",
            "certainty": "low",
            "confidence": 0.0,
            "agreement": "0/3",
            "vote_split_pattern": "missing",
            "uncertainty_tag": "api_missing",
        }
    labels = [v["label"] for v in votes]
    counts = Counter(labels)
    label, count = counts.most_common(1)[0]
    avg_conf = sum(float(v.get("confidence", 0)) for v in votes) / n
    if n >= 3:
        has_maj = count >= 2
        split = "3-0" if count == 3 else ("2-1" if count == 2 else "1-1-1")
    elif n == 2:
        has_maj = count == 2
        split = "2-0" if has_maj else "1-1"
    else:
        has_maj = False
        split = "1-0"
    if has_maj:
        certainty = "high" if (count == n and avg_conf >= 0.8) else "medium"
        uncertainty = "stable" if count == n else "majority_vote"
    else:
        label = "no_consensus"
        certainty = "low"
        uncertainty = "split_vote"
        split = "1-1-1" if n >= 3 else split
    return {
        "label": label,
        "certainty": certainty,
        "confidence": round(avg_conf, 4),
        "agreement": f"{count}/{n}",
        "vote_split_pattern": split,
        "uncertainty_tag": uncertainty,
    }


def call_judge_batch(
    prompt: str,
    items: list[dict[str, Any]],
    base_id: int,
    api_key: str,
) -> dict[str, Any]:
    id_map = {base_id + i: it for i, it in enumerate(items)}
    payload = [
        {
            "record_id": rid,
            "query": it["query"],
            "query_kind": it["query_kind"],
            "structure_name": it["structure_name"],
            "fullname": it["fullname"],
            "top1_name": it["top_name"],
            "top1_id": it["top_homba_id"],
            "system": it["system"],
        }
        for rid, it in id_map.items()
    ]
    body = {
        "model": "deepseek-v4-flash",
        "messages": [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": "Review these records.\nrecords="
                + json.dumps(payload, ensure_ascii=False),
            },
        ],
        "temperature": 0,
        "max_tokens": 8192,
        "thinking": {"type": "disabled"},
    }
    data = http_chat(url=DEEPSEEK_URL, api_key=api_key, body=body)
    msg = data["choices"][0]["message"]
    content = msg.get("content") or msg.get("reasoning_content") or ""
    obj = extract_json_obj(content)
    if not isinstance(obj.get("results"), list):
        raise ValueError("missing results")
    out: dict[str, dict[str, Any]] = {}
    for item in obj["results"]:
        norm = normalize_judge_item(item) if isinstance(item, dict) else None
        if not norm:
            continue
        it = id_map.get(norm["record_id"])
        if not it:
            continue
        key = judge_cache_key(
            it["system"], it["query"], it["top_homba_id"], it["top_name"]
        )
        out[key] = {
            "label": norm["label"],
            "certainty": norm["certainty"],
            "confidence": norm["confidence"],
            "reason": norm["reason"],
        }
    if len(out) != len(items):
        raise ValueError(f"judge incomplete got={len(out)} want={len(items)}")
    return {"results": out, "usage": data.get("usage", {})}


def stage_validate(args: argparse.Namespace) -> dict[str, Any]:
    mapping_path = RUNS_DIR / "mapping_results.json"
    if not mapping_path.exists():
        raise SystemExit("mapping_results.json missing; run --stage map first")
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    records = mapping["records"]
    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise SystemExit("DEEPSEEK_API_KEY not set")

    # Flatten judgeable items: one per (record, system) with a predicted name
    items: list[dict[str, Any]] = []
    for rec in records:
        for system in SYSTEMS:
            pred = (rec.get("systems") or {}).get(system) or {}
            name = (pred.get("name") or "").strip()
            hid = (pred.get("homba_id") or "").strip()
            if not name and not hid:
                continue
            items.append(
                {
                    "record_id": rec["id"],
                    "system": system,
                    "query": rec["structure_name"],
                    "query_kind": rec.get("query_kind") or "fullname",
                    "structure_name": rec["structure_name"],
                    "fullname": rec.get("fullname") or "",
                    "top_homba_id": hid,
                    "top_name": name or hid,
                    "difficulty": rec.get("difficulty") or "",
                    "gt_status": rec.get("gt_status") or "",
                    "expected_homba_id": rec.get("expected_homba_id") or "",
                    "expected_homba_name": rec.get("expected_homba_name") or "",
                }
            )

    cache = {} if args.revalidate else _load_json(JUDGE_CACHE)
    usage = UsageAccum()
    print(f"[validate] judgeable items={len(items)}", flush=True)

    for pass_name, model, prompt in JUDGE_PASSES:
        pending = [
            it
            for it in items
            if pass_name
            not in cache.get(
                judge_cache_key(
                    it["system"], it["query"], it["top_homba_id"], it["top_name"]
                ),
                {},
            )
        ]
        print(f"  {pass_name}: pending={len(pending)}", flush=True)
        if not pending:
            continue
        batches = [
            pending[i : i + args.judge_batch_size]
            for i in range(0, len(pending), args.judge_batch_size)
        ]

        def _one(bi: int, batch: list[dict[str, Any]]) -> dict[str, Any]:
            try:
                return {"ok": True, **call_judge_batch(prompt, batch, bi * 1000, api_key)}
            except Exception as exc:  # noqa: BLE001
                return {"ok": False, "error": str(exc)}

        finished = 0
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = {ex.submit(_one, i, b): b for i, b in enumerate(batches)}
            for fut in as_completed(futs):
                batch = futs[fut]
                res = fut.result()
                finished += 1
                if not res.get("ok"):
                    # retry smaller
                    for it in batch:
                        try:
                            r2 = call_judge_batch(prompt, [it], 0, api_key)
                            usage.add(model, r2.get("usage") or {})
                            for k, v in r2["results"].items():
                                cache.setdefault(k, {})[pass_name] = v
                        except Exception as exc:  # noqa: BLE001
                            usage.errors += 1
                            key = judge_cache_key(
                                it["system"],
                                it["query"],
                                it["top_homba_id"],
                                it["top_name"],
                            )
                            cache.setdefault(k := key, {})[pass_name] = {
                                "label": "ambiguous",
                                "certainty": "low",
                                "confidence": 0.0,
                                "reason": f"judge_error: {exc}"[:180],
                            }
                    continue
                usage.add(model, res.get("usage") or {})
                for k, v in res["results"].items():
                    cache.setdefault(k, {})[pass_name] = v
                if finished % 30 == 0 or finished == len(batches):
                    _save_json(JUDGE_CACHE, cache)
                    print(
                        f"    {pass_name}: {finished}/{len(batches)} "
                        f"cost=${usage.cost_usd:.4f}",
                        flush=True,
                    )
        _save_json(JUDGE_CACHE, cache)

    # Build validation rows
    out_rows: list[dict[str, Any]] = []
    for it in items:
        key = judge_cache_key(
            it["system"], it["query"], it["top_homba_id"], it["top_name"]
        )
        votes = cache.get(key, {})
        p1, p2, p3 = votes.get("pass1", {}), votes.get("pass2", {}), votes.get("pass3", {})
        final = final_decision(p1, p2, p3)
        # also attach systems without prediction as empty handled earlier
        pred_meta = {}
        # find original pred flags
        for rec in records:
            if rec["id"] == it["record_id"]:
                pred_meta = (rec.get("systems") or {}).get(it["system"]) or {}
                break
        out_rows.append(
            {
                "id": it["record_id"],
                "system": it["system"],
                "query": it["query"],
                "query_kind": it["query_kind"],
                "fullname": it["fullname"],
                "difficulty": it["difficulty"],
                "gt_status": it["gt_status"],
                "expected_homba_id": it["expected_homba_id"],
                "expected_homba_name": it["expected_homba_name"],
                "top_homba_id": it["top_homba_id"],
                "top_name": it["top_name"],
                "id_match": str(bool(pred_meta.get("id_match"))).lower(),
                "name_match": str(bool(pred_meta.get("name_match"))).lower(),
                "pass1_label": p1.get("label", ""),
                "pass1_reason": p1.get("reason", ""),
                "pass2_label": p2.get("label", ""),
                "pass2_reason": p2.get("reason", ""),
                "pass3_label": p3.get("label", ""),
                "pass3_reason": p3.get("reason", ""),
                "final_label": final["label"],
                "final_certainty": final["certainty"],
                "final_confidence": final["confidence"],
                "vote_agreement": final["agreement"],
                "vote_split_pattern": final["vote_split_pattern"],
                "uncertainty_tag": final["uncertainty_tag"],
            }
        )

    # Add empty predictions as source_or_ontology_issue
    present = {(r["id"], r["system"]) for r in out_rows}
    for rec in records:
        for system in SYSTEMS:
            if (rec["id"], system) in present:
                continue
            out_rows.append(
                {
                    "id": rec["id"],
                    "system": system,
                    "query": rec["structure_name"],
                    "query_kind": rec.get("query_kind") or "",
                    "fullname": rec.get("fullname") or "",
                    "difficulty": rec.get("difficulty") or "",
                    "gt_status": rec.get("gt_status") or "",
                    "expected_homba_id": rec.get("expected_homba_id") or "",
                    "expected_homba_name": rec.get("expected_homba_name") or "",
                    "top_homba_id": "",
                    "top_name": "",
                    "id_match": "false",
                    "name_match": "false",
                    "pass1_label": "",
                    "pass1_reason": "",
                    "pass2_label": "",
                    "pass2_reason": "",
                    "pass3_label": "",
                    "pass3_reason": "",
                    "final_label": "source_or_ontology_issue",
                    "final_certainty": "high",
                    "final_confidence": 1.0,
                    "vote_agreement": "0/0",
                    "vote_split_pattern": "no_match",
                    "uncertainty_tag": "no_prediction",
                }
            )

    out_rows.sort(key=lambda r: (r["id"], SYSTEMS.index(r["system"]) if r["system"] in SYSTEMS else 9))
    csv_path = RUNS_DIR / "validation_results.csv"
    with csv_path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out_rows[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(out_rows)

    # merge validation cost into costs.json
    costs = _load_json(RUNS_DIR / "costs.json")
    costs["validation"] = {
        "model": "deepseek-v4-flash",
        "passes": 3,
        **usage.as_dict(),
    }
    costs["grand_total_usd"] = round(
        float(costs.get("inference_total_usd") or 0) + usage.cost_usd, 6
    )
    _save_json(RUNS_DIR / "costs.json", costs)

    summary = build_compare_summary(out_rows, costs)
    _save_json(RUNS_DIR / "summary.json", summary)
    print(f"[validate] wrote {csv_path}", flush=True)
    print(json.dumps(summary["by_system"], ensure_ascii=False, indent=2), flush=True)
    return summary


def build_compare_summary(
    rows: list[dict[str, Any]], costs: dict[str, Any]
) -> dict[str, Any]:
    mapping_recs: list[dict[str, Any]] = []
    mapping_path = RUNS_DIR / "mapping_results.json"
    if mapping_path.exists():
        mapping_recs = json.loads(mapping_path.read_text(encoding="utf-8")).get(
            "records", []
        )

    by_system: dict[str, Any] = {}
    for system in SYSTEMS:
        sub = [r for r in rows if r["system"] == system]
        labels = Counter(r["final_label"] for r in sub)
        scored = [r for r in sub if r.get("gt_status") != "open"]
        n = len(sub)
        aligned = labels.get("aligned", 0)
        parent = labels.get("broader_parent", 0)

        scored_map = [
            r
            for r in mapping_recs
            if r.get("gt_status") != "open" and r.get("expected_homba_id")
        ]
        res_n = len(scored_map)
        res_match = sum(
            1
            for r in scored_map
            if ((r.get("systems") or {}).get(system) or {}).get("resolved_id_match")
        )
        hallu = sum(
            1
            for r in mapping_recs
            if ((r.get("systems") or {}).get(system) or {}).get("raw_id_hallucinated")
        )
        valid = sum(
            1
            for r in mapping_recs
            if ((r.get("systems") or {}).get(system) or {}).get("homba_id_exists")
        )
        raw_id_match = sum(
            1
            for r in scored_map
            if ((r.get("systems") or {}).get(system) or {}).get("id_match")
        )

        by_system[system] = {
            "n": n,
            "label_counts": dict(labels),
            "aligned_rate": round(aligned / n, 4) if n else 0.0,
            "aligned_or_parent_rate": round((aligned + parent) / n, 4) if n else 0.0,
            "id_match_rate_scored": (
                round(raw_id_match / res_n, 4)
                if res_n
                else (
                    round(
                        sum(1 for r in scored if r["id_match"] == "true") / len(scored),
                        4,
                    )
                    if scored
                    else None
                )
            ),
            "resolved_id_match_rate_scored": (
                round(res_match / res_n, 4) if res_n else None
            ),
            "name_match_rate_scored": (
                round(
                    sum(1 for r in scored if r["name_match"] == "true") / len(scored), 4
                )
                if scored
                else None
            ),
            "raw_id_valid_count": valid,
            "raw_id_hallucinated_count": hallu,
            "by_difficulty": {},
        }
        for diff in ("easy", "medium", "hard"):
            dsub = [r for r in sub if r["difficulty"] == diff]
            dn = len(dsub)
            dlab = Counter(r["final_label"] for r in dsub)
            by_system[system]["by_difficulty"][diff] = {
                "n": dn,
                "aligned_rate": round(dlab.get("aligned", 0) / dn, 4) if dn else 0.0,
                "aligned_or_parent_rate": (
                    round(
                        (dlab.get("aligned", 0) + dlab.get("broader_parent", 0)) / dn, 4
                    )
                    if dn
                    else 0.0
                ),
                "label_counts": dict(dlab),
            }
    return {
        "dataset": "rcs_ai_compare",
        "mode": "catalog_in_context",
        "n_queries": len({r["id"] for r in rows}),
        "judge": {
            "model": "deepseek-v4-flash",
            "passes": 3,
            "pro_used": False,
        },
        "by_system": by_system,
        "costs": {
            "inference": costs.get("inference"),
            "inference_total_usd": costs.get("inference_total_usd"),
            "validation": costs.get("validation"),
            "grand_total_usd": costs.get("grand_total_usd"),
        },
    }


def esc(v: object) -> str:
    return html.escape(str(v or ""))


def pct(n: float | int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "0%"


def stage_report(args: argparse.Namespace) -> Path:
    summary = json.loads((RUNS_DIR / "summary.json").read_text(encoding="utf-8"))
    costs = json.loads((RUNS_DIR / "costs.json").read_text(encoding="utf-8"))
    rows = list(
        csv.DictReader(
            (RUNS_DIR / "validation_results.csv").open(encoding="utf-8-sig")
        )
    )
    mapping = json.loads((RUNS_DIR / "mapping_results.json").read_text(encoding="utf-8"))
    records = {r["id"]: r for r in mapping["records"]}

    label_order = [
        "aligned",
        "broader_parent",
        "partial_or_narrower",
        "wrong",
        "ambiguous",
        "source_or_ontology_issue",
        "no_consensus",
    ]
    label_cls = {
        "aligned": "ok",
        "broader_parent": "parent",
        "partial_or_narrower": "warn",
        "wrong": "bad",
        "ambiguous": "unknown",
        "source_or_ontology_issue": "issue",
        "no_consensus": "unknown",
    }
    sys_labels = {
        "rcs": "RCS",
        "deepseek_v4_flash": "DeepSeek V4 Flash",
        "deepseek_v4_pro": "DeepSeek V4 Pro",
        "gpt56_luna": "GPT-5.6 Luna",
    }

    def bar(counts: dict[str, int], total: int) -> str:
        parts = []
        for k in label_order:
            n = counts.get(k, 0)
            if not n:
                continue
            w = 100 * n / total if total else 0
            parts.append(
                f'<div class="bar-seg {label_cls.get(k,"unknown")}" '
                f'style="width:{w:.2f}%" title="{esc(k)}: {n}"></div>'
            )
        return '<div class="bar">' + "".join(parts) + "</div>"

    # overview cards
    cards = []
    for sk in SYSTEMS:
        s = summary["by_system"][sk]
        inf = (costs.get("inference") or {}).get(sk) or {}
        cost_s = f"${float(inf.get('cost_usd') or 0):.4f}" if sk != "rcs" else "—"
        aligned_pct = f"{100 * s['aligned_rate']:.1f}%"
        parent_pct = f"{100 * s['aligned_or_parent_rate']:.1f}%"
        cards.append(
            "<div class='card'>"
            f"<div class='card-kicker'>{esc(sys_labels[sk])}</div>"
            f"<div class='card-metric'>{esc(aligned_pct)}</div>"
            f"<div class='muted'>aligned · or+parent {esc(parent_pct)}</div>"
            f"<div class='muted small'>inference cost {esc(cost_s)}</div>"
            f"{bar(s['label_counts'], s['n'])}"
            "</div>"
        )

    # cost table
    cost_rows = []
    for sk, cfg in AI_MODELS.items():
        u = (costs.get("inference") or {}).get(sk) or {}
        cost_rows.append(
            "<tr>"
            f"<td>{esc(cfg['label'])}</td>"
            f"<td class='num'>{u.get('calls',0)}</td>"
            f"<td class='num'>{u.get('prompt_tokens',0):,}</td>"
            f"<td class='num'>{u.get('cached_tokens',0):,}</td>"
            f"<td class='num'>{u.get('completion_tokens',0):,}</td>"
            f"<td class='num'>{u.get('reasoning_tokens',0):,}</td>"
            f"<td class='num'><strong>${float(u.get('cost_usd') or 0):.4f}</strong></td>"
            f"<td class='num'>{u.get('errors',0)}</td>"
            "</tr>"
        )
    val = costs.get("validation") or {}
    cost_rows.append(
        "<tr class='total'>"
        "<td>Validation (flash×3)</td>"
        f"<td class='num'>{val.get('calls',0)}</td>"
        f"<td class='num'>{val.get('prompt_tokens',0):,}</td>"
        f"<td class='num'>{val.get('cached_tokens',0):,}</td>"
        f"<td class='num'>{val.get('completion_tokens',0):,}</td>"
        f"<td class='num'>{val.get('reasoning_tokens',0):,}</td>"
        f"<td class='num'><strong>${float(val.get('cost_usd') or 0):.4f}</strong></td>"
        f"<td class='num'>{val.get('errors',0)}</td>"
        "</tr>"
    )

    # difficulty matrix
    diff_rows = []
    for diff in ("easy", "medium", "hard"):
        cells = [f"<td><strong>{esc(diff)}</strong></td>"]
        for sk in SYSTEMS:
            d = summary["by_system"][sk]["by_difficulty"][diff]
            cells.append(
                f"<td class='num'>{100*d['aligned_rate']:.0f}% "
                f"<span class='muted'>({d['n']})</span></td>"
            )
        diff_rows.append("<tr>" + "".join(cells) + "</tr>")

    # disagreement table: where systems diverge on final_label
    by_id: dict[str, dict[str, dict[str, str]]] = defaultdict(dict)
    for r in rows:
        by_id[r["id"]][r["system"]] = r

    disagree_html = []
    for rid, sysmap in by_id.items():
        labs = {sk: sysmap[sk]["final_label"] for sk in SYSTEMS if sk in sysmap}
        if len(set(labs.values())) <= 1:
            continue
        rec = records.get(rid, {})
        disagree_html.append(
            "<tr>"
            f"<td>{esc(rid)}</td>"
            f"<td>{esc(rec.get('structure_name'))}"
            f"<div class='muted small'>{esc(rec.get('difficulty'))} · "
            f"{esc(rec.get('gt_status'))}</div></td>"
            + "".join(
                f"<td><span class='pill {label_cls.get(labs.get(sk,''),'unknown')}'>"
                f"{esc(labs.get(sk,''))}</span>"
                f"<div class='muted small'>{esc((sysmap.get(sk) or {}).get('top_name',''))}</div></td>"
                for sk in SYSTEMS
            )
            + "</tr>"
        )
    # limit for readability
    disagree_html = disagree_html[:80]

    # full results accordion-ish table (compact)
    full_rows = []
    for rid in sorted(by_id):
        rec = records.get(rid, {})
        full_rows.append(
            "<tr>"
            f"<td>{esc(rid)}</td>"
            f"<td>{esc(rec.get('structure_name'))}"
            f"<div class='muted small'>{esc(rec.get('difficulty'))} / "
            f"{esc(rec.get('query_kind'))}</div></td>"
            f"<td class='muted small'>{esc(rec.get('expected_homba_id'))}<br>"
            f"{esc(rec.get('expected_homba_name'))}</td>"
            + "".join(
                (
                    lambda r: (
                        f"<td><span class='pill {label_cls.get(r.get('final_label',''),'unknown')}'>"
                        f"{esc(r.get('final_label'))}</span>"
                        f"<div class='muted small'>{esc(r.get('top_homba_id'))}</div>"
                        f"<div class='small'>{esc(r.get('top_name'))}</div></td>"
                    )
                )(by_id[rid].get(sk, {}))
                for sk in SYSTEMS
            )
            + "</tr>"
        )

    inf_total = float(costs.get("inference_total_usd") or 0)
    grand = float(costs.get("grand_total_usd") or (inf_total + float(val.get("cost_usd") or 0)))

    doc = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="utf-8"/>
<title>RCS vs 3-AI Compare (catalog-in-context) — rcs_ai_compare</title>
<style>
:root {{
  --bg:#f6f3ec; --card:#fffdf8; --ink:#1d1a16; --muted:#6e665c;
  --line:#e4ddd0; --ok:#2f6f4e; --parent:#2a5f8f; --warn:#9a6b12;
  --bad:#9b2c2c; --issue:#6b4f8a; --unknown:#666;
}}
* {{ box-sizing:border-box; }}
body {{
  margin:0; font-family:"Iowan Old Style","Palatino Linotype",Palatino,Georgia,serif;
  color:var(--ink); background:
    radial-gradient(1200px 500px at 10% -10%, #efe4cf 0%, transparent 55%),
    radial-gradient(900px 400px at 100% 0%, #dce8e2 0%, transparent 50%),
    var(--bg);
  line-height:1.45;
}}
.wrap {{ max-width:1280px; margin:0 auto; padding:28px 22px 64px; }}
h1 {{ font-size:1.85rem; margin:0 0 6px; letter-spacing:-0.02em; }}
h2 {{ font-size:1.2rem; margin:28px 0 10px; }}
.muted {{ color:var(--muted); }}
.small {{ font-size:0.82rem; }}
.grid {{ display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:12px; }}
@media (max-width:1100px) {{ .grid {{ grid-template-columns:repeat(2,minmax(0,1fr)); }} }}
.card {{
  background:var(--card); border:1px solid var(--line); border-radius:14px;
  padding:14px 14px 12px; box-shadow:0 1px 0 rgba(0,0,0,.03);
}}
.card-kicker {{ font-size:0.78rem; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }}
.card-metric {{ font-size:1.7rem; font-weight:700; margin:4px 0; }}
.bar {{ display:flex; height:10px; border-radius:99px; overflow:hidden; background:#efe9dc; margin-top:10px; }}
.bar-seg.ok {{ background:var(--ok); }}
.bar-seg.parent {{ background:var(--parent); }}
.bar-seg.warn {{ background:var(--warn); }}
.bar-seg.bad {{ background:var(--bad); }}
.bar-seg.issue {{ background:var(--issue); }}
.bar-seg.unknown {{ background:#a39a8c; }}
table {{ width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line); }}
th, td {{ padding:8px 9px; border-bottom:1px solid var(--line); text-align:left; vertical-align:top; font-size:0.86rem; }}
th {{ background:#f3ede2; font-weight:600; position:sticky; top:0; }}
td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
tr.total td {{ background:#f7f1e6; }}
.pill {{
  display:inline-block; padding:1px 7px; border-radius:999px; font-size:0.75rem;
  border:1px solid var(--line); background:#fff;
}}
.pill.ok {{ color:var(--ok); border-color:#b9d8c6; background:#eef7f1; }}
.pill.parent {{ color:var(--parent); border-color:#b9cee3; background:#eef4fa; }}
.pill.warn {{ color:var(--warn); border-color:#e2cfa0; background:#fbf5e6; }}
.pill.bad {{ color:var(--bad); border-color:#e2b6b6; background:#fbeaea; }}
.pill.issue {{ color:var(--issue); border-color:#d2c2e4; background:#f5effa; }}
.pill.unknown {{ color:#555; }}
.note {{
  background:var(--card); border:1px solid var(--line); border-radius:12px;
  padding:12px 14px; margin:12px 0 18px;
}}
.scroll {{ overflow:auto; max-height:620px; border:1px solid var(--line); border-radius:10px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>RCS vs 3-AI Compare (catalog-in-context)</h1>
  <p class="muted">Dataset <code>rcs_ai_compare.csv</code> · {summary['n_queries']} queries ·
  AI = Flash / Pro / Luna with <strong>full HOMBA catalog</strong> in prompt ·
  judge = deepseek-v4-flash × 3-pass majority ·
  inference total <strong>${inf_total:.4f}</strong> ·
  grand total <strong>${grand:.4f}</strong></p>

  <div class="note">
    目的は <strong>RCS の存在意義</strong>を確かめる比較（AI 運用前提ではない）。
    AI プロンプトには HOMBA 全件（id|acronym|name）を載せている。
    ハルシネーション（カタログ外 ID 等）は再ランせずそのまま計上する。
    <strong>Aligned</strong> = flash×3 の query↔名称一致。
    推論コストは 3AI mapping のみ（RCS=$0）。Validation は別計上。
  </div>

  <h2>Overview</h2>
  <div class="grid">{''.join(cards)}</div>

  <h2>Inference cost (4 AI)</h2>
  <table>
    <thead><tr>
      <th>System</th><th class="num">Calls</th><th class="num">Prompt tok</th>
      <th class="num">Cached</th><th class="num">Completion</th>
      <th class="num">Reasoning</th><th class="num">USD</th><th class="num">Errors</th>
    </tr></thead>
    <tbody>{''.join(cost_rows)}</tbody>
  </table>
  <p class="muted small">{esc(costs.get('pricing_note',''))}</p>

  <h2>Aligned rate by difficulty</h2>
  <table>
    <thead><tr><th>Difficulty</th>
    {''.join(f'<th class="num">{esc(sys_labels[s])}</th>' for s in SYSTEMS)}
    </tr></thead>
    <tbody>{''.join(diff_rows)}</tbody>
  </table>

  <h2>Ontology grounding vs name consistency</h2>
  <p class="muted small">
    Raw ID match = 予測 HOMBA ID が expected と一致。
    Resolved ID match = 予測名称を RCS で再解決した ID が expected と一致（AI の名称接地）。
    Hallucinated IDs = HOMBA に存在しない ID を返した件数。
  </p>
  <table>
    <thead><tr>
      <th>System</th>
      <th class="num">Raw ID match</th>
      <th class="num">Resolved ID match</th>
      <th class="num">Name≈expected</th>
      <th class="num">Valid raw IDs</th>
      <th class="num">Hallucinated IDs</th>
      <th class="num">Aligned</th>
      <th class="num">Aligned∪Parent</th>
    </tr></thead>
    <tbody>
    {''.join(
      (
        lambda s=summary['by_system'][sk]: (
          f"<tr><td>{esc(sys_labels[sk])}</td>"
          f"<td class='num'>{'—' if s.get('id_match_rate_scored') is None else f'{100*s['id_match_rate_scored']:.1f}%'}</td>"
          f"<td class='num'>{'—' if s.get('resolved_id_match_rate_scored') is None else f'{100*s['resolved_id_match_rate_scored']:.1f}%'}</td>"
          f"<td class='num'>{'—' if s.get('name_match_rate_scored') is None else f'{100*s['name_match_rate_scored']:.1f}%'}</td>"
          f"<td class='num'>{s.get('raw_id_valid_count', '—')}</td>"
          f"<td class='num'>{s.get('raw_id_hallucinated_count', '—')}</td>"
          f"<td class='num'>{100*s['aligned_rate']:.1f}%</td>"
          f"<td class='num'>{100*s['aligned_or_parent_rate']:.1f}%</td></tr>"
        )
      )()
      for sk in SYSTEMS
    )}
    </tbody>
  </table>

  <h2>Disagreements across systems (first 80)</h2>
  <div class="scroll"><table>
    <thead><tr><th>ID</th><th>Query</th>
    {''.join(f'<th>{esc(sys_labels[s])}</th>' for s in SYSTEMS)}
    </tr></thead>
    <tbody>{''.join(disagree_html) if disagree_html else '<tr><td colspan="7">none</td></tr>'}</tbody>
  </table></div>

  <h2>All results</h2>
  <div class="scroll"><table>
    <thead><tr><th>ID</th><th>Query</th><th>Expected</th>
    {''.join(f'<th>{esc(sys_labels[s])}</th>' for s in SYSTEMS)}
    </tr></thead>
    <tbody>{''.join(full_rows)}</tbody>
  </table></div>

  <h2>Raw summary</h2>
  <pre style="background:var(--card);border:1px solid var(--line);padding:12px;overflow:auto;font-size:0.78rem;">{esc(json.dumps(summary, ensure_ascii=False, indent=2))}</pre>
</div>
</body>
</html>
"""
    out = RUNS_DIR / "ai_compare_report.html"
    out.write_text(doc, encoding="utf-8")
    print(f"[report] wrote {out}", flush=True)
    return out


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    args = parse_args()

    if args.stage in {"map", "all"}:
        stage_map(args)
    if args.stage in {"validate", "all"}:
        stage_validate(args)
    if args.stage in {"report", "all"}:
        if not (RUNS_DIR / "summary.json").exists():
            stage_validate(args)
        stage_report(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
