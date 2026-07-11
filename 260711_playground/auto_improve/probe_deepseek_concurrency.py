#!/usr/bin/env python3
"""Quick DeepSeek concurrency probe (not an RCS improvement experiment).

Fires tiny chat-completion requests at increasing concurrency levels and
reports success rate / HTTP errors / wall time.  Stops early once error
rate climbs.

Usage:
    python probe_deepseek_concurrency.py
"""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-v4-flash"
# Ramp: few cheap probes first, then bigger jumps.
LEVELS = [8, 16, 24, 48, 96, 128, 192, 256]
REQUESTS_PER_LEVEL = 48  # fixed request count so levels are comparable


def one_call(api_key: str, i: int) -> dict:
    body = {
        "model": MODEL,
        "messages": [
            {"role": "user", "content": f"Reply with exactly: ok{i}"},
        ],
        "temperature": 0,
        "max_tokens": 8,
    }
    req = urllib.request.Request(
        API_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read()
            code = resp.status
        elapsed = time.perf_counter() - t0
        return {"ok": True, "code": code, "sec": elapsed}
    except urllib.error.HTTPError as exc:
        elapsed = time.perf_counter() - t0
        body_txt = exc.read().decode("utf-8", errors="replace")[:120]
        return {"ok": False, "code": exc.code, "sec": elapsed, "err": body_txt}
    except Exception as exc:
        elapsed = time.perf_counter() - t0
        return {"ok": False, "code": 0, "sec": elapsed, "err": str(exc)[:120]}


def run_level(api_key: str, workers: int, n: int) -> dict:
    t0 = time.perf_counter()
    results = []
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = [ex.submit(one_call, api_key, i) for i in range(n)]
        for fut in as_completed(futs):
            results.append(fut.result())
    wall = time.perf_counter() - t0
    ok = sum(1 for r in results if r["ok"])
    codes: dict[int, int] = {}
    for r in results:
        codes[r["code"]] = codes.get(r["code"], 0) + 1
    lat = sorted(r["sec"] for r in results if r["ok"])
    p50 = lat[len(lat) // 2] if lat else None
    p95 = lat[int(len(lat) * 0.95)] if lat else None
    return {
        "workers": workers,
        "n": n,
        "ok": ok,
        "fail": n - ok,
        "ok_rate": ok / n,
        "wall_sec": round(wall, 2),
        "rps": round(ok / wall, 2) if wall > 0 else 0,
        "p50_sec": round(p50, 2) if p50 is not None else None,
        "p95_sec": round(p95, 2) if p95 is not None else None,
        "http_codes": codes,
        "sample_err": next((r.get("err") for r in results if not r["ok"]), None),
    }


def main() -> int:
    api_key = os.environ.get("DEEPSEEK_API_KEY")
    if not api_key:
        print("DEEPSEEK_API_KEY not set")
        return 2

    print(f"model={MODEL}  requests/level={REQUESTS_PER_LEVEL}")
    print(f"{'workers':>8} {'ok':>5} {'fail':>5} {'ok%':>6} {'wall':>7} {'rps':>7} {'p50':>6} {'p95':>6}  codes")
    rows = []
    for w in LEVELS:
        row = run_level(api_key, w, REQUESTS_PER_LEVEL)
        rows.append(row)
        print(
            f"{row['workers']:8d} {row['ok']:5d} {row['fail']:5d} "
            f"{row['ok_rate']:6.1%} {row['wall_sec']:7.2f} {row['rps']:7.1f} "
            f"{str(row['p50_sec']):>6} {str(row['p95_sec']):>6}  {row['http_codes']}"
            + (f"  err={row['sample_err']!r}" if row["sample_err"] else "")
        )
        # Stop ramp if mostly failing — no point burning quota.
        if row["ok_rate"] < 0.5:
            print("stopping: ok_rate < 50%")
            break
        time.sleep(1.0)  # brief cool-down between levels

    out = Path(__file__).resolve().parent / "runs" / "concurrency_probe.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=2), encoding="utf-8")
    print(f"wrote {out}")

    best = max(rows, key=lambda r: (r["ok_rate"] > 0.95, r["rps"]))
    print(
        f"best usable: workers={best['workers']}  "
        f"ok={best['ok_rate']:.0%}  rps={best['rps']}  wall={best['wall_sec']}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
