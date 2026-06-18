"""AWS Lambda backend for ROSETTA Candidate Search.

Environment variables:
- HOMBA_BUCKET: S3 bucket that stores HOMBA_v1_fixed.csv, homba_token_rules.csv,
                homba_alias_rules.csv, and homba_abbrev_rules.csv
- HOMBA_KEY: S3 key for HOMBA_v1_fixed.csv
- TOKEN_RULES_KEY: S3 key for homba_token_rules.csv
- ALIAS_RULES_KEY: S3 key for homba_alias_rules.csv
- ABBREV_RULES_KEY: S3 key for homba_abbrev_rules.csv  (new in v0.3.0)
- ALLOWED_ORIGIN: CORS origin, e.g. https://example.com or *
"""

# VERSION: 0.3.0
# Versioning rule:
# - Behavior changes or scoring logic changes: increment PATCH (e.g. 0.1.0 -> 0.1.1)
# - Backward-compatible input/output field additions: increment MINOR (e.g. 0.1.0 -> 0.2.0)
# - Backward-incompatible API/input/output changes: increment MAJOR (e.g. 0.1.0 -> 1.0.0)
# Keep this version synchronized with rosetta_candidate_generator.py.

from __future__ import annotations

import csv
import json
import math
import os
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable

import boto3


HOMBA_ID_FIELD = "unified_ontology_id"
HOMBA_NAME_FIELD = "unified_ontology_name"
HOMBA_ACRONYM_FIELD = "unified_ontology_acronym"
DHBA_NAME_FIELD = "DHBA_name"
DHBA_ACRONYM_FIELD = "DHBA_acronym"
PARENT_ID_FIELD = "parent_identifier"

S3 = boto3.client("s3")
GENERATOR = None


@dataclass(frozen=True)
class LexiconConfig:
    stopwords: set[str]
    laterality_words: set[str]
    weak_terms: set[str]
    modifier_terms: set[str]


@dataclass(frozen=True)
class HOMBATerm:
    row_index: int
    homba_id: str
    name: str
    acronym: str = ""
    dhba_name: str = ""
    dhba_acronym: str = ""
    parent_id: str = ""
    graph_order: str = ""
    depth: int = 0
    aliases: tuple[str, ...] = field(default_factory=tuple)


@dataclass
class AliasEntry:
    term_index: int
    alias: str
    normalized: str
    tokens: tuple[str, ...]
    token_counts: Counter[str]


@dataclass(frozen=True)
class AliasRule:
    input_text: str
    homba_text: str
    notes: str = ""


@dataclass(frozen=True)
class AbbrevRule:
    """Query-only abbreviation expansion (never applied to HOMBA alias expansion)."""

    abbrev: str      # normalized abbreviation, e.g. "lc"
    expansion: str   # normalized expansion, e.g. "locus coeruleus"
    notes: str = ""


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = re.sub(r"['`´]", "", text)
    text = re.sub(r"[-_]+", " ", text)
    text = re.sub(r"[^0-9A-Za-z]+", " ", text)
    return re.sub(r"\s+", " ", text).strip().lower()


def unique_preserve_order(items: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        cleaned = (item or "").strip()
        key = normalize_text(cleaned)
        if cleaned and key and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def load_lexicon_config(path: Path) -> LexiconConfig:
    stopwords: set[str] = set()
    laterality_words: set[str] = set()
    weak_terms: set[str] = set()
    modifier_terms: set[str] = set()

    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            term = normalize_text(row.get("term", ""))
            kind = normalize_text(row.get("kind", ""))
            if not term:
                continue
            if kind == "stopword":
                stopwords.add(term)
            elif kind == "laterality":
                laterality_words.add(term)
            elif kind == "weak":
                weak_terms.add(term)
            elif kind == "modifier":
                modifier_terms.add(term)

    return LexiconConfig(
        stopwords=stopwords,
        laterality_words=laterality_words,
        weak_terms=weak_terms,
        modifier_terms=modifier_terms,
    )


def load_alias_rules(path: Path) -> list[AliasRule]:
    rules: list[AliasRule] = []
    if not path.exists():
        return rules

    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            input_text = normalize_text(row.get("input_text", ""))
            homba_text = normalize_text(row.get("homba_text", ""))
            if not input_text or not homba_text or input_text == homba_text:
                continue
            rules.append(
                AliasRule(
                    input_text=input_text,
                    homba_text=homba_text,
                    notes=(row.get("notes") or "").strip(),
                )
            )
    return rules


def load_abbrev_rules(path: Path) -> list[AbbrevRule]:
    """Load query-only abbreviation expansion rules.

    Unlike alias rules these are *never* applied to HOMBA alias expansion,
    which prevents short abbreviations from polluting the inverted index.
    """
    rules: list[AbbrevRule] = []
    if not path.exists():
        return rules
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            abbrev = normalize_text(row.get("abbrev", ""))
            expansion = normalize_text(row.get("expansion", ""))
            if not abbrev or not expansion or abbrev == expansion:
                continue
            rules.append(AbbrevRule(
                abbrev=abbrev,
                expansion=expansion,
                notes=(row.get("notes") or "").strip(),
            ))
    return rules


def apply_abbrev_rules(query: str, abbrev_rules: list[AbbrevRule]) -> list[str]:
    """Expand abbreviations in a query (query-side only).

    Strategy
    --------
    * Full-query match: works for any abbreviation length.
    * Word-boundary substitution within a longer query: only for abbreviations
      of 3+ characters to avoid false positives with 1-2 char tokens.
    """
    if not abbrev_rules:
        return [query]
    normalized = normalize_text(query)
    variants = [query]
    for rule in abbrev_rules:
        if normalized == rule.abbrev:
            variants.append(rule.expansion)
        elif len(rule.abbrev) >= 3:
            replaced = re.sub(
                rf"(?<![a-z0-9]){re.escape(rule.abbrev)}(?![a-z0-9])",
                rule.expansion,
                normalized,
            )
            if replaced != normalized:
                variants.append(replaced)
    return variants


def tokenize(text: str, config: LexiconConfig, keep_stopwords: bool = False) -> list[str]:
    tokens = normalize_text(text).split()
    if keep_stopwords:
        return tokens
    return [token for token in tokens if token not in config.stopwords]


def strip_parenthetical(text: str) -> str:
    return re.sub(r"\([^)]*\)", " ", text)


def strip_laterality(text: str, config: LexiconConfig) -> str:
    return " ".join(
        token for token in normalize_text(text).split() if token not in config.laterality_words
    )


def expand_with_alias_rules(text: str, alias_rules: list[AliasRule]) -> list[str]:
    normalized = normalize_text(text)
    variants = [text]
    if not normalized:
        return variants

    for rule in alias_rules:
        replacements = (
            (rule.input_text, rule.homba_text),
            (rule.homba_text, rule.input_text),
        )
        for source, target in replacements:
            if normalized == source:
                variants.append(target)
            replaced = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
            if replaced != normalized:
                variants.append(replaced)

    return unique_preserve_order(variants)


def expand_alias(alias: str, alias_rules: list[AliasRule] | None = None) -> list[str]:
    aliases = [alias, strip_parenthetical(alias)]
    alias_rules = alias_rules or []
    for group in re.findall(r"\(([^)]*)\)", alias):
        for part in re.split(r"[,;/]", group):
            aliases.append(part)
            base = normalize_text(strip_parenthetical(alias))
            suffix = normalize_text(part)
            if suffix and not suffix.isdigit():
                aliases.append(f"{base} {suffix}")
    if "," in alias:
        left, right = [part.strip() for part in alias.split(",", 1)]
        if left and right:
            aliases.append(f"{right} {left}")

    expanded: list[str] = []
    for item in aliases:
        expanded.extend(expand_with_alias_rules(item, alias_rules))

    return unique_preserve_order(expanded)


def query_variants(
    query: str,
    config: LexiconConfig,
    alias_rules: list[AliasRule] | None = None,
    abbrev_rules: list[AbbrevRule] | None = None,
) -> list[str]:
    alias_rules = alias_rules or []
    abbrev_rules = abbrev_rules or []
    variants = [query, strip_laterality(query, config), strip_parenthetical(query)]
    variants.append(re.sub(r"\b(excluding|except|without)\b.*$", " ", strip_parenthetical(query), flags=re.I))
    expanded: list[str] = []
    for variant in variants:
        expanded.extend(expand_with_alias_rules(variant, alias_rules))
    # Apply abbreviation expansion last (query-only; not used for HOMBA alias expansion).
    abbrev_expanded: list[str] = []
    for variant in expanded:
        abbrev_expanded.extend(apply_abbrev_rules(variant, abbrev_rules))
    return unique_preserve_order(abbrev_expanded)


def extract_modifier_terms(query: str, config: LexiconConfig) -> list[str]:
    terms: list[str] = []
    for group in re.findall(r"\(([^)]*)\)", query):
        group_tokens = tokenize(group, config)
        terms.extend(group_tokens)
        normalized_group = normalize_text(group)
        if normalized_group and len(group_tokens) > 1:
            terms.append(normalized_group)
    for token in tokenize(query, config):
        if token in config.modifier_terms:
            terms.append(token)
    return unique_preserve_order(terms)


def modifier_match_score(modifier_terms: list[str], aliases: Iterable[str]) -> float:
    if not modifier_terms:
        return 1.0
    alias_text = " ".join(normalize_text(alias) for alias in aliases)
    matched = sum(1 for term in modifier_terms if normalize_text(term) in alias_text)
    return matched / len(modifier_terms)


def char_ngrams(text: str, n: int) -> set[str]:
    compact = normalize_text(text).replace(" ", "")
    if len(compact) <= n:
        return {compact} if compact else set()
    return {compact[i : i + n] for i in range(len(compact) - n + 1)}


def dice_coefficient(left: set[str], right: set[str]) -> float:
    if not left or not right:
        return 0.0
    return 2.0 * len(left & right) / (len(left) + len(right))


def token_jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    left_set = set(left)
    right_set = set(right)
    if not left_set or not right_set:
        return 0.0
    return len(left_set & right_set) / len(left_set | right_set)


def string_similarity(query: str, alias: str, config: LexiconConfig) -> float:
    q_norm = normalize_text(query)
    a_norm = normalize_text(alias)
    if not q_norm or not a_norm:
        return 0.0
    if q_norm == a_norm:
        return 1.0

    sequence = SequenceMatcher(None, q_norm, a_norm).ratio()
    bigram = dice_coefficient(char_ngrams(q_norm, 2), char_ngrams(a_norm, 2))
    trigram = dice_coefficient(char_ngrams(q_norm, 3), char_ngrams(a_norm, 3))
    tokens = token_jaccard(tokenize(q_norm, config), tokenize(a_norm, config))

    containment = 0.0
    if len(q_norm) >= 4 and q_norm in a_norm:
        containment = min(0.92, len(q_norm) / max(len(a_norm), 1) + 0.25)
    if len(a_norm) >= 4 and a_norm in q_norm:
        containment = max(containment, min(0.92, len(a_norm) / max(len(q_norm), 1) + 0.25))

    return max(containment, 0.35 * sequence + 0.25 * bigram + 0.2 * trigram + 0.2 * tokens)


def specificity_terms(text: str, config: LexiconConfig) -> set[str]:
    return {
        token
        for token in tokenize(text, config, keep_stopwords=True)
        if token in config.modifier_terms or token in config.weak_terms
    }


class RosettaCandidateGenerator:
    def __init__(self, homba_csv_path: Path, token_rules_path: Path, alias_rules_path: Path, abbrev_rules_path: Path | None = None):
        self.config = load_lexicon_config(token_rules_path)
        self.alias_rules = load_alias_rules(alias_rules_path)
        self.abbrev_rules = load_abbrev_rules(abbrev_rules_path) if abbrev_rules_path else []
        self.terms: list[HOMBATerm] = []
        self.term_index_by_id: dict[str, int] = {}
        self.alias_entries: list[AliasEntry] = []
        self.alias_map: dict[str, set[int]] = defaultdict(set)
        self.token_to_entries: dict[str, set[int]] = defaultdict(set)
        self._bm25_doc_freq: Counter[str] = Counter()
        self._bm25_avg_len = 0.0
        self._load_homba_csv(homba_csv_path)
        self._build_indexes()

    def _load_homba_csv(self, homba_csv_path: Path) -> None:
        with homba_csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            hierarchy_fields = [
                field
                for field in (reader.fieldnames or [])
                if field.startswith("hierarchy") or field.startswith("Unnamed:")
            ]
            for row_index, row in enumerate(reader):
                name = (row.get(HOMBA_NAME_FIELD) or "").strip()
                if not name:
                    continue
                raw_aliases = [
                    row.get(HOMBA_NAME_FIELD, ""),
                    row.get(HOMBA_ACRONYM_FIELD, ""),
                    row.get(DHBA_NAME_FIELD, ""),
                    row.get(DHBA_ACRONYM_FIELD, ""),
                ]
                raw_aliases.extend(row.get(field, "") for field in hierarchy_fields)

                expanded_aliases: list[str] = []
                for alias in raw_aliases:
                    expanded_aliases.extend(expand_alias(alias, self.alias_rules))

                term = HOMBATerm(
                    row_index=row_index,
                    homba_id=(row.get(HOMBA_ID_FIELD) or "").strip(),
                    name=name,
                    acronym=(row.get(HOMBA_ACRONYM_FIELD) or "").strip(),
                    dhba_name=(row.get(DHBA_NAME_FIELD) or "").strip(),
                    dhba_acronym=(row.get(DHBA_ACRONYM_FIELD) or "").strip(),
                    parent_id=(row.get(PARENT_ID_FIELD) or "").strip(),
                    graph_order=(row.get("graph_order") or "").strip(),
                    depth=self._infer_depth(row, hierarchy_fields),
                    aliases=tuple(unique_preserve_order(expanded_aliases)),
                )
                self.term_index_by_id[term.homba_id] = len(self.terms)
                self.terms.append(term)

    @staticmethod
    def _infer_depth(row: dict[str, str], hierarchy_fields: list[str]) -> int:
        parent = (row.get("parent") or "").strip()
        if parent.isdigit():
            return int(parent) + 1
        positions = [index for index, field in enumerate(hierarchy_fields) if (row.get(field) or "").strip()]
        return max(positions) if positions else 0

    def _build_indexes(self) -> None:
        total_tokens = 0
        for term_index, term in enumerate(self.terms):
            for alias in term.aliases:
                normalized = normalize_text(alias)
                if not normalized:
                    continue
                tokens = tuple(tokenize(normalized, self.config))
                entry = AliasEntry(term_index, alias, normalized, tokens, Counter(tokens))
                self.alias_entries.append(entry)
                entry_index = len(self.alias_entries) - 1
                self.alias_map[normalized].add(term_index)
                for token in set(tokens):
                    self._bm25_doc_freq[token] += 1
                    self.token_to_entries[token].add(entry_index)
                total_tokens += len(tokens)
        self._bm25_avg_len = total_tokens / max(len(self.alias_entries), 1)

    def generate(self, query: str, top_k: int = 5, per_method_k: int = 40, dhba_filter: str = "both") -> list[dict[str, object]]:
        """Generate candidates for *query*.

        Parameters
        ----------
        dhba_filter:
            ``"both"`` (default) — return all candidates regardless of DHBA coverage.
            ``"with"`` — return only candidates that have a non-empty ``DHBA_name``.
            ``"without"`` — return only candidates that have an empty ``DHBA_name``.
        """
        variants = query_variants(query, self.config, self.alias_rules, self.abbrev_rules)
        modifier_terms = extract_modifier_terms(query, self.config)
        candidate_state: dict[int, dict[str, object]] = {}

        for variant in variants:
            normalized = normalize_text(variant)
            for term_index in self.alias_map.get(normalized, set()):
                self._add_candidate(candidate_state, term_index, "exact", 1.0, variant, variant)

        for term_index, score, alias, matched_query in self._fuzzy_candidates(variants, per_method_k):
            self._add_candidate(candidate_state, term_index, "fuzzy", score, alias, matched_query)

        for term_index, score, alias, matched_query in self._bm25_candidates(variants, per_method_k):
            self._add_candidate(candidate_state, term_index, "bm25", score, alias, matched_query)

        # Pass 1: compute preliminary final scores (with penalties) so that
        # _promote_common_parents uses penalised child scores, not raw method scores.
        prelim_scores: dict[int, float] = {}
        for term_index, state in candidate_state.items():
            prelim_scores[term_index], _ = self._score_candidate(query, modifier_terms, term_index, state)

        self._promote_common_parents(query, modifier_terms, candidate_state, prelim_scores)

        # Pass 2: build final ranked list (now includes any hierarchy_parent entries).
        ranked = []
        for term_index, state in candidate_state.items():
            term = self.terms[term_index]
            final_score, mod_score = self._score_candidate(query, modifier_terms, term_index, state)
            ranked.append(
                {
                    "homba_id": term.homba_id,
                    "name": term.name,
                    "acronym": term.acronym,
                    "dhba_name": term.dhba_name,
                    "dhba_acronym": term.dhba_acronym,
                    "parent_id": term.parent_id,
                    "graph_order": term.graph_order,
                    "depth": term.depth,
                    "score": round(min(final_score, 1.0), 6),
                    "methods": "+".join(sorted(state["methods"])),
                    "matched_alias": state["matched_alias"],
                    "matched_query": state["matched_query"],
                    "modifier_terms": ";".join(modifier_terms),
                    "modifier_match_score": round(mod_score, 6),
                    "hierarchy_reason": state.get("hierarchy_reason", ""),
                }
            )

        ranked.sort(key=lambda item: (-float(item["score"]), str(item["name"]).lower(), str(item["homba_id"])))

        if dhba_filter == "with":
            ranked = [c for c in ranked if c["dhba_name"]]
        elif dhba_filter == "without":
            ranked = [c for c in ranked if not c["dhba_name"]]

        return ranked[:top_k]

    def _score_candidate(
        self,
        query: str,
        modifier_terms: list[str],
        term_index: int,
        state: dict[str, object],
    ) -> tuple[float, float]:
        """Compute ``(final_score, modifier_score)`` for a single candidate.

        Specificity penalty rules
        -------------------------
        * Exact match → never penalised.
        * Pure hierarchy_parent (no direct fuzzy/bm25 evidence) → never penalised
          (the promoted score already reflects the penalised child scores).
        * Fuzzy / BM25 match without exact → penalty applied.
        """
        term = self.terms[term_index]
        method_scores = state["method_scores"]
        exact = method_scores.get("exact", 0.0)
        fuzzy = method_scores.get("fuzzy", 0.0)
        bm25 = method_scores.get("bm25", 0.0)
        hierarchy = method_scores.get("hierarchy_parent", 0.0)
        token_score = max(
            token_jaccard(tokenize(query, self.config), tokenize(alias, self.config))
            for alias in term.aliases
        )
        mod_score = modifier_match_score(modifier_terms, term.aliases)

        final_score = max(
            hierarchy,
            exact,
            0.5 * fuzzy + 0.3 * bm25 + 0.2 * token_score,
            0.75 * fuzzy + 0.25 * token_score,
        )
        if exact:
            final_score = max(final_score, 0.96)
        if modifier_terms:
            final_score = min(final_score + 0.12 * mod_score, 1.0) if mod_score else min(final_score * 0.88, 0.88)
        if not exact and (fuzzy or bm25):
            final_score *= self._specificity_penalty(query, modifier_terms, term)

        return final_score, mod_score

    def _entry_indexes_for_tokens(self, tokens: list[str], rarest_limit: int | None = None) -> Iterable[int]:
        search_tokens = list(dict.fromkeys(tokens))
        if rarest_limit is not None and len(search_tokens) > rarest_limit:
            search_tokens.sort(key=lambda token: self._bm25_doc_freq.get(token, 0))
            search_tokens = search_tokens[:rarest_limit]
        entry_indexes: set[int] = set()
        for token in search_tokens:
            entry_indexes.update(self.token_to_entries.get(token, set()))
        return entry_indexes

    def _fuzzy_candidates(self, variants: list[str], limit: int) -> list[tuple[int, float, str, str]]:
        best_by_term: dict[int, tuple[float, str, str]] = {}
        for variant in variants:
            query_tokens = tokenize(variant, self.config)
            entry_indexes = self._entry_indexes_for_tokens(query_tokens, rarest_limit=2)
            if not entry_indexes and len(normalize_text(variant)) > 5:
                entry_indexes = range(len(self.alias_entries))
            for entry_index in entry_indexes:
                entry = self.alias_entries[entry_index]
                score = string_similarity(variant, entry.alias, self.config)
                if score >= 0.45 and (entry.term_index not in best_by_term or score > best_by_term[entry.term_index][0]):
                    best_by_term[entry.term_index] = (score, entry.alias, variant)
        ranked = sorted(best_by_term.items(), key=lambda item: item[1][0], reverse=True)
        return [(term_index, score, alias, query) for term_index, (score, alias, query) in ranked[:limit]]

    def _bm25_candidates(self, variants: list[str], limit: int) -> list[tuple[int, float, str, str]]:
        best_by_term: dict[int, tuple[float, str, str]] = {}
        total_docs = max(len(self.alias_entries), 1)
        k1 = 1.5
        b = 0.75
        for variant in variants:
            query_tokens = tokenize(variant, self.config)
            if not query_tokens:
                continue
            query_counts = Counter(query_tokens)
            for entry_index in self._entry_indexes_for_tokens(query_tokens):
                entry = self.alias_entries[entry_index]
                if not entry.tokens:
                    continue
                raw_score = 0.0
                doc_len = len(entry.tokens)
                for token, query_count in query_counts.items():
                    freq = entry.token_counts.get(token, 0)
                    if not freq:
                        continue
                    df = self._bm25_doc_freq.get(token, 0)
                    idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
                    denom = freq + k1 * (1 - b + b * doc_len / max(self._bm25_avg_len, 1e-9))
                    raw_score += idf * (freq * (k1 + 1) / denom) * query_count
                if raw_score <= 0:
                    continue
                score = raw_score / (raw_score + 4.0)
                if entry.term_index not in best_by_term or score > best_by_term[entry.term_index][0]:
                    best_by_term[entry.term_index] = (score, entry.alias, variant)
        ranked = sorted(best_by_term.items(), key=lambda item: item[1][0], reverse=True)
        return [(term_index, score, alias, query) for term_index, (score, alias, query) in ranked[:limit]]

    def _promote_common_parents(
        self,
        query: str,
        modifier_terms: list[str],
        candidate_state: dict[int, dict[str, object]],
        prelim_scores: dict[int, float],
    ) -> None:
        """Promote a shared parent when 2+ sibling candidates exist.

        Uses *prelim_scores* (pass-1 penalised final scores) rather than raw
        method scores so the parent cannot outscore a directly matched child.
        """
        if modifier_terms:
            return
        query_tokens = set(tokenize(query, self.config))
        parent_to_children: dict[str, list[int]] = defaultdict(list)
        for term_index in candidate_state:
            parent_id = self.terms[term_index].parent_id
            if parent_id:
                parent_to_children[parent_id].append(term_index)
        for parent_id, child_indexes in parent_to_children.items():
            if len(child_indexes) < 2:
                continue
            parent_index = self.term_index_by_id.get(parent_id)
            if parent_index is None:
                continue
            parent = self.terms[parent_index]
            parent_token_score = max(token_jaccard(query_tokens, tokenize(alias, self.config)) for alias in parent.aliases)
            if parent_token_score <= 0:
                continue
            child_scores = [
                prelim_scores.get(idx, float(candidate_state[idx]["best_method_score"]))
                for idx in child_indexes
            ]
            promoted_score = min(max(child_scores) + 0.08, 0.97)
            self._add_candidate(
                candidate_state,
                parent_index,
                "hierarchy_parent",
                promoted_score,
                parent.name,
                query,
                f"common_parent_of_{len(child_indexes)}_candidates",
            )

    def _specificity_penalty(self, query: str, modifier_terms: list[str], term: HOMBATerm) -> float:
        if modifier_terms or not term.parent_id:
            return 1.0
        query_specificity = specificity_terms(query, self.config)
        candidate_specificity: set[str] = set()
        for alias in term.aliases:
            candidate_specificity.update(specificity_terms(alias, self.config))
        return 0.86 if candidate_specificity - query_specificity else 1.0

    def _add_candidate(
        self,
        candidate_state: dict[int, dict[str, object]],
        term_index: int,
        method: str,
        score: float,
        alias: str,
        matched_query: str,
        hierarchy_reason: str = "",
    ) -> None:
        state = candidate_state.setdefault(
            term_index,
            {
                "methods": set(),
                "method_scores": {},
                "matched_alias": alias,
                "matched_query": matched_query,
                "best_method_score": score,
                "hierarchy_reason": hierarchy_reason,
            },
        )
        state["methods"].add(method)
        state["method_scores"][method] = max(state["method_scores"].get(method, 0.0), score)
        if score > state["best_method_score"]:
            state["best_method_score"] = score
            state["matched_alias"] = alias
            state["matched_query"] = matched_query
        if hierarchy_reason:
            state["hierarchy_reason"] = hierarchy_reason


def response(status_code: int, body: dict[str, object]) -> dict[str, object]:
    return {
        "statusCode": status_code,
        "headers": {
            "Access-Control-Allow-Origin": os.environ.get("ALLOWED_ORIGIN", "*"),
            "Access-Control-Allow-Headers": "Content-Type",
            "Access-Control-Allow-Methods": "OPTIONS,POST",
            "Content-Type": "application/json; charset=utf-8",
        },
        "body": json.dumps(body, ensure_ascii=False),
    }


def ensure_file_from_s3(bucket: str, key: str, local_name: str) -> Path:
    local_path = Path("/tmp") / local_name
    if not local_path.exists():
        S3.download_file(bucket, key, str(local_path))
    return local_path


def get_generator() -> RosettaCandidateGenerator:
    global GENERATOR
    if GENERATOR is not None:
        return GENERATOR

    bucket = os.environ["HOMBA_BUCKET"]
    homba_key = os.environ.get("HOMBA_KEY", "HOMBA_v1_fixed.csv")
    token_rules_key = os.environ.get("TOKEN_RULES_KEY", "homba_token_rules.csv")
    alias_rules_key = os.environ.get("ALIAS_RULES_KEY", "homba_alias_rules.csv")
    abbrev_rules_key = os.environ.get("ABBREV_RULES_KEY", "homba_abbrev_rules.csv")
    homba_path = ensure_file_from_s3(bucket, homba_key, "HOMBA_v1_fixed.csv")
    token_rules_path = ensure_file_from_s3(bucket, token_rules_key, "homba_token_rules.csv")
    alias_rules_path = ensure_file_from_s3(bucket, alias_rules_key, "homba_alias_rules.csv")
    abbrev_rules_path = ensure_file_from_s3(bucket, abbrev_rules_key, "homba_abbrev_rules.csv")
    GENERATOR = RosettaCandidateGenerator(homba_path, token_rules_path, alias_rules_path, abbrev_rules_path)
    return GENERATOR


def lambda_handler(event, context):
    if event.get("requestContext", {}).get("http", {}).get("method") == "OPTIONS":
        return response(200, {"ok": True})

    try:
        payload = json.loads(event.get("body") or "{}")
        query = str(payload.get("query", "")).strip()
        top_k = int(payload.get("top_k", 5))
        top_k = max(1, min(top_k, 20))
        dhba_filter = str(payload.get("dhba_filter", "both")).strip().lower()
        if dhba_filter not in ("both", "with", "without"):
            dhba_filter = "both"
        if not query:
            return response(400, {"error": "query is required"})

        generator = get_generator()
        candidates = generator.generate(query, top_k=top_k, dhba_filter=dhba_filter)
        for candidate in candidates:
            score = float(candidate["score"])
            modifier_terms = str(candidate.get("modifier_terms", ""))
            modifier_score = float(candidate.get("modifier_match_score", 1.0) or 1.0)
            if modifier_terms and modifier_score < 1.0:
                review_flag = "modifier_conflict"
            elif score >= 0.90:
                review_flag = "high_confidence"
            elif score < 0.60:
                review_flag = "low_confidence"
            else:
                review_flag = "needs_review"
            candidate["review_flag"] = review_flag

        return response(200, {"query": query, "top_k": top_k, "dhba_filter": dhba_filter, "candidates": candidates})
    except Exception as exc:
        return response(500, {"error": str(exc)})
