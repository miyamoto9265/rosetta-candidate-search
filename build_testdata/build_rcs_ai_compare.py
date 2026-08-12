#!/usr/bin/env python3
"""Build RCS vs AI comparison bench (~100 queries, easy→hard).

Sources
-------
- rcs_core.csv                         — verified HOMBA expected
- rcs_challenge.csv                    — known hard / often open GT
- rcs_projection_corpus_curated_non_neocortex.csv
                                       — literature abbrevs + frequency

Task
----
Same as RCS: structure_name → expected HOMBA ID / name.

Difficulty
----------
easy   — unambiguous full names (basic anatomy)
medium — common abbrevs / synonyms / light compounds
hard   — ambiguous abbrevs, challenge issues, rare / edge forms

Usage (repo root or build_testdata):
    python build_testdata/build_rcs_ai_compare.py
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
CORE_CSV = ROOT / "rcs_core.csv"
CHALLENGE_CSV = ROOT / "rcs_challenge.csv"
CURATED_CSV = ROOT / "rcs_projection_corpus_curated_non_neocortex.csv"
OUTPUT_CSV = ROOT / "rcs_ai_compare.csv"

OUTPUT_FIELDS = (
    "id",
    "structure_name",
    "fullname",
    "expected_homba_id",
    "expected_homba_name",
    "difficulty",
    "query_kind",
    "source",
    "gt_status",
    "n_mentions",
    "notes",
)

# Explicit curated abbrevs (not relying on core name match alone for intent).
# Used when fullname maps cleanly onto a core-verified HOMBA row.
CURATED_MEDIUM_ABBREVS = (
    "BLA",
    "NAc",
    "CeA",
    "LHb",
    "DG",
    "LS",
    "ZI",
    "LGN",
    "CLA",
    "VPL",
    "MGB",
    "EC",
    "DR",
    "Cd",
    "DN",
    "VP",
    "STN",
    "GPe",
    "SNr",
    "BNST",
)

CURATED_HARD_ABBREVS = (
    # short / polysemous in neuroscience literature
    "SC",
    "IC",
    "MD",
    "VL",
    "LH",
    "MS",
    "PVN",
    "PVT",
    "RE",
    "Sub",
    "Gr",
    "LHA",
    "MDT",
    "NAcc",
    "NTS",
    "PAG",
)

# fullname variants seen in curated corpus → a core lookup key
FULLNAME_ALIASES: dict[str, str] = {
    "nucleus tractus solitarius": "nucleus of the solitary tract",
    "nucleus tractus solitarii": "nucleus of the solitary tract",
    "basolateral amygdala": "basolateral amygdala",
    "central amygdala": "central amygdala",
    "lateral hypothalamus": "lateral hypothalamic area",
    "mediodorsal thalamus": "mediodorsal nucleus of thalamus",
    "ventrolateral thalamus": "ventral lateral nucleus of thalamus",
    "paraventricular nucleus": "paraventricular nucleus of hypothalamus",
    "paraventricular thalamus": "paraventricular nucleus of thalamus",
    "reuniens nucleus": "nucleus reuniens",
    "dorsal raphe": "dorsal raphe nucleus",
    "lateral habenula": "lateral habenular nucleus",
    "lateral septum": "lateral septal nuclear complex",
    "medial septum": "medial septal nucleus",
    "periaqueductal gray": "periaqueductal gray",
    "ventral tegmental area": "ventral tegmental area",
}

# Near-duplicate surface forms: skip these structure_names from core picks
DROP_IF_OTHER_PRESENT: dict[str, str] = {
    "facial motor nucleus": "facial nucleus",
    "broca's area": "broca area",
    "amygdaloid complex": "amygdala",
}

# Manual expected for curated hard items absent from core (HOMBA lookup / literature sense)
CURATED_MANUAL_EXPECTED: dict[str, tuple[str, str]] = {
    "PVT": ("HOMBA:10457", "paraventricular nucleus of thalamus"),
    "RE": ("HOMBA:10403", "reuniens (medioventral) nucleus of thalamus"),
    "LH": ("HOMBA:10494", "lateral hypothalamic area, tuberal part"),
}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def _core_indexes(core: list[dict[str, str]]) -> tuple[dict[str, dict], dict[str, dict]]:
    by_name: dict[str, dict] = {}
    by_fullname: dict[str, dict] = {}
    for r in core:
        by_name[_norm(r["structure_name"])] = r
        by_fullname[_norm(r["expected_homba_name"])] = r
        # also index common alias-like structure names for fullname join
        by_fullname.setdefault(_norm(r["structure_name"]), r)
    return by_name, by_fullname


def _core_difficulty(notes: str) -> str:
    n = (notes or "").lower()
    if any(
        k in n
        for k in (
            "fiber_tract",
            "white_matter",
            "cytoarchitectonic",
            "brodmann",
            "eponym",
            "laterality",
            "collective",
            "parenthetical",
            "disambiguation",
            "ambiguous",
            "issue",
        )
    ):
        return "hard"
    if any(
        k in n
        for k in (
            "abbrev",
            "abbreviation",
            "synonym",
            "compound",
            "modifier",
            "functional",
            "spelling",
            "variant",
        )
    ):
        return "medium"
    return "easy"


def _is_abbrev_token(s: str) -> bool:
    t = s.strip()
    if not t:
        return False
    if t.isupper() and t.isalpha() and 1 <= len(t) <= 6:
        return True
    # mixed like dLGN, NAcc
    if 2 <= len(t) <= 6 and any(c.isupper() for c in t) and " " not in t:
        return True
    return False


def _query_kind(structure_name: str, notes: str, fullname: str) -> str:
    n = (notes or "").lower()
    sn = structure_name.strip()
    if "abbrev" in n or "abbreviation" in n or _is_abbrev_token(sn):
        return "abbrev"
    if any(k in n for k in ("collective", "ambiguous", "disambiguation", "issue")):
        return "ambiguous"
    if any(k in n for k in ("edge", "parenthetical", "plural", "spelling", "variant")):
        return "edge"
    if any(k in n for k in ("synonym", "eponym", "functional")):
        return "synonym"
    return "fullname"


def _pick_unique(
    rows: list[dict[str, str]],
    seen: set[str],
    limit: int,
) -> list[dict[str, str]]:
    out: list[dict[str, str]] = []
    for r in rows:
        key = _norm(r["structure_name"])
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
        if len(out) >= limit:
            break
    return out


def build() -> list[dict[str, str]]:
    core = _load_csv(CORE_CSV)
    challenge = _load_csv(CHALLENGE_CSV)
    curated = _load_csv(CURATED_CSV)
    by_name, by_fullname = _core_indexes(core)

    curated_by_sn: dict[str, dict] = {}
    for r in curated:
        curated_by_sn.setdefault(_norm(r["structure_name"]), r)

    def resolve_to_core(structure_name: str, fullname: str) -> tuple[dict | None, str]:
        """Return (core_row, gt_status_tag) or (None, '')."""
        sn_key = _norm(structure_name)
        if sn_key in by_name and by_name[sn_key].get("expected_homba_id"):
            return by_name[sn_key], "verified"
        fn_key = _norm(fullname)
        if not fn_key:
            return None, ""
        alias = FULLNAME_ALIASES.get(fn_key, fn_key)
        for key in (fn_key, _norm(alias)):
            if key in by_name and by_name[key].get("expected_homba_id"):
                return by_name[key], "verified_via_fullname"
            if key in by_fullname and by_fullname[key].get("expected_homba_id"):
                return by_fullname[key], "verified_via_fullname"
        return None, ""

    # --- core stratified picks (stable order = file order) ---
    core_easy = [r for r in core if _core_difficulty(r["notes"]) == "easy"]
    core_medium = [r for r in core if _core_difficulty(r["notes"]) == "medium"]
    core_hard = [r for r in core if _core_difficulty(r["notes"]) == "hard"]

    # Prefer non-abbrev full names for easy
    core_easy_pref = [
        r for r in core_easy if not _is_abbrev_token(r["structure_name"])
    ]
    # Prefer true abbrev / synonym for medium from core; fall back to rest
    core_medium_pref = [
        r
        for r in core_medium
        if _is_abbrev_token(r["structure_name"])
        or "abbrev" in (r["notes"] or "").lower()
        or "synonym" in (r["notes"] or "").lower()
    ]
    core_medium_rest = [r for r in core_medium if r not in core_medium_pref]

    # Skip near-duplicates from core picks
    skip_norms = set(DROP_IF_OTHER_PRESENT.keys())

    seen: set[str] = set()
    selected: list[dict[str, str]] = []

    def add_from_core(src_rows: list[dict], difficulty: str, limit: int) -> None:
        filtered = [
            r for r in src_rows if _norm(r["structure_name"]) not in skip_norms
        ]
        picked = _pick_unique(filtered, seen, limit)
        for r in picked:
            sn = r["structure_name"].strip()
            cur = curated_by_sn.get(_norm(sn), {})
            fullname = (cur.get("fullname") or "").strip()
            selected.append(
                {
                    "structure_name": sn,
                    "fullname": fullname,
                    "expected_homba_id": r["expected_homba_id"],
                    "expected_homba_name": r["expected_homba_name"],
                    "difficulty": difficulty,
                    "query_kind": _query_kind(sn, r["notes"], fullname),
                    "source": "rcs_core",
                    "gt_status": "verified",
                    "n_mentions": cur.get("n_mentions", ""),
                    "notes": r["notes"],
                }
            )

    # Targets: ~32 easy / ~38 medium / ~30 hard  → ~100
    add_from_core(core_easy_pref, "easy", 30)
    add_from_core(core_medium_pref, "medium", 14)
    if sum(1 for r in selected if r["difficulty"] == "medium") < 14:
        add_from_core(
            core_medium_rest,
            "medium",
            14 - sum(1 for r in selected if r["difficulty"] == "medium"),
        )
    add_from_core(core_hard, "hard", 5)

    # --- curated medium abbrevs with GT via structure_name/fullname→core ---
    for abbr in CURATED_MEDIUM_ABBREVS:
        if _norm(abbr) in seen:
            continue
        cur = curated_by_sn.get(_norm(abbr))
        if not cur:
            continue
        fn = (cur.get("fullname") or "").strip()
        gt, gt_status = resolve_to_core(cur["structure_name"], fn)
        if not gt or not gt.get("expected_homba_id"):
            continue
        seen.add(_norm(abbr))
        selected.append(
            {
                "structure_name": cur["structure_name"].strip(),
                "fullname": fn,
                "expected_homba_id": gt["expected_homba_id"],
                "expected_homba_name": gt["expected_homba_name"],
                "difficulty": "medium",
                "query_kind": "abbrev",
                "source": "curated_non_neocortex",
                "gt_status": gt_status,
                "n_mentions": cur.get("n_mentions", ""),
                "notes": f"corpus abbrev | {fn} | n_mentions={cur.get('n_mentions', '')}",
            }
        )

    # --- curated hard / ambiguous abbrevs ---
    for abbr in CURATED_HARD_ABBREVS:
        if _norm(abbr) in seen:
            continue
        cur = curated_by_sn.get(_norm(abbr))
        if not cur:
            continue
        sn = cur["structure_name"].strip()
        fn = (cur.get("fullname") or "").strip()
        gt, gt_status = resolve_to_core(sn, fn)
        eid, ename = "", ""
        if gt:
            eid, ename = gt["expected_homba_id"], gt["expected_homba_name"]
        elif sn in CURATED_MANUAL_EXPECTED:
            eid, ename = CURATED_MANUAL_EXPECTED[sn]
            gt_status = "provisional"
        else:
            gt_status = "open"
        seen.add(_norm(abbr))
        selected.append(
            {
                "structure_name": sn,
                "fullname": fn,
                "expected_homba_id": eid,
                "expected_homba_name": ename,
                "difficulty": "hard",
                "query_kind": "abbrev",
                "source": "curated_non_neocortex",
                "gt_status": gt_status or "open",
                "n_mentions": cur.get("n_mentions", ""),
                "notes": (
                    f"corpus hard abbrev | {fn} | ambiguous_or_short | "
                    f"n_mentions={cur.get('n_mentions', '')}"
                ),
            }
        )

    # --- challenge (hard, often open GT) ---
    for r in challenge:
        sn = r["structure_name"].strip()
        if _norm(sn) in seen:
            # already selected from core — upgrade difficulty/notes if needed
            continue
        seen.add(_norm(sn))
        cur = curated_by_sn.get(_norm(sn), {})
        selected.append(
            {
                "structure_name": sn,
                "fullname": (cur.get("fullname") or "").strip(),
                "expected_homba_id": r.get("expected_homba_id") or "",
                "expected_homba_name": r.get("expected_homba_name") or "",
                "difficulty": "hard",
                "query_kind": "ambiguous",
                "source": "rcs_challenge",
                "gt_status": "open" if not r.get("expected_homba_id") else "verified",
                "n_mentions": cur.get("n_mentions", ""),
                "notes": r.get("notes") or "",
            }
        )

    # Fill remaining medium slots with additional curated abbrevs (freq-ranked)
    need_medium = max(0, 38 - sum(1 for r in selected if r["difficulty"] == "medium"))
    if need_medium:
        candidates: list[tuple[int, dict, dict, str]] = []
        for r in curated:
            sn = r["structure_name"].strip()
            fn = (r.get("fullname") or "").strip()
            if _norm(sn) in seen:
                continue
            if not fn or _norm(sn) == _norm(fn):
                continue
            if not _is_abbrev_token(sn):
                continue
            gt, gt_status = resolve_to_core(sn, fn)
            if not gt or not gt.get("expected_homba_id"):
                continue
            candidates.append((int(r.get("n_mentions") or 0), r, gt, gt_status))
        candidates.sort(key=lambda x: (-x[0], x[1]["structure_name"]))
        for _, r, gt, gt_status in candidates[:need_medium]:
            sn = r["structure_name"].strip()
            fn = (r.get("fullname") or "").strip()
            seen.add(_norm(sn))
            selected.append(
                {
                    "structure_name": sn,
                    "fullname": fn,
                    "expected_homba_id": gt["expected_homba_id"],
                    "expected_homba_name": gt["expected_homba_name"],
                    "difficulty": "medium",
                    "query_kind": "abbrev",
                    "source": "curated_non_neocortex",
                    "gt_status": gt_status,
                    "n_mentions": r.get("n_mentions", ""),
                    "notes": f"corpus abbrev fill | {fn}",
                }
            )

    # Fill remaining easy with more core easy if short
    need_easy = max(0, 32 - sum(1 for r in selected if r["difficulty"] == "easy"))
    if need_easy:
        add_from_core(core_easy, "easy", need_easy)

    # Soft-cap hard: keep challenge + curated hard; trim excess core-hard first
    hard_rows = [r for r in selected if r["difficulty"] == "hard"]
    if len(hard_rows) > 30:
        keep_hard = [
            r
            for r in hard_rows
            if r["source"] in {"rcs_challenge", "curated_non_neocortex"}
        ]
        core_hard_kept = [
            r for r in hard_rows if r["source"] == "rcs_core"
        ][: max(0, 30 - len(keep_hard))]
        hard_keep_set = {id(r) for r in keep_hard + core_hard_kept}
        selected = [
            r
            for r in selected
            if r["difficulty"] != "hard" or id(r) in hard_keep_set
        ]

    # Stable sort: difficulty order, then source priority, then name
    diff_order = {"easy": 0, "medium": 1, "hard": 2}
    src_order = {
        "rcs_core": 0,
        "curated_non_neocortex": 1,
        "rcs_challenge": 2,
    }
    selected.sort(
        key=lambda r: (
            diff_order[r["difficulty"]],
            src_order.get(r["source"], 9),
            r["structure_name"].lower(),
        )
    )

    # Assign ids
    out: list[dict[str, str]] = []
    for i, r in enumerate(selected, start=1):
        row = {"id": f"AIC-{i:03d}", **r}
        out.append(row)
    return out


def main() -> None:
    rows = build()
    with OUTPUT_CSV.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        w.writeheader()
        w.writerows(rows)

    from collections import Counter

    by_d = Counter(r["difficulty"] for r in rows)
    by_s = Counter(r["source"] for r in rows)
    by_g = Counter(r["gt_status"] for r in rows)
    print(f"Wrote {len(rows)} rows → {OUTPUT_CSV}")
    print(f"  difficulty: {dict(by_d)}")
    print(f"  source:     {dict(by_s)}")
    print(f"  gt_status:  {dict(by_g)}")


if __name__ == "__main__":
    main()
