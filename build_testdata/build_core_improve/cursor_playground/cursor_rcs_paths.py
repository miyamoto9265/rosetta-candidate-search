"""Shared paths to the RCS engine directory (repo root / rcs/)."""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
RCS_DIR = REPO_ROOT / "rcs"
HOMBA_CSV = RCS_DIR / "HOMBA_v1_fixed.csv"
ALIAS_RULES_CSV = RCS_DIR / "homba_alias_rules.csv"
TEST_OUTPUT_DIR = REPO_ROOT / "build_testdata" / "build_core_improve" / "output"
