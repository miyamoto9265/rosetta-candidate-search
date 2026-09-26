"""Pre-built cache for EblCandidateGenerator (Lambda cold-start optimization).

Building the lit_name matcher takes ~30 s, which exceeds the API Gateway limit,
so deployments bundle a pickle built by ``scripts/build_ebl_generator_cache.py``.
"""

from __future__ import annotations

import pickle
from pathlib import Path

from rcs.rosetta_candidate_generator import ENGINE_VERSION as RCS_ENGINE_VERSION
from rcs_ebl import ENGINE_VERSION
from rcs_ebl.ebl_candidate_generator import EblCandidateGenerator

CACHE_FORMAT_VERSION = 1
DEFAULT_CACHE_FILENAME = "ebl_generator_cache.pkl"


class EblCacheError(Exception):
    """Raised when a cache file cannot be loaded or validated."""


def _to_str_paths(generator: EblCandidateGenerator) -> None:
    generator.rcs_ready_dir = str(generator.rcs_ready_dir)  # type: ignore[assignment]
    generator._matcher.homba_csv_path = str(generator._matcher.homba_csv_path)  # type: ignore[assignment]


def _to_path_objects(generator: EblCandidateGenerator) -> None:
    generator.rcs_ready_dir = Path(str(generator.rcs_ready_dir))
    generator._matcher.homba_csv_path = Path(str(generator._matcher.homba_csv_path))


def save_ebl_cache(cache_path: Path, generator: EblCandidateGenerator) -> None:
    payload = {
        "cache_format": CACHE_FORMAT_VERSION,
        "rcs_ebl_version": ENGINE_VERSION,
        "rcs_version": RCS_ENGINE_VERSION,
        "generator": generator,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(".pkl.tmp")
    _to_str_paths(generator)
    try:
        with temp_path.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    finally:
        _to_path_objects(generator)
    temp_path.replace(cache_path)


def load_ebl_cache(cache_path: Path) -> EblCandidateGenerator:
    if not cache_path.is_file():
        raise EblCacheError(f"Cache file not found: {cache_path}")
    with cache_path.open("rb") as handle:
        payload = pickle.load(handle)
    if not isinstance(payload, dict) or payload.get("cache_format") != CACHE_FORMAT_VERSION:
        raise EblCacheError("Unsupported EBL cache format")
    if payload.get("rcs_ebl_version") != ENGINE_VERSION or payload.get("rcs_version") != RCS_ENGINE_VERSION:
        raise EblCacheError(
            "Engine version mismatch: "
            f"cache=({payload.get('rcs_ebl_version')!r}, {payload.get('rcs_version')!r}), "
            f"runtime=({ENGINE_VERSION!r}, {RCS_ENGINE_VERSION!r})"
        )
    generator = payload.get("generator")
    if not isinstance(generator, EblCandidateGenerator):
        raise EblCacheError("Cache payload does not contain an EblCandidateGenerator")
    _to_path_objects(generator)
    return generator
