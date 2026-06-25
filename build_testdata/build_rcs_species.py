#!/usr/bin/env python3
"""Build Species dataset from paper seeds and official atlas label files."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SPECIES_SOURCES = ROOT / "species_sources"
ATLAS_LABELS = SPECIES_SOURCES / "atlas_labels"
SEED_CSV = SPECIES_SOURCES / "rcs_species_seed.csv"
DEFAULT_OUTPUT = ROOT / "rcs_species.csv"

WHS_LABEL = ATLAS_LABELS / "WHS_SD_rat_atlas_v4.label"
SARM_KEY_TABLE = ATLAS_LABELS / "SARM_key_table.csv"
MHOA2_PU_CSV = ATLAS_LABELS / "mHOA2_parcellation_units.csv"

OUTPUT_FIELDS = (
    "structure_name",
    "species",
    "source_atlas",
)

CLEAR_LABEL = "Clear Label"
SARM_CELL_RE = re.compile(r"^\d+:\s*(.+?)\s*\([^)]+\)\s*$")
WHS_LABEL_RE = re.compile(r'"([^"]+)"\s*$')


@dataclass
class SpeciesEntry:
    structure_name: str
    species: str
    source_atlas: str
    sources: set[str] = field(default_factory=set)
    from_seed: bool = False

    @property
    def key(self) -> tuple[str, str]:
        return (self.structure_name.casefold(), self.species)

    def merge(self, other: SpeciesEntry) -> None:
        if other.from_seed and not self.from_seed:
            self.structure_name = other.structure_name
            self.from_seed = True
        elif self.from_seed and not other.from_seed:
            pass
        elif len(other.structure_name) > len(self.structure_name):
            self.structure_name = other.structure_name

        self.sources.update(other.sources)
        if other.source_atlas and other.source_atlas not in self.source_atlas.split(" | "):
            self.source_atlas = (
                f"{self.source_atlas} | {other.source_atlas}"
                if self.source_atlas
                else other.source_atlas
            )


def humanize_sarm_token(token: str) -> str:
    words = token.replace("_", " ").split()
    small = {"of", "and", "the", "in", "to", "a", "for"}
    out: list[str] = []
    for index, word in enumerate(words):
        if index > 0 and word in small:
            out.append(word)
        else:
            out.append(word[:1].upper() + word[1:] if word else word)
    return " ".join(out)


def parse_sarm_cell(cell: str) -> str:
    cell = cell.strip()
    if not cell:
        return ""
    match = SARM_CELL_RE.match(cell)
    token = match.group(1) if match else cell
    return humanize_sarm_token(token)


def read_seed_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        rows: list[dict[str, str]] = []
        for row in reader:
            name = (row.get("structure_name") or "").strip()
            species = (row.get("species") or "").strip()
            if not name or species not in {"Macaque", "Rat"}:
                continue
            rows.append(
                {
                    "structure_name": name,
                    "species": species,
                    "source_atlas": (row.get("source_atlas") or row.get("paper") or "").strip(),
                }
            )
        return rows


def load_seed_entries() -> dict[tuple[str, str], SpeciesEntry]:
    if not SEED_CSV.exists():
        raise FileNotFoundError(SEED_CSV)

    entries: dict[tuple[str, str], SpeciesEntry] = {}
    for row in read_seed_rows(SEED_CSV):
        entry = SpeciesEntry(
            structure_name=row["structure_name"],
            species=row["species"],
            source_atlas=row["source_atlas"],
            from_seed=True,
        )
        entry.sources.add(row["source_atlas"])
        existing = entries.get(entry.key)
        if existing:
            existing.merge(entry)
        else:
            entries[entry.key] = entry
    return entries


def parse_whs_label(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)

    labels: list[str] = []
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = WHS_LABEL_RE.search(line)
        if not match:
            continue
        name = match.group(1).strip()
        if not name or name == CLEAR_LABEL:
            continue
        normalized = name[:1].upper() + name[1:] if name else name
        if normalized not in seen:
            seen.add(normalized)
            labels.append(normalized)
    return labels


def parse_mhoa2_pu(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)

    labels: list[str] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            name = (row.get("structure_name") or "").strip()
            if not name or name.casefold() in seen:
                continue
            seen.add(name.casefold())
            labels.append(name)
    return labels


def parse_sarm_level6(path: Path) -> list[str]:
    if not path.exists():
        raise FileNotFoundError(path)

    labels: list[str] = []
    seen: set[str] = set()
    with path.open(newline="", encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        level_col = "Level 6"
        if reader.fieldnames and level_col not in reader.fieldnames:
            level_col = reader.fieldnames[-1]
        for row in reader:
            name = parse_sarm_cell((row.get(level_col) or "").strip())
            if not name or name in seen:
                continue
            seen.add(name)
            labels.append(name)
    return labels


def add_atlas_entries(
    entries: dict[tuple[str, str], SpeciesEntry],
    *,
    labels: list[str],
    species: str,
    source_atlas: str,
) -> int:
    added = 0
    for label in labels:
        key = (label.casefold(), species)
        candidate = SpeciesEntry(
            structure_name=label,
            species=species,
            source_atlas=source_atlas,
        )
        candidate.sources.add(source_atlas)
        existing = entries.get(key)
        if existing:
            existing.merge(candidate)
        else:
            entries[key] = candidate
            added += 1
    return added


def write_csv(entries: list[SpeciesEntry], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "structure_name": entry.structure_name,
            "species": entry.species,
            "source_atlas": entry.source_atlas,
        }
        for entry in entries
    ]
    with output_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUTPUT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    entries = load_seed_entries()
    seed_count = len(entries)

    rat_labels = parse_whs_label(WHS_LABEL)
    sarm_labels = parse_sarm_level6(SARM_KEY_TABLE)
    mhoa2_labels = parse_mhoa2_pu(MHOA2_PU_CSV)

    rat_added = add_atlas_entries(
        entries,
        labels=rat_labels,
        species="Rat",
        source_atlas="WaxholmSpace_v4",
    )
    sarm_added = add_atlas_entries(
        entries,
        labels=sarm_labels,
        species="Macaque",
        source_atlas="SARM",
    )
    mhoa2_added = add_atlas_entries(
        entries,
        labels=mhoa2_labels,
        species="Macaque",
        source_atlas="mHOA2",
    )

    ordered = sorted(entries.values(), key=lambda item: (item.species, item.structure_name.casefold()))
    write_csv(ordered, DEFAULT_OUTPUT)

    macaque_count = sum(1 for entry in ordered if entry.species == "Macaque")
    rat_count = sum(1 for entry in ordered if entry.species == "Rat")

    print(f"Seed entries: {seed_count}")
    print(
        "Atlas additions:"
        f" Rat +{rat_added} (WHS={len(rat_labels)}),"
        f" Macaque +{sarm_added} (SARM L6={len(sarm_labels)}),"
        f" Macaque +{mhoa2_added} (mHOA2={len(mhoa2_labels)})"
    )
    print(f"Wrote {len(ordered)} rows to {DEFAULT_OUTPUT}")
    print(f"  Macaque: {macaque_count}, Rat: {rat_count}")


if __name__ == "__main__":
    main()
