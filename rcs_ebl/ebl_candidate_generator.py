#!/usr/bin/env python3
"""EBL → BNA candidate generator for RCS_EBL (local test).

Reuses RosettaCandidateGenerator matching (normalize / variants / exact / fuzzy /
BM25 / alias / abbrev) against EBL ``lit_name`` vocabulary, then expands hits to
BNA region distributions from ``rcs_ready/bna_name_*.csv``.
"""

from __future__ import annotations

import csv
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.rosetta_candidate_generator import (  # noqa: E402
    RosettaCandidateGenerator,
    normalize_text,
)

DEFAULT_RCS_READY = REPO_ROOT / "ebl_for_rcs_v1.0_20260722" / "rcs_ready"
DEFAULT_TOKEN_RULES = REPO_ROOT / "rcs" / "homba_token_rules.csv"
DEFAULT_ALIAS_RULES = REPO_ROOT / "rcs" / "homba_alias_rules.csv"
DEFAULT_ABBREV_RULES = REPO_ROOT / "rcs" / "homba_abbrev_rules.csv"

_LEFT_WORDS = frozenset({"left", "l", "lh", "lt", "ipsilateral"})
_RIGHT_WORDS = frozenset({"right", "r", "rh", "rt", "contralateral"})
_BILAT_WORDS = frozenset({"bilateral", "both", "b", "bl", "bilat"})


def detect_laterality(query: str, laterality_words: set[str] | None = None) -> str:
    """Return 'left' | 'right' | 'bilateral' | 'unknown' from raw query tokens."""
    tokens = set(normalize_text(query).split())
    # Include EBL-proposed short forms even if not in RCS token rules yet.
    left = tokens & (_LEFT_WORDS | ({"left"} & (laterality_words or set())))
    right = tokens & (_RIGHT_WORDS | ({"right"} & (laterality_words or set())))
    bilat = tokens & _BILAT_WORDS
    if bilat and not left and not right:
        return "bilateral"
    if left and not right:
        return "left"
    if right and not left:
        return "right"
    return "unknown"


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def _write_synthetic_homba(index_rows: list[dict[str, str]], dest: Path) -> None:
    """Write lit_name rows in the minimal HOMBA CSV shape RCS expects."""
    fieldnames = [
        "unified_ontology_id",
        "unified_ontology_name",
        "unified_ontology_acronym",
        "DHBA_name",
        "DHBA_acronym",
        "parent_identifier",
        "graph_order",
        "parent",
    ]
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in index_rows:
            lit = (row.get("lit_name") or "").strip()
            if not lit:
                continue
            surface = (row.get("lit_surface_top") or lit).strip()
            writer.writerow(
                {
                    "unified_ontology_id": f"EBL:{lit}",
                    "unified_ontology_name": lit,
                    "unified_ontology_acronym": "",
                    "DHBA_name": surface,
                    "DHBA_acronym": "",
                    "parent_identifier": "",
                    "graph_order": "",
                    "parent": "",
                }
            )


class EblCandidateGenerator:
    """Match literature names with RCS algorithms, expand to BNA candidates."""

    def __init__(
        self,
        *,
        rcs_ready_dir: str | Path = DEFAULT_RCS_READY,
        token_rules_csv: str | Path = DEFAULT_TOKEN_RULES,
        alias_rules_csv: str | Path = DEFAULT_ALIAS_RULES,
        abbrev_rules_csv: str | Path = DEFAULT_ABBREV_RULES,
        cache_dir: str | Path | None = None,
    ):
        self.rcs_ready_dir = Path(rcs_ready_dir)
        index_path = self.rcs_ready_dir / "bna_name_index.csv"
        cand_path = self.rcs_ready_dir / "bna_name_candidates.csv"
        l2_path = self.rcs_ready_dir / "bna_name_l2_candidates.csv"
        for path in (index_path, cand_path, l2_path):
            if not path.is_file():
                raise FileNotFoundError(f"Missing RCS-ready EBL table: {path}")

        self.index_by_name: dict[str, dict[str, str]] = {
            row["lit_name"]: row for row in _read_csv(index_path)
        }
        self.candidates_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in _read_csv(cand_path):
            self.candidates_by_name[row["lit_name"]].append(row)
        for rows in self.candidates_by_name.values():
            rows.sort(key=lambda r: int(float(r.get("rank") or 999)))

        self.l2_by_name: dict[str, list[dict[str, str]]] = defaultdict(list)
        for row in _read_csv(l2_path):
            self.l2_by_name[row["lit_name"]].append(row)

        cache = Path(cache_dir) if cache_dir else Path(tempfile.gettempdir()) / "rcs_ebl"
        synthetic = cache / "ebl_lit_names_as_homba.csv"
        _write_synthetic_homba(list(self.index_by_name.values()), synthetic)

        self._matcher = RosettaCandidateGenerator(
            synthetic,
            token_rules_csv=token_rules_csv,
            alias_rules_csv=alias_rules_csv,
            abbrev_rules_csv=abbrev_rules_csv,
        )
        self.config = self._matcher.config

    def generate(
        self,
        query: str,
        *,
        top_k: int = 10,
        per_method_k: int = 40,
        name_top_k: int = 5,
        level: str = "l3",
    ) -> list[dict[str, object]]:
        """Return BNA candidates for *query*.

        Parameters
        ----------
        level:
            ``"l3"`` (default) — BNA fine regions from ``bna_name_candidates``.
            ``"l2"`` — gyrus-level from ``bna_name_l2_candidates``.
        """
        laterality = detect_laterality(query, self.config.laterality_words)
        # Match against lit_name vocabulary (laterality stripped inside RCS variants).
        name_hits = self._matcher.generate(
            query, top_k=max(name_top_k, 10), per_method_k=per_method_k, dhba_filter="both"
        )
        # Prefer exact lit_name hits so fuzzy near-misses do not flood BNA ranks.
        exact_hits = [
            hit
            for hit in name_hits
            if "exact" in str(hit.get("methods") or "") and float(hit.get("score") or 0) >= 0.95
        ]
        if exact_hits:
            # Prefer primary-name exact (lit_name == matched alias), not
            # parenthetical alias collisions like SMG surface "(TPJ)" → tpj.
            primary_exact = [
                hit
                for hit in exact_hits
                if normalize_text(str(hit.get("name") or ""))
                == normalize_text(str(hit.get("matched_alias") or hit.get("matched_query") or ""))
            ]
            name_hits = (primary_exact or exact_hits)[:name_top_k]
        else:
            name_hits = name_hits[:name_top_k]

        merged: dict[str, dict[str, object]] = {}
        for hit in name_hits:
            lit_name = str(hit.get("name") or "").strip()
            if not lit_name or lit_name not in self.index_by_name:
                # Defensive: matcher should return lit_name as name.
                lit_name = normalize_text(str(hit.get("homba_id", "")).removeprefix("EBL:"))
            if lit_name not in self.index_by_name:
                continue
            match_score = float(hit.get("score") or 0.0)
            methods = str(hit.get("methods") or "")
            matched_alias = str(hit.get("matched_alias") or "")
            matched_query = str(hit.get("matched_query") or "")
            index_row = self.index_by_name[lit_name]

            if level == "l2":
                dist_rows = self.l2_by_name.get(lit_name, [])
                for row in dist_rows:
                    key = f"l2:{row.get('bna_l2_abbr', '')}"
                    self._merge_l2(
                        merged,
                        key=key,
                        row=row,
                        index_row=index_row,
                        lit_name=lit_name,
                        match_score=match_score,
                        methods=methods,
                        matched_alias=matched_alias,
                        matched_query=matched_query,
                        laterality=laterality,
                    )
            else:
                dist_rows = self.candidates_by_name.get(lit_name, [])
                for row in dist_rows:
                    key = f"l3:{row.get('bna_l3_code') or row.get('bna_area_abbr', '')}"
                    self._merge_l3(
                        merged,
                        key=key,
                        row=row,
                        index_row=index_row,
                        lit_name=lit_name,
                        match_score=match_score,
                        methods=methods,
                        matched_alias=matched_alias,
                        matched_query=matched_query,
                        laterality=laterality,
                    )

        ranked = sorted(
            merged.values(),
            key=lambda item: (-float(item["score"]), str(item.get("bna_area_abbr") or item.get("bna_l2_abbr") or "")),
        )
        return ranked[: max(1, top_k)]

    @staticmethod
    def _resolve_label_id(laterality: str, id_l: str, id_r: str) -> str:
        if laterality == "left":
            return id_l
        if laterality == "right":
            return id_r
        return ""

    def _merge_l3(
        self,
        merged: dict[str, dict[str, object]],
        *,
        key: str,
        row: dict[str, str],
        index_row: dict[str, str],
        lit_name: str,
        match_score: float,
        methods: str,
        matched_alias: str,
        matched_query: str,
        laterality: str,
    ) -> None:
        p_raw = float(row.get("p_raw") or 0.0)
        score = match_score * p_raw
        id_l = (row.get("bna_label_id_l") or "").strip()
        id_r = (row.get("bna_label_id_r") or "").strip()
        candidate = {
            "bna_area_abbr": row.get("bna_area_abbr", ""),
            "bna_area_name": row.get("bna_area_name", ""),
            "bna_l2_abbr": row.get("bna_l2_abbr", ""),
            "bna_l3_code": row.get("bna_l3_code", ""),
            "bna_label_id_l": id_l,
            "bna_label_id_r": id_r,
            "bna_label_id": self._resolve_label_id(laterality, id_l, id_r),
            "laterality": laterality,
            "p_raw": p_raw,
            "p": float(row.get("p") or 0.0) if row.get("p") else None,
            "score": score,
            "match_score": match_score,
            "matched_lit_name": lit_name,
            "lit_surface_top": index_row.get("lit_surface_top", ""),
            "methods": methods,
            "matched_alias": matched_alias,
            "matched_query": matched_query,
            "k_papers": _to_int(index_row.get("k_papers") or row.get("k_papers")),
            "eff_n": _to_float(index_row.get("eff_n")),
            "n_papers": _to_int(row.get("n_papers")),
            "rank_in_name": _to_int(row.get("rank")),
            "level": "l3",
            # Frontend compatibility aliases (HOMBA-shaped columns)
            "homba_id": f"BNA:{row.get('bna_area_abbr', '')}",
            "name": row.get("bna_area_name") or row.get("bna_area_abbr", ""),
            "acronym": row.get("bna_area_abbr", ""),
            "dhba_name": row.get("bna_l2_abbr", ""),
            "dhba_acronym": row.get("bna_l3_code", ""),
        }
        prev = merged.get(key)
        if prev is None or float(candidate["score"]) > float(prev["score"]):
            merged[key] = candidate

    def _merge_l2(
        self,
        merged: dict[str, dict[str, object]],
        *,
        key: str,
        row: dict[str, str],
        index_row: dict[str, str],
        lit_name: str,
        match_score: float,
        methods: str,
        matched_alias: str,
        matched_query: str,
        laterality: str,
    ) -> None:
        p_raw = float(row.get("p_raw") or 0.0)
        score = match_score * p_raw
        candidate = {
            "bna_area_abbr": row.get("bna_l2_abbr", ""),
            "bna_area_name": row.get("bna_l2_name", ""),
            "bna_l2_abbr": row.get("bna_l2_abbr", ""),
            "bna_l2_name": row.get("bna_l2_name", ""),
            "bna_lobe": row.get("bna_lobe", ""),
            "bna_l3_code": "",
            "bna_label_id_l": "",
            "bna_label_id_r": "",
            "bna_label_id": "",
            "laterality": laterality,
            "p_raw": p_raw,
            "p": float(row.get("p") or 0.0) if row.get("p") else None,
            "score": score,
            "match_score": match_score,
            "matched_lit_name": lit_name,
            "lit_surface_top": index_row.get("lit_surface_top", ""),
            "methods": methods,
            "matched_alias": matched_alias,
            "matched_query": matched_query,
            "k_papers": _to_int(row.get("k_papers") or index_row.get("k_papers")),
            "eff_n": _to_float(row.get("eff_n") or index_row.get("eff_n")),
            "n_papers": _to_int(row.get("n_papers")),
            "rank_in_name": _to_int(row.get("rank")),
            "level": "l2",
            "homba_id": f"BNA-L2:{row.get('bna_l2_abbr', '')}",
            "name": row.get("bna_l2_name") or row.get("bna_l2_abbr", ""),
            "acronym": row.get("bna_l2_abbr", ""),
            "dhba_name": row.get("bna_lobe", ""),
            "dhba_acronym": "",
        }
        prev = merged.get(key)
        if prev is None or float(candidate["score"]) > float(prev["score"]):
            merged[key] = candidate


def _to_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def _to_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value))
    except ValueError:
        return None


def default_generator() -> EblCandidateGenerator:
    return EblCandidateGenerator()
