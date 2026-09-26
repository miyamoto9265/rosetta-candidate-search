#!/usr/bin/env python3
"""Build rcs_ebl/ebl_generator_cache.pkl from EBL rcs_ready tables for Lambda deployment."""

from __future__ import annotations

import argparse
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs_ebl.ebl_cache import DEFAULT_CACHE_FILENAME, load_ebl_cache, save_ebl_cache  # noqa: E402
from rcs_ebl.ebl_candidate_generator import DEFAULT_RCS_READY, EblCandidateGenerator  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Build EblCandidateGenerator cache.")
    parser.add_argument("--rcs-ready-dir", type=Path, default=DEFAULT_RCS_READY)
    parser.add_argument("--output", type=Path, default=REPO_ROOT / "rcs_ebl" / DEFAULT_CACHE_FILENAME)
    args = parser.parse_args()

    print(f"Building EBL matcher from {args.rcs_ready_dir} ...")
    started = time.perf_counter()
    with tempfile.TemporaryDirectory() as tmp:
        generator = EblCandidateGenerator(rcs_ready_dir=args.rcs_ready_dir, cache_dir=tmp)
    save_ebl_cache(args.output, generator)
    size_mb = args.output.stat().st_size / (1024 * 1024)
    print(f"Wrote {args.output} ({size_mb:.1f} MB) in {time.perf_counter() - started:.2f}s")

    started = time.perf_counter()
    loaded = load_ebl_cache(args.output)
    load_seconds = time.perf_counter() - started
    sample = loaded.generate("DLPFC", top_k=1)
    if not sample:
        print("Verification failed: empty sample result", file=sys.stderr)
        return 1
    print(f"Verified load in {load_seconds:.3f}s; sample={sample[0]['bna_area_abbr']} score={sample[0]['score']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
