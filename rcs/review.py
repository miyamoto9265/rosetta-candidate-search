"""Review-flag helpers shared by the Lambda API and local evaluation tools."""

from __future__ import annotations


def review_flag_for(candidate: dict[str, object]) -> str:
    score = float(candidate["score"])
    modifier_terms = str(candidate.get("modifier_terms", ""))
    modifier_score = float(candidate.get("modifier_match_score", 1.0) or 1.0)
    if modifier_terms and modifier_score < 1.0:
        return "modifier_conflict"
    if score >= 0.90:
        return "high_confidence"
    if score < 0.60:
        return "low_confidence"
    return "needs_review"


def add_review_flags(candidates: list[dict[str, object]]) -> None:
    for candidate in candidates:
        candidate["review_flag"] = review_flag_for(candidate)
