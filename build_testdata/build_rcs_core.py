#!/usr/bin/env python3
"""Build Core dataset from LLM-based Recursive Improvement test inputs.

Merges Round CSVs under build_core_improve/input/ and enriches with expected HOMBA IDs.
"""

from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent
BUILD_CORE_IMPROVE = ROOT / "build_core_improve"
RCS_DIR = REPO_ROOT / "rcs"
INPUT_DIR = BUILD_CORE_IMPROVE / "input"
DEFAULT_HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
DEFAULT_ALIAS_RULES_CSV = RCS_DIR / "homba_alias_rules.csv"
DEFAULT_OUTPUT = ROOT / "rcs_core.csv"
DEFAULT_CHALLENGE_OUTPUT = ROOT / "rcs_challenge.csv"

SOURCE_FILES: tuple[tuple[str, Path], ...] = (
    ("level1", INPUT_DIR / "level1.csv"),
    ("round1", INPUT_DIR / "round1_comprehensive.csv"),
    ("round3", INPUT_DIR / "round3_edge_cases.csv"),
    ("round4", INPUT_DIR / "round4_large_scale.csv"),
)

CORE_OUTPUT_FIELDS = (
    "structure_name",
    "expected_homba_id",
    "expected_homba_name",
    "notes",
)

CHALLENGE_OUTPUT_FIELDS = (
    *CORE_OUTPUT_FIELDS,
    "由来",
)

CHALLENGE_ORIGIN_LRI_UNRESOLVED = (
    "LLM-based Recursive Improvement において Core へ収録できなかったレコード"
)

# round1 level1_issue entries: manually verified correct HOMBA IDs (ANALYSIS_REPORT_03 §3-2)
CURATED_EXPECTED_IDS: dict[str, str] = {
    "Vestibular nucleus": "HOMBA:12448",
    "Habenula": "HOMBA:10452",
    "Insula": "HOMBA:12176",
    "Cingulate gyrus": "HOMBA:10277",
    "Inferior olivary nucleus": "HOMBA:12600",
    "Pituitary gland": "HOMBA:10505",
    "Pulvinar nucleus": "HOMBA:10409",
    "Locus coeruleus": "HOMBA:12499",
}

# 期待値を定義できない、または RCS 現状出力を正解とできないクエリ
ISSUE_RECORDS: dict[str, str] = {
    "Brainstem": (
        "issue: 粒度・スコープの誤りにより、brainstem 全体を表す単一の HOMBA エントリが存在しない"
        "（ANALYSIS_REPORT_03 §5-1, §8 T-1）"
    ),
    "Limbic system": (
        "issue: 粒度・スコープの誤りにより、limbic system を表す単一の HOMBA エントリが存在しない"
        "（機能的概念）（ANALYSIS_REPORT_03 §5-2, §8 T-1）"
    ),
    "Inferior fronto-occipital fasciculus": (
        "issue: HOMBA に IFOF エントリがなく、vertical occipital fasciculus への誤マッチとなる"
        "（ANALYSIS_REPORT_03 §5-1）"
    ),
    "Septum": (
        "issue: テスト意図は septal area（中隔野）だが、RCS は septum pellucidum（透明中隔）にマッチする。"
        "Septal area/nuclei（HOMBA:10350）と別構造（ANALYSIS_REPORT_03 §5-1）"
    ),
    "Arcuate nucleus": (
        "issue: 視床下部と延髄に同名の弓状核が存在し、文脈なしでは正解を一意に定められない"
        "（ANALYSIS_REPORT_03 §5-1, §8 T-2）"
    ),
    "Paraventricular nucleus": (
        "issue: 視床下部 PVN と視床 PVN の曖昧性。PVN 略語行は視床下部だが、"
        "フル名は視床側にマッチする（ANALYSIS_REPORT_03 §8 T-2）"
    ),
    "Superior colliculus (deep layers)": (
        "issue: 括弧内の層指定が反映されず superior colliculus 全体にマッチする"
        "（deep gray layer が 2 位候補）"
    ),
    "Medial temporal lobe": (
        "issue: medial の修飾が落ち、temporal lobe 全体に汎化される"
    ),
    "Medial hypothalamus": (
        "issue: 修飾語が無視され、hypothalamus 全体に汎化される"
    ),
    "Thalamic nuclei": (
        "issue: 複数形の集合名詞が特定の視床核群 1 つ（ventral midline nuclei）にマップされる"
    ),
    "Motor cortex": (
        "issue: 汎用名称が frontal motor cortex（上位）にマップされる。"
        "文脈により primary motor cortex が望ましい場合あり（ANALYSIS_REPORT_03 §8 T-2）"
    ),
    "Lenticular nucleus": (
        "issue: 解剖学的には putamen + globus pallidus だが、"
        "HOMBA ギャップにより putamen のみで近似（homba_alias_rules.csv に明記）"
    ),
    "Insular cortex": (
        "issue: Insula（insular lobe, HOMBA:12176）と notes 上同義語だが expected が不一致"
    ),
}


@dataclass
class Entry:
    structure_name: str
    expected_homba_id: str = ""
    category: str = ""
    notes: str = ""

    def merge(self, *, expected_homba_id: str = "", category: str = "", notes: str = "") -> None:
        if expected_homba_id:
            self.expected_homba_id = expected_homba_id
        if category:
            if self.category and self.category != category:
                if category not in self.category.split("; "):
                    self.category = f"{self.category}; {category}"
            else:
                self.category = category
        if notes:
            if self.notes and notes not in self.notes.split(" | "):
                self.notes = f"{self.notes} | {notes}"
            elif not self.notes:
                self.notes = notes

    @property
    def merged_notes(self) -> str:
        parts: list[str] = []
        if self.category:
            for item in self.category.split("; "):
                item = item.strip()
                if item and item not in parts:
                    parts.append(item)
        if self.notes:
            for item in self.notes.split(" | "):
                item = item.strip()
                if item and item not in parts:
                    parts.append(item)
        return " | ".join(parts)


def append_note(base: str, addition: str) -> str:
    if not addition:
        return base
    if addition in base:
        return base
    return f"{base} | {addition}" if base else addition


def read_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        if not reader.fieldnames:
            raise ValueError(f"No header row: {path}")
        rows: list[dict[str, str]] = []
        for row in reader:
            name = (row.get("structure_name") or row.get(reader.fieldnames[0]) or "").strip()
            if not name:
                continue
            rows.append(
                {
                    "structure_name": name,
                    "expected_homba_id": (row.get("expected_homba_id") or "").strip(),
                    "category": (row.get("category") or "").strip(),
                    "notes": (row.get("notes") or "").strip(),
                }
            )
        return rows


def build_union() -> list[Entry]:
    entries: dict[str, Entry] = {}
    for _source, path in SOURCE_FILES:
        if not path.exists():
            raise FileNotFoundError(path)
        for row in read_rows(path):
            name = row["structure_name"]
            if name not in entries:
                entries[name] = Entry(structure_name=name)
            entries[name].merge(
                expected_homba_id=row["expected_homba_id"],
                category=row["category"],
                notes=row["notes"],
            )
    return sorted(entries.values(), key=lambda item: item.structure_name.casefold())


def load_homba_names(homba_csv: Path) -> dict[str, str]:
    names: dict[str, str] = {}
    with homba_csv.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            homba_id = (row.get("unified_ontology_id") or "").strip()
            name = (row.get("unified_ontology_name") or "").strip()
            if homba_id and name:
                names[homba_id] = name
    return names


def resolve_expected_ids(
    entries: list[Entry],
    homba_csv: Path,
    alias_rules_csv: Path,
) -> dict[str, tuple[str, str]]:
    sys.path.insert(0, str(RCS_DIR))
    from rosetta_candidate_generator import RosettaCandidateGenerator

    generator = RosettaCandidateGenerator(homba_csv, alias_rules_csv=alias_rules_csv)
    homba_names = load_homba_names(homba_csv)
    resolved: dict[str, tuple[str, str]] = {}

    for entry in entries:
        if entry.structure_name in ISSUE_RECORDS:
            resolved[entry.structure_name] = ("", "")
            continue

        homba_id = CURATED_EXPECTED_IDS.get(entry.structure_name) or entry.expected_homba_id
        homba_name = homba_names.get(homba_id, "") if homba_id else ""

        if not homba_id:
            candidates = generator.generate(entry.structure_name, top_k=1)
            if candidates:
                homba_id = str(candidates[0].get("homba_id") or "")
                homba_name = str(candidates[0].get("name") or "")
                if homba_id and not homba_name:
                    homba_name = homba_names.get(homba_id, "")

        if homba_id and not homba_name:
            homba_name = homba_names.get(homba_id, "")

        resolved[entry.structure_name] = (homba_id, homba_name)

    return resolved


def verify_containment(entries: list[Entry]) -> None:
    by_name = {entry.structure_name for entry in entries}
    for source, path in SOURCE_FILES:
        names = {row["structure_name"] for row in read_rows(path)}
        missing = names - by_name
        if missing:
            raise RuntimeError(f"{source} entries missing from union: {sorted(missing)}")
        print(f"  {source}: {len(names)} unique names (all contained)")


def write_csv(
    rows: list[dict[str, str]],
    output_path: Path,
    *,
    fieldnames: tuple[str, ...],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def split_and_write(
    entries: list[Entry],
    resolved: dict[str, tuple[str, str]],
    main_output: Path,
    issues_output: Path,
) -> None:
    main_rows: list[dict[str, str]] = []
    issue_rows: list[dict[str, str]] = []

    for entry in entries:
        homba_id, homba_name = resolved[entry.structure_name]
        row = {
            "structure_name": entry.structure_name,
            "expected_homba_id": homba_id,
            "expected_homba_name": homba_name,
            "notes": entry.merged_notes,
        }
        issue_reason = ISSUE_RECORDS.get(entry.structure_name)
        if issue_reason:
            row["expected_homba_id"] = ""
            row["expected_homba_name"] = ""
            row["notes"] = append_note(row["notes"], issue_reason)
            row["由来"] = CHALLENGE_ORIGIN_LRI_UNRESOLVED
            issue_rows.append(row)
        else:
            main_rows.append(row)

    write_csv(main_rows, main_output, fieldnames=CORE_OUTPUT_FIELDS)
    write_csv(issue_rows, issues_output, fieldnames=CHALLENGE_OUTPUT_FIELDS)


def main() -> None:
    entries = build_union()
    print("Verifying containment:")
    verify_containment(entries)

    print("Resolving expected HOMBA IDs via RCS + curated overrides...")
    resolved = resolve_expected_ids(entries, DEFAULT_HOMBA_CSV, DEFAULT_ALIAS_RULES_CSV)

    split_and_write(entries, resolved, DEFAULT_OUTPUT, DEFAULT_CHALLENGE_OUTPUT)

    main_count = len(entries) - len(ISSUE_RECORDS)
    issue_count = len(ISSUE_RECORDS)
    main_filled = sum(
        1
        for entry in entries
        if entry.structure_name not in ISSUE_RECORDS and resolved[entry.structure_name][0]
    )

    print(f"\nWrote {main_count} rows to {DEFAULT_OUTPUT}")
    print(f"  expected_homba_id filled: {main_filled}/{main_count}")
    print(f"Wrote {issue_count} rows to {DEFAULT_CHALLENGE_OUTPUT}")
    print(f"  expected_homba_id filled: 0/{issue_count}")


if __name__ == "__main__":
    main()
