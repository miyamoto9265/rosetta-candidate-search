#!/usr/bin/env python3
"""Compare AI backends for the RCS preprocess / postprocess stages.

Two stages, measured separately so each model choice can be judged alone:

- pre:  query cleaning (ai_pipeline.PREPROCESS_SYSTEM) by DeepSeek v4-flash vs
        gpt-6-luna, then RCS top-1 against the verified expected HOMBA id.
        Runs on the clean queries and on "dirty" variants (laterality, gene,
        cell-type noise added) so cleaning actually matters.
- post: candidate adjudication on the same RCS top-10 by
        deepseek    DeepSeek v4-flash with ai_pipeline.POSTPROCESS_SYSTEM (prod)
        luna        gpt-6-luna Chat Completions with the same prompt
        decisions   OpenAI Decisions API (gpt-6-luna): one choice question for the
                    best candidate + one relation question per candidate

Ground truth: build_testdata/rcs_ai_compare.csv (verified expected_homba_id), the
abbreviation and the full name as separate queries. --dataset core uses
rcs_core.csv instead.

Every API response is cached under runs/<dataset>/cache.json, so reruns and new
arms only pay for what is missing. --mock answers without any API (offline check).

Keys come from DEEPSEEK_API_KEY / OPENAI_API_KEY; when unset, requests go out
without Authorization so a Claude Code cloud environment's network secrets for
api.deepseek.com / api.openai.com can add it.

Usage (repo root):
    export DEEPSEEK_API_KEY=... OPENAI_API_KEY=...
    python playgrounds/261010_decisions/decisions_harness.py --limit 10
    python playgrounds/261010_decisions/decisions_harness.py --workers 8
    python playgrounds/261010_decisions/decisions_harness.py --stage post --post decisions
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[1]
for p in (REPO_ROOT, REPO_ROOT / "web" / "backend"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import ai_pipeline  # noqa: E402
from rcs.generator_cache import build_generator, default_csv_paths  # noqa: E402

DATASETS = {
    "ai_compare": REPO_ROOT / "build_testdata" / "rcs_ai_compare.csv",
    "core": REPO_ROOT / "build_testdata" / "rcs_core.csv",
}

DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
OPENAI_CHAT_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_DECISIONS_URL = "https://api.openai.com/v1/decisions"
DEEPSEEK_MODEL = "deepseek-v4-flash"
LUNA_MODEL = "gpt-6-luna"

# USD per 1M tokens, 2026-10 list prices (cobrac-web packages/shared/src/pricing.ts,
# DeepSeek pricing page, OpenAI Decisions beta announcement). No peak surcharges.
PRICING = {
    DEEPSEEK_MODEL: {"input_miss": 0.14, "input_hit": 0.0028, "output": 0.28},
    LUNA_MODEL: {"input_miss": 0.10, "input_hit": 0.01, "output": 0.50},
    "decisions:" + LUNA_MODEL: {"input_miss": 0.10, "input_hit": 0.10, "output": 0.0},
}

# Noise added around clean queries for the preprocess stage. RCS strips some of
# this itself, so the "none" arm is the baseline to beat.
DIRTY_TEMPLATES = [
    "left {q}",
    "right {q} Drd1 neurons",
    "bilateral {q} SST interneurons",
    "contralateral {q} vGluT2-Cre cells",
    "{q} (excluding fibers of passage)",
]

PRE_ARMS = ("none", "deepseek", "luna")
POST_ARMS = ("deepseek", "luna", "decisions")


# --------------------------------------------------------------------------- data


def load_queries(dataset: str, limit: int | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    with DATASETS[dataset].open(encoding="utf-8-sig", newline="") as fh:
        for r in csv.DictReader(fh):
            exp = (r.get("expected_homba_id") or "").strip()
            if not exp:
                continue
            abbrev = (r.get("structure_name") or "").strip()
            full = (r.get("fullname") or "").strip()
            base = r.get("id") or f"{dataset}-{len(rows) + 1:03d}"
            if abbrev:
                rows.append({"qid": f"{base}:abbrev", "query": abbrev, "expected": exp})
            if full and full.casefold() != abbrev.casefold():
                rows.append({"qid": f"{base}:full", "query": full, "expected": exp})
    return rows[:limit] if limit else rows


def dirty_variant(item: dict[str, str], i: int) -> dict[str, str]:
    tpl = DIRTY_TEMPLATES[i % len(DIRTY_TEMPLATES)]
    return {**item, "qid": item["qid"] + ":dirty", "query": tpl.format(q=item["query"])}


# --------------------------------------------------------------------------- cache


class Cache:
    def __init__(self, path: Path):
        self.path = path
        self.lock = threading.Lock()
        self.data: dict[str, Any] = json.loads(path.read_text("utf-8")) if path.is_file() else {}

    def get_or_call(self, key: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        with self.lock:
            if key in self.data and not self.data[key].get("error"):
                return self.data[key]
        value = fn()
        with self.lock:
            self.data[key] = value
        return value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.lock:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(self.path)


# --------------------------------------------------------------------------- API calls


def _post_json(url: str, key: str, body: dict[str, Any], timeout: float = 30.0) -> tuple[dict[str, Any], float]:
    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    last = ""
    for attempt in range(1, 4):
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", **({"Authorization": f"Bearer {key}"} if key else {})},
            method="POST",
        )
        started = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            return payload, time.perf_counter() - started
        except urllib.error.HTTPError as exc:
            last = f"HTTP {exc.code}: {exc.read().decode('utf-8', errors='replace')[:300]}"
            if exc.code not in (429, 500, 502, 503):
                break
        except Exception as exc:  # noqa: BLE001
            last = str(exc)
        time.sleep(min(2**attempt, 8))
    raise RuntimeError(last)


def _env_key(name: str) -> str:
    """Key from the environment, or "" to send no Authorization header and let a
    cloud environment's network secret (agent proxy) add it."""
    return os.environ.get(name, "").strip()


def _usage(payload: dict[str, Any]) -> dict[str, int]:
    """Normalize DeepSeek / OpenAI usage to {input, cached, output}."""
    u = payload.get("usage") or {}
    inp = int(u.get("prompt_tokens") or u.get("input_tokens") or 0)
    cached = int(
        u.get("prompt_cache_hit_tokens")
        or (u.get("prompt_tokens_details") or {}).get("cached_tokens")
        or (u.get("input_tokens_details") or {}).get("cached_tokens")
        or 0
    )
    out = int(u.get("completion_tokens") or u.get("output_tokens") or 0)
    return {"input": inp, "cached": cached, "output": out}


def cost_usd(model: str, usage: dict[str, int]) -> float:
    price = PRICING[model]
    miss = max(usage["input"] - usage["cached"], 0)
    return (
        miss * price["input_miss"] + usage["cached"] * price["input_hit"] + usage["output"] * price["output"]
    ) / 1_000_000


def chat_json(provider: str, system: str, user: str, mock: bool) -> dict[str, Any]:
    """One JSON-mode chat call. Returns {obj, latency, usage, cost, error}."""
    model = DEEPSEEK_MODEL if provider == "deepseek" else LUNA_MODEL
    if mock:
        return {"obj": None, "latency": 0.0, "usage": {"input": 0, "cached": 0, "output": 0}, "cost": 0.0, "error": None, "mock": True}
    body: dict[str, Any] = {
        "model": model,
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "response_format": {"type": "json_object"},
    }
    if provider == "deepseek":
        body["temperature"] = 0.0
        body["thinking"] = {"type": "disabled"}
        url, key = DEEPSEEK_URL, _env_key("DEEPSEEK_API_KEY")
    else:
        body["reasoning_effort"] = "none"
        url, key = OPENAI_CHAT_URL, _env_key("OPENAI_API_KEY")
    try:
        payload, latency = _post_json(url, key, body)
        usage = _usage(payload)
        obj = ai_pipeline._extract_json_obj(payload["choices"][0]["message"]["content"])
        return {"obj": obj, "latency": latency, "usage": usage, "cost": cost_usd(model, usage), "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"obj": None, "latency": None, "usage": None, "cost": 0.0, "error": str(exc)[:300]}


# --------------------------------------------------------------------------- preprocess


def run_preprocess(arm: str, query: str, cache: Cache, mock: bool) -> dict[str, Any]:
    if arm == "none":
        return {"roi_query": query, "latency": 0.0, "cost": 0.0, "error": None}

    def call() -> dict[str, Any]:
        r = chat_json(arm, ai_pipeline.PREPROCESS_SYSTEM, f"query={query}", mock)
        roi = query
        if r["obj"]:
            roi = str(r["obj"].get("roi_query") or "").strip() or query
        return {"roi_query": roi, "latency": r["latency"], "usage": r["usage"], "cost": r["cost"], "error": r["error"]}

    return cache.get_or_call(f"pre|{arm}|{query}", call)


# --------------------------------------------------------------------------- postprocess


def postprocess_user_prompt(query: str, candidates: list[dict[str, Any]]) -> str:
    """Same input text the prod postprocess sends (preprocess skipped)."""
    hints = ai_pipeline.find_dict_hints(query)
    hint_ids = {h["homba_id"] for h in hints}
    lines = [f"raw_query={query}", "context=", f"roi_query={query}", "removed=[]"]
    if hints:
        lines.append("curated_dictionary_hints (authoritative):")
        for h in hints:
            lines.append(f"  \"{h['abbrev']}\" conventionally maps to {h['homba_id']} ({h['homba_name']})")
    lines.append("candidates:")
    for i, c in enumerate(candidates, 1):
        mark = "|CURATED" if str(c.get("homba_id") or "") in hint_ids else ""
        lines.append(f"  {i}. {c.get('homba_id')}|{c.get('acronym') or ''}|{c.get('name')}|score={c.get('score')}{mark}")
    return "\n".join(lines)


def _chat_results(obj: dict[str, Any] | None, candidates: list[dict[str, Any]]) -> list[dict[str, str]]:
    allowed = {str(c.get("homba_id")) for c in candidates}
    out: list[dict[str, str]] = []
    for it in (obj or {}).get("results") or []:
        if not isinstance(it, dict):
            continue
        hid = ai_pipeline._norm_homba_id(it.get("homba_id"))
        rel = ai_pipeline._norm_relation(it.get("relation"))
        if hid in allowed and rel and hid not in {r["homba_id"] for r in out}:
            out.append({"homba_id": hid, "relation": rel})
    return out[: ai_pipeline.MAX_AI_RESULTS]


DECISION_RELATIONS = [
    {"value": "=", "description": "Same structure, accepted synonym, or spelling/word-order variant."},
    {"value": "<", "description": "The query is smaller: the candidate is its broader parent/container."},
    {"value": ">", "description": "The query is larger: the candidate is only a part/subdivision of it."},
    {"value": "wrong", "description": "Anatomically a different structure; not acceptable."},
]


def decisions_body(query: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    """Decisions request: best-candidate choice + one relation choice per candidate.

    Field names follow the Decisions guide (model / input / questions with
    type, name, instructions, choices[value, description])."""
    state = (
        "Task: match a mammalian brain-region search query to HOMBA ontology candidates.\n"
        "Curated dictionary hints, when present, are authoritative for abbreviation senses.\n\n"
        + postprocess_user_prompt(query, candidates)
    )
    choices = [
        {"value": str(i), "description": f"{c.get('homba_id')} | {c.get('acronym') or ''} | {c.get('name')}"}
        for i, c in enumerate(candidates, 1)
    ]
    choices.append({"value": "none", "description": "No candidate is anatomically acceptable."})
    questions: list[dict[str, Any]] = [
        {
            "type": "choice",
            "name": "best",
            "instructions": "Which candidate best names the brain structure in the query? "
            "Prefer an exact synonym; else the closest acceptable parent; 'none' if all are wrong.",
            "choices": choices,
        }
    ]
    for i, c in enumerate(candidates, 1):
        questions.append(
            {
                "type": "choice",
                "name": f"rel_{i}",
                "instructions": f"How does the query relate to candidate {i} "
                f"({c.get('homba_id')} {c.get('name')})?",
                "choices": DECISION_RELATIONS,
            }
        )
    return {"model": LUNA_MODEL, "input": state, "questions": questions}


def _answer_map(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {str(a.get("name")): a for a in payload.get("answers") or [] if isinstance(a, dict)}


def decisions_results(payload: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[list[dict[str, str]], float | None]:
    """Map Decisions answers to prod-shaped results (best first, then other non-wrong)."""
    answers = _answer_map(payload)
    best = answers.get("best") or {}
    if best.get("type") == "refusal":
        raise RuntimeError("refusal")
    rel_of: dict[int, tuple[str, float]] = {}
    for i in range(1, len(candidates) + 1):
        a = answers.get(f"rel_{i}") or {}
        probs = {str(p.get("value")): float(p.get("probability") or 0) for p in a.get("probabilities") or []}
        ok = {k: v for k, v in probs.items() if k in ("=", "<", ">")}
        p_ok = sum(ok.values()) if probs else (0.0 if a.get("choice") == "wrong" else 1.0)
        rel = max(ok, key=ok.get) if ok else (a.get("choice") if a.get("choice") in ("=", "<", ">") else "=")
        rel_of[i] = (rel, p_ok)

    results: list[dict[str, str]] = []
    choice = str(best.get("choice") or "none")
    if choice.isdigit() and 1 <= int(choice) <= len(candidates):
        i = int(choice)
        rel = rel_of[i][0]
        results.append({"homba_id": str(candidates[i - 1]["homba_id"]), "relation": "'=" if rel == "=" else rel})
        others = sorted((j for j in rel_of if j != i and rel_of[j][1] >= 0.5), key=lambda j: -rel_of[j][1])
        for j in others[: ai_pipeline.MAX_AI_RESULTS - 1]:
            rel = rel_of[j][0]
            results.append({"homba_id": str(candidates[j - 1]["homba_id"]), "relation": "'=" if rel == "=" else rel})
    conf = best.get("confidence")
    return results, (float(conf) if conf is not None else None)


def _mock_decisions(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    answers = [{"type": "choice", "name": "best", "choice": "1", "confidence": 0.9}]
    for i in range(1, len(candidates) + 1):
        p = 0.9 if i == 1 else 0.1
        answers.append(
            {
                "type": "choice",
                "name": f"rel_{i}",
                "choice": "=" if i == 1 else "wrong",
                "probabilities": [{"value": "=", "probability": p}, {"value": "wrong", "probability": 1 - p}],
                "confidence": 0.8,
            }
        )
    return {"answers": answers, "usage": {"input_tokens": 0}}


def run_postprocess(arm: str, query: str, candidates: list[dict[str, Any]], cache: Cache, mock: bool) -> dict[str, Any]:
    if not candidates:
        return {"results": [], "latency": 0.0, "cost": 0.0, "error": None, "confidence": None}

    def call() -> dict[str, Any]:
        if arm in ("deepseek", "luna"):
            r = chat_json(arm, ai_pipeline.POSTPROCESS_SYSTEM, postprocess_user_prompt(query, candidates), mock)
            obj = r["obj"]
            if r.get("mock"):
                obj = {"results": [{"homba_id": candidates[0]["homba_id"], "relation": "'="}]}
            return {
                "results": _chat_results(obj, candidates),
                "latency": r["latency"],
                "usage": r["usage"],
                "cost": r["cost"],
                "error": r["error"],
                "confidence": None,
            }
        # decisions
        body = decisions_body(query, candidates)
        try:
            if mock:
                payload, latency = _mock_decisions(candidates), 0.0
            else:
                payload, latency = _post_json(OPENAI_DECISIONS_URL, _env_key("OPENAI_API_KEY"), body)
            usage = _usage(payload)
            estimated = False
            if not usage["input"]:
                # Usage shape is undocumented in the beta guide; fall back to ~4 chars/token.
                usage = {"input": len(json.dumps(body, ensure_ascii=False)) // 4, "cached": 0, "output": 0}
                estimated = True
            results, conf = decisions_results(payload, candidates)
            return {
                "results": results,
                "latency": latency,
                "usage": usage,
                "usage_estimated": estimated,
                "cost": cost_usd("decisions:" + LUNA_MODEL, usage),
                "error": None,
                "confidence": conf,
            }
        except Exception as exc:  # noqa: BLE001
            return {"results": [], "latency": None, "usage": None, "cost": 0.0, "error": str(exc)[:300], "confidence": None}

    return cache.get_or_call(f"post|{arm}|{query}|" + ",".join(str(c["homba_id"]) for c in candidates), call)


# --------------------------------------------------------------------------- summary


def _pct(values: list[float], q: float) -> float | None:
    if not values:
        return None
    values = sorted(values)
    return round(values[min(len(values) - 1, int(q * (len(values) - 1) + 0.5))], 3)


def _timing(rows: list[dict[str, Any]]) -> dict[str, Any]:
    lat = [r["latency"] for r in rows if r.get("latency") is not None]
    cost = sum(r.get("cost") or 0.0 for r in rows)
    n = len(rows)
    return {
        "latency_p50_s": _pct(lat, 0.5),
        "latency_p95_s": _pct(lat, 0.95),
        "cost_usd": round(cost, 6),
        "cost_per_1k_queries_usd": round(cost / n * 1000, 4) if n else None,
        "errors": sum(1 for r in rows if r.get("error")),
    }


def summarize_pre(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in sorted({r["arm"] for r in records}):
        for kind in ("clean", "dirty"):
            rows = [r for r in records if r["arm"] == arm and r["kind"] == kind]
            if not rows:
                continue
            out[f"{arm}/{kind}"] = {
                "n": len(rows),
                "rcs_top1_hit": round(sum(r["top1_hit"] for r in rows) / len(rows), 4),
                "rcs_top10_hit": round(sum(r["top10_hit"] for r in rows) / len(rows), 4),
                **_timing(rows),
            }
    return out


def summarize_post(records: list[dict[str, Any]]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for arm in sorted({r["arm"] for r in records}):
        rows = [r for r in records if r["arm"] == arm]
        reachable = [r for r in rows if r["expected_in_candidates"]]
        entry: dict[str, Any] = {
            "n": len(rows),
            "n_expected_in_top10": len(reachable),
            "rcs_top1_hit": round(sum(r["rcs_top1_hit"] for r in rows) / len(rows), 4),
            "ai_top1_hit": round(sum(r["ai_top1_hit"] for r in rows) / len(rows), 4),
            "ai_top1_hit_when_reachable": round(sum(r["ai_top1_hit"] for r in reachable) / len(reachable), 4) if reachable else None,
            "ai_any_hit": round(sum(r["ai_any_hit"] for r in rows) / len(rows), 4),
            "abstain_rate": round(sum(1 for r in rows if not r["results"]) / len(rows), 4),
            "top1_relation_eq_when_hit": round(
                sum(1 for r in rows if r["ai_top1_hit"] and r["results"][0]["relation"] == "'=")
                / max(1, sum(r["ai_top1_hit"] for r in rows)),
                4,
            ),
            **_timing(rows),
        }
        confs = [(r["confidence"], r["ai_top1_hit"]) for r in rows if r.get("confidence") is not None]
        if confs:
            # How much could be answered by Decisions alone with DeepSeek as fallback.
            entry["by_confidence"] = {
                str(t): {
                    "share": round(sum(1 for c, _ in confs if c >= t) / len(confs), 4),
                    "top1_hit": round(sum(h for c, h in confs if c >= t) / max(1, sum(1 for c, _ in confs if c >= t)), 4),
                }
                for t in (0.5, 0.7, 0.8, 0.9)
            }
        if any(r.get("usage_estimated") for r in rows):
            entry["cost_note"] = "token usage estimated (~4 chars/token)"
        out[arm] = entry
    return out


def write_markdown(path: Path, summary: dict[str, Any]) -> None:
    lines = [f"# Decisions / luna comparison ({summary['dataset']}, {summary['generated_at']})", ""]
    if summary.get("pre"):
        lines += [
            "## Preprocess -> RCS top-1",
            "",
            "| arm/queries | n | top-1 | top-10 | p50 s | p95 s | $/1k | errors |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for k, v in summary["pre"].items():
            lines.append(
                f"| {k} | {v['n']} | {v['rcs_top1_hit']:.1%} | {v['rcs_top10_hit']:.1%} | {v['latency_p50_s']} | "
                f"{v['latency_p95_s']} | {v['cost_per_1k_queries_usd']} | {v['errors']} |"
            )
        lines.append("")
    if summary.get("post"):
        lines += [
            "## Postprocess (same RCS top-10, no preprocess)",
            "",
            "| arm | n | RCS top-1 | AI top-1 | AI top-1 (reachable) | abstain | p50 s | p95 s | $/1k | errors |",
            "|---|---|---|---|---|---|---|---|---|---|",
        ]
        for k, v in summary["post"].items():
            reach = f"{v['ai_top1_hit_when_reachable']:.1%}" if v["ai_top1_hit_when_reachable"] is not None else "-"
            lines.append(
                f"| {k} | {v['n']} | {v['rcs_top1_hit']:.1%} | {v['ai_top1_hit']:.1%} | {reach} | {v['abstain_rate']:.1%} | "
                f"{v['latency_p50_s']} | {v['latency_p95_s']} | {v['cost_per_1k_queries_usd']} | {v['errors']} |"
            )
        dec = summary["post"].get("decisions", {}).get("by_confidence")
        if dec:
            lines += ["", "Decisions by confidence (share answered, top-1 among them):", ""]
            for t, v in dec.items():
                lines.append(f"- confidence >= {t}: {v['share']:.1%} answered, top-1 {v['top1_hit']:.1%}")
    path.write_text("\n".join(lines) + "\n", "utf-8")


# --------------------------------------------------------------------------- main


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", choices=sorted(DATASETS), default="ai_compare")
    ap.add_argument("--stage", choices=("all", "pre", "post"), default="all")
    ap.add_argument("--pre", nargs="+", choices=PRE_ARMS, default=list(PRE_ARMS))
    ap.add_argument("--post", nargs="+", choices=POST_ARMS, default=list(POST_ARMS))
    ap.add_argument("--limit", type=int, default=None, help="first N queries only")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--mock", action="store_true", help="no API calls; fake answers (offline check)")
    ap.add_argument("--out", type=Path, default=None, help="output dir (default runs/<dataset>[-mock])")
    args = ap.parse_args()

    out_dir = args.out or HERE / "runs" / (args.dataset + ("-mock" if args.mock else ""))
    out_dir.mkdir(parents=True, exist_ok=True)
    cache = Cache(out_dir / "cache.json")

    started = time.perf_counter()
    generator = build_generator(default_csv_paths(REPO_ROOT / "rcs"))
    print(f"RCS generator ready in {time.perf_counter() - started:.1f}s", flush=True)
    rcs_lock = threading.Lock()
    rcs_memo: dict[str, list[dict[str, Any]]] = {}

    def rcs_top10(q: str) -> list[dict[str, Any]]:
        with rcs_lock:  # generator is not documented as thread-safe
            if q not in rcs_memo:
                rcs_memo[q] = generator.generate(q, top_k=10)
            return rcs_memo[q]

    items = load_queries(args.dataset, args.limit)
    print(f"{len(items)} queries from {DATASETS[args.dataset].name}", flush=True)
    summary: dict[str, Any] = {"dataset": args.dataset, "generated_at": time.strftime("%Y-%m-%d %H:%M"), "mock": args.mock}

    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        if args.stage in ("all", "pre"):
            jobs = [(it, "clean") for it in items] + [(dirty_variant(it, i), "dirty") for i, it in enumerate(items)]

            def pre_one(job: tuple[dict[str, str], str], arm: str) -> dict[str, Any]:
                it, kind = job
                r = run_preprocess(arm, it["query"], cache, args.mock)
                cands = rcs_top10(r["roi_query"])
                ids = [str(c["homba_id"]) for c in cands]
                return {
                    "qid": it["qid"], "arm": arm, "kind": kind, "query": it["query"], "roi_query": r["roi_query"],
                    "expected": it["expected"], "top1_hit": bool(ids) and ids[0] == it["expected"],
                    "top10_hit": it["expected"] in ids, "latency": r.get("latency"), "cost": r.get("cost"), "error": r.get("error"),
                }

            pre_records = [rec for arm in args.pre for rec in pool.map(lambda j, a=arm: pre_one(j, a), jobs)]
            cache.save()
            (out_dir / "pre_records.json").write_text(json.dumps(pre_records, ensure_ascii=False, indent=1), "utf-8")
            summary["pre"] = summarize_pre(pre_records)

        if args.stage in ("all", "post"):
            cand_of = {it["qid"]: rcs_top10(it["query"]) for it in items}

            def post_one(it: dict[str, str], arm: str) -> dict[str, Any]:
                cands = cand_of[it["qid"]]
                ids = [str(c["homba_id"]) for c in cands]
                r = run_postprocess(arm, it["query"], cands, cache, args.mock)
                res = r["results"]
                return {
                    "qid": it["qid"], "arm": arm, "query": it["query"], "expected": it["expected"],
                    "expected_in_candidates": it["expected"] in ids,
                    "rcs_top1_hit": bool(ids) and ids[0] == it["expected"],
                    "ai_top1_hit": bool(res) and res[0]["homba_id"] == it["expected"],
                    "ai_any_hit": any(x["homba_id"] == it["expected"] for x in res),
                    "results": res, "confidence": r.get("confidence"), "latency": r.get("latency"),
                    "cost": r.get("cost"), "usage_estimated": r.get("usage_estimated", False), "error": r.get("error"),
                }

            post_records = [rec for arm in args.post for rec in pool.map(lambda it, a=arm: post_one(it, a), items)]
            cache.save()
            (out_dir / "post_records.json").write_text(json.dumps(post_records, ensure_ascii=False, indent=1), "utf-8")
            summary["post"] = summarize_post(post_records)

    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), "utf-8")
    write_markdown(out_dir / "summary.md", summary)
    print((out_dir / "summary.md").read_text("utf-8"))
    errors = [r for k in ("pre", "post") for r in (summary.get(k) or {}).values() if r.get("errors")]
    if errors:
        print("Some calls failed; see *_records.json 'error'. Rerun to retry only failed calls.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
