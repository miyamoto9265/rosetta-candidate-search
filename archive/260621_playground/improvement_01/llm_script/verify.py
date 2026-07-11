#!/usr/bin/env python3
"""Verify candidate alias targets against HOMBA.

Loads HOMBA once (fast) and, for each target string given on the command
line, reports whether it resolves to an exact HOMBA alias and prints nearby
matches by substring so we can confirm the *correct* HOMBA entry exists
before writing an alias rule.

Usage:
  python verify.py "median raphe nucleus" "transverse temporal gyrus"
  python verify.py --grep raphe          # list HOMBA names containing 'raphe'
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from rcs.rosetta_candidate_generator import (  # noqa: E402
    RosettaCandidateGenerator, normalize_text)

RCS_DIR = REPO_ROOT / "rcs"
gen = RosettaCandidateGenerator(RCS_DIR / "HOMBA_v1_fixed.csv")

# Map normalized name/acronym -> (homba_id, name) for exact-target checks.
name_index: dict[str, list[tuple[str, str]]] = {}
for t in gen.terms:
    for key in (t.name, t.acronym, t.dhba_name, t.dhba_acronym):
        nk = normalize_text(key)
        if nk:
            name_index.setdefault(nk, []).append((t.homba_id, t.name))


def grep(substr: str):
    s = substr.lower()
    hits = [(t.homba_id, t.name, t.acronym) for t in gen.terms
            if s in t.name.lower() or s in (t.acronym or "").lower()]
    print(f"# grep '{substr}': {len(hits)} hits")
    for hid, name, acr in hits[:60]:
        print(f"  {hid:14s} {name!r}  acr={acr!r}")


def check(target: str):
    nk = normalize_text(target)
    exact = name_index.get(nk)
    alias_hit = gen.alias_map.get(nk)
    print(f"\n== {target!r}  (norm={nk!r})")
    if exact:
        print(f"   EXACT name/acronym: {exact[:5]}")
    elif alias_hit:
        ids = {gen.terms[i].homba_id for i in alias_hit}
        names = {gen.terms[i].name for i in alias_hit}
        print(f"   ALIAS match -> ids={sorted(ids)[:5]} names={sorted(names)[:5]}")
    else:
        print("   NOT an exact alias. Nearest by token overlap:")
        toks = set(normalize_text(target).split())
        scored = []
        for t in gen.terms:
            nt = set(normalize_text(t.name).split())
            if toks & nt:
                scored.append((len(toks & nt) / max(len(toks | nt), 1), t.homba_id, t.name))
        scored.sort(reverse=True)
        for sc, hid, name in scored[:6]:
            print(f"     {sc:.2f} {hid:14s} {name!r}")


def main():
    args = sys.argv[1:]
    if args and args[0] == "--grep":
        grep(args[1])
        return
    for a in args:
        check(a)


if __name__ == "__main__":
    main()
