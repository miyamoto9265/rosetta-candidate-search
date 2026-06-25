#!/usr/bin/env python3
"""Build rcs/generator_cache.pkl from CSV sources for Lambda deployment."""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.generator_cache import (  # noqa: E402
    build_and_save_cache,
    default_cache_path,
    default_csv_paths,
    load_generator_cache,
)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build RosettaCandidateGenerator index cache.")
    parser.add_argument(
        "--rcs-dir",
        type=Path,
        default=REPO_ROOT / "rcs",
        help="Directory containing HOMBA and rule CSV files",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Output pickle path (default: <rcs-dir>/generator_cache.pkl)",
    )
    args = parser.parse_args()

    rcs_dir = args.rcs_dir.resolve()
    output = (args.output or rcs_dir / "generator_cache.pkl").resolve()
    paths = default_csv_paths(rcs_dir)

    print(f"Building index from {rcs_dir} ...")
    started = time.perf_counter()
    build_and_save_cache(output, paths)
    build_seconds = time.perf_counter() - started

    size_mb = output.stat().st_size / (1024 * 1024)
    print(f"Wrote {output} ({size_mb:.1f} MB) in {build_seconds:.2f}s")

    started = time.perf_counter()
    generator = load_generator_cache(output)
    load_seconds = time.perf_counter() - started
    sample = generator.generate("Pulvinar nucleus", top_k=1)
    if not sample:
        print("Verification failed: empty sample result", file=sys.stderr)
        return 1

    print(
        f"Verified load in {load_seconds:.3f}s; "
        f"sample={sample[0]['homba_id']} score={sample[0]['score']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
