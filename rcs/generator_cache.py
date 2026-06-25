"""Pre-built index cache for RosettaCandidateGenerator (Lambda cold-start optimization)."""

from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from typing import Any

from rcs.rosetta_candidate_generator import ENGINE_VERSION, RosettaCandidateGenerator

CACHE_FORMAT_VERSION = 1
DEFAULT_CACHE_FILENAME = "generator_cache.pkl"

HOMBA_CSV = "HOMBA_v1_fixed.csv"
TOKEN_RULES_CSV = "homba_token_rules.csv"
ALIAS_RULES_CSV = "homba_alias_rules.csv"
ABBREV_RULES_CSV = "homba_abbrev_rules.csv"


class GeneratorCacheError(Exception):
    """Raised when a cache file cannot be loaded or validated."""


def default_csv_paths(rcs_dir: Path) -> dict[str, Path]:
    return {
        "homba": rcs_dir / HOMBA_CSV,
        "token_rules": rcs_dir / TOKEN_RULES_CSV,
        "alias_rules": rcs_dir / ALIAS_RULES_CSV,
        "abbrev_rules": rcs_dir / ABBREV_RULES_CSV,
    }


def default_cache_path(base_dir: Path) -> Path:
    return base_dir / "rcs" / DEFAULT_CACHE_FILENAME


def compute_data_fingerprint(paths: dict[str, Path]) -> str:
    digest = hashlib.sha256()
    for key in sorted(paths):
        path = paths[key]
        digest.update(key.encode("utf-8"))
        digest.update(path.name.encode("utf-8"))
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(65536), b""):
                digest.update(chunk)
    return digest.hexdigest()


def build_generator(paths: dict[str, Path]) -> RosettaCandidateGenerator:
    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        raise FileNotFoundError(f"Missing CSV files: {', '.join(missing)}")
    return RosettaCandidateGenerator(
        paths["homba"],
        token_rules_csv=paths["token_rules"],
        alias_rules_csv=paths["alias_rules"],
        abbrev_rules_csv=paths["abbrev_rules"],
    )


def _normalize_generator_for_cache(generator: RosettaCandidateGenerator) -> None:
    """Store paths as plain strings so pickles work across Windows and Linux."""
    generator.homba_csv_path = str(generator.homba_csv_path)


def _normalize_generator_after_load(generator: RosettaCandidateGenerator) -> None:
    generator.homba_csv_path = Path(str(generator.homba_csv_path))


def save_generator_cache(
    cache_path: Path,
    generator: RosettaCandidateGenerator,
    *,
    fingerprint: str,
    source_paths: dict[str, Path],
) -> None:
    payload: dict[str, Any] = {
        "cache_format": CACHE_FORMAT_VERSION,
        "engine_version": ENGINE_VERSION,
        "fingerprint": fingerprint,
        "source_files": {key: path.name for key, path in sorted(source_paths.items())},
        "generator": generator,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = cache_path.with_suffix(".pkl.tmp")
    _normalize_generator_for_cache(generator)
    try:
        with temp_path.open("wb") as handle:
            pickle.dump(payload, handle, protocol=pickle.HIGHEST_PROTOCOL)
    finally:
        _normalize_generator_after_load(generator)
    temp_path.replace(cache_path)


def load_generator_cache(cache_path: Path) -> RosettaCandidateGenerator:
    if not cache_path.is_file():
        raise GeneratorCacheError(f"Cache file not found: {cache_path}")

    with cache_path.open("rb") as handle:
        payload = pickle.load(handle)

    if not isinstance(payload, dict):
        raise GeneratorCacheError("Cache payload must be a dict")

    cache_format = payload.get("cache_format")
    if cache_format != CACHE_FORMAT_VERSION:
        raise GeneratorCacheError(
            f"Unsupported cache format {cache_format!r} (expected {CACHE_FORMAT_VERSION})"
        )

    engine_version = payload.get("engine_version")
    if engine_version != ENGINE_VERSION:
        raise GeneratorCacheError(
            f"Engine version mismatch: cache={engine_version!r}, runtime={ENGINE_VERSION!r}"
        )

    generator = payload.get("generator")
    if not isinstance(generator, RosettaCandidateGenerator):
        raise GeneratorCacheError("Cache payload does not contain a RosettaCandidateGenerator")

    _normalize_generator_after_load(generator)
    return generator


def build_and_save_cache(cache_path: Path, paths: dict[str, Path]) -> RosettaCandidateGenerator:
    fingerprint = compute_data_fingerprint(paths)
    generator = build_generator(paths)
    save_generator_cache(cache_path, generator, fingerprint=fingerprint, source_paths=paths)
    return generator
