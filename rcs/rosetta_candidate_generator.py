#!/usr/bin/env python3
# VERSION: 0.7.0
# Versioning rule:
# - Behavior changes or scoring logic changes: increment PATCH (e.g. 0.1.0 -> 0.1.1)
# - Backward-compatible input/output field additions: increment MINOR (e.g. 0.1.0 -> 0.2.0)
# - Backward-incompatible API/input/output changes: increment MAJOR (e.g. 0.1.0 -> 1.0.0)
# Lambda imports this module from rcs/ via scripts/package_lambda.* (no duplicate copy).
"""ROSETTA Candidate Search — candidate generation for mapping brain-region mentions to HOMBA terms.

This module intentionally stays dependency-free.  It implements the practical
parts of the implementation plan: normalization, alias lookup, fuzzy string
matching, and a lightweight BM25-style token search.
"""

from __future__ import annotations

import csv
import math
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Iterable


ENGINE_VERSION = "0.7.0"

# Pure positional / directional words.  On their own these do not identify a
# structure: two unrelated regions can both be "posterior" or "ventral".  They
# are therefore excluded from standalone modifier evidence (see
# extract_modifier_terms) so a candidate cannot win purely by sharing a
# direction word with the query.
POSITIONAL_WORDS = {
    "anterior", "posterior", "superior", "inferior",
    "ventral", "dorsal", "medial", "lateral",
    "rostral", "caudal", "oral",
    "dorsomedial", "ventromedial", "dorsolateral", "ventrolateral",
    "anteroposterior", "central",
}

# Regex for area / cell-group identifier tokens such as "23c", "24dd", "a8",
# "v3a", "op1", "5".  These carry a specific numeric identity: two structures
# with different identifiers (e.g. cingulate "area 23c" vs "area 5", or the
# "A1" vs "A8" cell groups) are different even when the surrounding words match.
_AREA_ID_RE = re.compile(r"^([a-z]{0,3})(\d+)([a-z]{0,3})$")


def _parse_area_id(token: str) -> tuple[str, int] | None:
    """Return (alpha_prefix, numeric_core) for an area-id token, else None."""
    m = _AREA_ID_RE.match(token)
    if not m:
        return None
    return m.group(1), int(m.group(2))


def _area_ids_compatible(query_ids: set[str], cand_ids: set[str]) -> bool:
    """Whether any query area-id is compatible with any candidate area-id.

    Two ids are compatible when they share the same alphabetic prefix *and*
    numeric core.  A subdivision suffix is ignored so ``6a`` matches area ``6``
    and ``3a`` matches area ``3`` (subdivisions of the same area), while ``23c``
    stays distinct from ``5`` and cell group ``a1`` stays distinct from ``a8``.
    """
    q_parsed = [p for p in (_parse_area_id(t) for t in query_ids) if p]
    c_parsed = [p for p in (_parse_area_id(t) for t in cand_ids) if p]
    if not q_parsed or not c_parsed:
        return True  # nothing comparable -> do not penalise
    return any(q == c for q in q_parsed for c in c_parsed)


# Mutually exclusive anatomical structure classes.  A query that clearly names
# one class should not rank a candidate whose only strong cue is a different
# class (tract↔nucleus, nerve↔ventricle, organ↔nucleus, …).
_STRUCTURE_CLASS_TOKENS: dict[str, frozenset[str]] = {
    "gray": frozenset({
        "nucleus", "nuclei", "ganglion", "ganglia",
    }),
    "white": frozenset({
        "tract", "fasciculus", "fascicle", "radiation", "stria", "striae",
        "commissure", "bundle", "capsule", "lemniscus", "path", "pathway",
        "fiber", "fibers", "fibre", "fibres",
    }),
    "nerve": frozenset({"nerve", "nerves"}),
    "ventricle": frozenset({"ventricle", "ventricles"}),
    "sulcus": frozenset({"sulcus", "sulci", "fissure", "fissures"}),
    "organ": frozenset({"cochlea", "apparatus"}),
    "cortex": frozenset({"cortex", "cortical", "gyrus", "gyri"}),
    "lobule": frozenset({"lobule", "lobules"}),
}

# Distinguishing morphological prefixes.  When the query carries one of these
# fused to a stem (``precuneiform``, ``retroreuniens``, ``juxtaparaventricular``)
# and the candidate matches only the bare stem, they name different structures.
_DISTINGUISHING_PREFIXES = (
    "juxta", "retro", "supra", "infra", "peri", "para", "hypo", "hyper",
    "inter", "intra", "extra", "endo", "ecto", "meta", "proto",
    "pre", "sub",
)

HOMBA_ID_FIELD = "unified_ontology_id"
HOMBA_NAME_FIELD = "unified_ontology_name"
HOMBA_ACRONYM_FIELD = "unified_ontology_acronym"
DHBA_NAME_FIELD = "DHBA_name"
DHBA_ACRONYM_FIELD = "DHBA_acronym"
PARENT_ID_FIELD = "parent_identifier"


DEFAULT_TOKEN_RULES_CSV = Path(__file__).with_name("homba_token_rules.csv")
DEFAULT_ALIAS_RULES_CSV = Path(__file__).with_name("homba_alias_rules.csv")


@dataclass(frozen=True)
class LexiconConfig:
    stopwords: set[str]
    laterality_words: set[str]
    weak_terms: set[str]
    modifier_terms: set[str]


@dataclass(frozen=True)
class HOMBATerm:
    """A single HOMBA row with all searchable aliases."""

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
    bidirectional: bool = True


@dataclass(frozen=True)
class AbbrevRule:
    """Query-only abbreviation expansion (never applied to HOMBA alias expansion)."""

    abbrev: str      # normalized abbreviation, e.g. "lc"
    expansion: str   # normalized expansion, e.g. "locus coeruleus"
    notes: str = ""


DEFAULT_ABBREV_RULES_CSV = Path(__file__).with_name("homba_abbrev_rules.csv")


def normalize_text(text: str) -> str:
    """Normalize text for alias lookup and string similarity."""

    text = unicodedata.normalize("NFKC", text or "")
    text = text.replace("&", " and ")
    text = text.replace("/", " ")
    text = re.sub(r"['`´]", "", text)
    text = re.sub(r"[-_]+", " ", text)
    text = re.sub(r"[^0-9A-Za-z]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip().lower()
    return text


def strip_laterality(text: str, config: LexiconConfig | None = None) -> str:
    config = config or DEFAULT_CONFIG
    tokens = normalize_text(text).split()
    tokens = [token for token in tokens if token not in config.laterality_words]
    return " ".join(tokens)


def strip_parenthetical(text: str) -> str:
    return re.sub(r"\([^)]*\)", " ", text)


def tokenize(text: str, *, keep_stopwords: bool = False, config: LexiconConfig | None = None) -> list[str]:
    config = config or DEFAULT_CONFIG
    tokens = normalize_text(text).split()
    if keep_stopwords:
        return tokens
    return [token for token in tokens if token not in config.stopwords]


def unique_preserve_order(items: Iterable[str]) -> list[str]:
    seen = set()
    result = []
    for item in items:
        cleaned = (item or "").strip()
        if not cleaned:
            continue
        key = normalize_text(cleaned)
        if not key or key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
    return result


def load_lexicon_config(token_rules_csv: str | Path = DEFAULT_TOKEN_RULES_CSV) -> LexiconConfig:
    """Load token handling rules from CSV instead of hard-coding data."""

    stopwords: set[str] = set()
    laterality_words: set[str] = set()
    weak_terms: set[str] = set()
    modifier_terms: set[str] = set()

    token_rules_path = Path(token_rules_csv)
    if token_rules_path.exists():
        with token_rules_path.open(newline="", encoding="utf-8-sig") as handle:
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


DEFAULT_CONFIG = load_lexicon_config()


def load_alias_rules(alias_rules_csv: str | Path = DEFAULT_ALIAS_RULES_CSV) -> list[AliasRule]:
    """Load curated synonym/word-form rules from CSV."""

    alias_rules_path = Path(alias_rules_csv)
    if not alias_rules_path.exists():
        return []

    rules: list[AliasRule] = []
    with alias_rules_path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            input_text = normalize_text(row.get("input_text", ""))
            homba_text = normalize_text(row.get("homba_text", ""))
            if not input_text or not homba_text or input_text == homba_text:
                continue
            direction = (row.get("bidirectional") or "").strip().lower()
            bidirectional = direction not in {"no", "false", "0", "n", "one-way", "oneway"}
            rules.append(
                AliasRule(
                    input_text=input_text,
                    homba_text=homba_text,
                    notes=(row.get("notes") or "").strip(),
                    bidirectional=bidirectional,
                )
            )
    return rules


def load_abbrev_rules(abbrev_rules_csv: str | Path = DEFAULT_ABBREV_RULES_CSV) -> list[AbbrevRule]:
    """Load query-only abbreviation rules.

    Unlike alias rules these are *never* applied to HOMBA alias expansion,
    which prevents short abbreviations from polluting the inverted index.
    """
    path = Path(abbrev_rules_csv)
    if not path.exists():
        return []
    rules: list[AbbrevRule] = []
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


def expand_with_alias_rules(text: str, alias_rules: list[AliasRule]) -> list[str]:
    """Add curated wording variants such as amygdala <-> amygdaloid complex."""

    normalized = normalize_text(text)
    variants = [text]
    if not normalized:
        return variants

    for rule in alias_rules:
        if rule.bidirectional:
            replacements = (
                (rule.input_text, rule.homba_text),
                (rule.homba_text, rule.input_text),
            )
        else:
            replacements = ((rule.input_text, rule.homba_text),)
        for source, target in replacements:
            if normalized == source:
                variants.append(target)
            replaced = re.sub(rf"\b{re.escape(source)}\b", target, normalized)
            if replaced != normalized:
                variants.append(replaced)

    return unique_preserve_order(variants)


def expand_alias(alias: str, alias_rules: list[AliasRule] | None = None) -> list[str]:
    """Create practical HOMBA-side aliases from parentheses and commas."""

    aliases = [alias]
    alias_rules = alias_rules or []

    without_parentheses = strip_parenthetical(alias)
    aliases.append(without_parentheses)

    for group in re.findall(r"\(([^)]*)\)", alias):
        for part in re.split(r"[,;/]", group):
            aliases.append(part)
            base = normalize_text(without_parentheses)
            suffix = normalize_text(part)
            if suffix and not suffix.isdigit():
                aliases.append(f"{base} {suffix}")

    if "," in alias:
        left, right = [part.strip() for part in alias.split(",", 1)]
        if left and right:
            aliases.append(f"{right} {left}")

    # One-way rules normalize queries only; applying them to HOMBA names would
    # create misleading reverse aliases for unrelated structures.
    homba_side_rules = [rule for rule in alias_rules if rule.bidirectional]
    expanded: list[str] = []
    for item in aliases:
        expanded.extend(expand_with_alias_rules(item, homba_side_rules))

    return unique_preserve_order(expanded)


def query_variants(
    query: str,
    config: LexiconConfig | None = None,
    alias_rules: list[AliasRule] | None = None,
    abbrev_rules: list[AbbrevRule] | None = None,
) -> list[str]:
    """Generate normalized query variants before candidate generation."""

    config = config or DEFAULT_CONFIG
    alias_rules = alias_rules or []
    abbrev_rules = abbrev_rules or []
    variants = [query, strip_laterality(query, config), strip_parenthetical(query)]

    # Keep parenthetical content as ordinary tokens so "Anterior nucleus
    # (thalamus)" also searches as "Anterior nucleus thalamus".
    variants.append(re.sub(r"[()]", " ", query))

    # "thalamus (excluding pulvinar)" should still search for "thalamus".
    variants.append(re.sub(r"\b(excluding|except|without)\b.*$", " ", strip_parenthetical(query), flags=re.I))

    expanded: list[str] = []
    for variant in variants:
        expanded.extend(expand_with_alias_rules(variant, alias_rules))

    # Apply abbreviation expansion last (query-only; not used for HOMBA alias expansion).
    abbrev_expanded: list[str] = []
    for variant in expanded:
        abbrev_expanded.extend(apply_abbrev_rules(variant, abbrev_rules))

    return unique_preserve_order(abbrev_expanded)


def extract_modifier_terms(query: str, config: LexiconConfig | None = None) -> list[str]:
    """Keep parenthetical and known subdivision words as ranking evidence."""

    config = config or DEFAULT_CONFIG
    terms: list[str] = []
    for group in re.findall(r"\(([^)]*)\)", query):
        group_tokens = tokenize(group, config=config)
        terms.extend(group_tokens)
        normalized_group = normalize_text(group)
        if normalized_group and len(group_tokens) > 1:
            terms.append(normalized_group)

    for token in tokenize(query, config=config):
        if token in config.modifier_terms:
            terms.append(token)

    return unique_preserve_order(terms)


def modifier_match_score(modifier_terms: list[str], aliases: Iterable[str]) -> float:
    if not modifier_terms:
        return 1.0
    alias_text = " ".join(normalize_text(alias) for alias in aliases)
    matched = 0
    for term in modifier_terms:
        normalized = normalize_text(term)
        if normalized and normalized in alias_text:
            matched += 1
    return matched / len(modifier_terms)


def specificity_terms(text: str, config: LexiconConfig | None = None) -> set[str]:
    """Terms that usually make a candidate more specific than its parent."""

    config = config or DEFAULT_CONFIG
    tokens = set(tokenize(text, keep_stopwords=True, config=config))
    return {
        token
        for token in tokens
        if token in config.modifier_terms or token in config.weak_terms
    }


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


def _boundary_contains(haystack: str, needle: str) -> bool:
    """Return True if *needle* occurs in *haystack* on word boundaries.

    A plain substring test lets a distinguishing prefix leak through: the query
    ``precuneiform nucleus`` "contains" ``cuneiform nucleus`` mid-token, and the
    old containment bonus then scored them as near-identical even though they are
    different nuclei.  Requiring the match to start and end on a token boundary
    (string edge or space) keeps legitimate containment (``insular cortex`` in
    ``major insular cortex``) while rejecting prefix-collision matches
    (``reuniens ...`` inside ``retroreuniens ...``).
    """
    start = 0
    n = len(needle)
    while True:
        idx = haystack.find(needle, start)
        if idx < 0:
            return False
        before_ok = idx == 0 or haystack[idx - 1] == " "
        after = idx + n
        after_ok = after == len(haystack) or haystack[after] == " "
        if before_ok and after_ok:
            return True
        start = idx + 1


def _head_structure_class(tokens: Iterable[str]) -> str | None:
    """Return the structure-class label of the syntactic head.

    Prefers the ``CLASS of …`` pattern (``nucleus of lateral olfactory tract``
    → gray).  Otherwise uses the *last* class token so
    ``lateral lemniscus, dorsal nucleus`` resolves to nucleus, not lemniscus.
    """
    token_list = list(tokens)
    token_to_class = {
        token: label
        for label, members in _STRUCTURE_CLASS_TOKENS.items()
        for token in members
    }
    for index, token in enumerate(token_list):
        label = token_to_class.get(token)
        if label is not None and index + 1 < len(token_list) and token_list[index + 1] == "of":
            return label
    head: str | None = None
    for token in token_list:
        label = token_to_class.get(token)
        if label is not None:
            head = label
    return head


def _structure_class_conflict(query_tokens: Iterable[str], cand_tokens: Iterable[str]) -> bool:
    """True when query and candidate assert incompatible structure-class heads."""
    q_head = _head_structure_class(query_tokens)
    c_head = _head_structure_class(cand_tokens)
    if q_head is None or c_head is None:
        return False
    return q_head != c_head


def _strip_distinguishing_prefix(token: str) -> str | None:
    """If *token* begins with a distinguishing prefix, return the bare stem."""
    for prefix in _DISTINGUISHING_PREFIXES:
        if token.startswith(prefix) and len(token) - len(prefix) >= 5:
            # Avoid stripping when the remainder is itself only a short prefix
            # fragment (e.g. "preoptic" → "optic" is intentional and useful).
            return token[len(prefix):]
    return None


def _distinguishing_affix_mismatch(query_tokens: set[str], cand_tokens: set[str]) -> bool:
    """True when the query's prefixed form is absent from the candidate.

    ``precuneiform`` vs ``cuneiform``, ``retroreuniens`` vs ``reuniens``, and
    ``juxtaparaventricular`` vs ``paraventricular`` are different nuclei; a
    fuzzy match on the shared stem alone must not win.
    """
    for qtok in query_tokens:
        stem = _strip_distinguishing_prefix(qtok)
        if stem is None:
            continue
        if qtok in cand_tokens:
            continue  # candidate also carries the prefixed form
        # Candidate has the bare stem (exact token or longer token that is the
        # stem / starts with the stem as a word-like unit).
        if stem in cand_tokens or any(
            ctok == stem or (len(ctok) >= 5 and ctok.startswith(stem) and qtok not in ctok)
            for ctok in cand_tokens
        ):
            return True
    return False


def string_similarity(query: str, alias: str) -> float:
    q_norm = normalize_text(query)
    a_norm = normalize_text(alias)
    if not q_norm or not a_norm:
        return 0.0
    if q_norm == a_norm:
        return 1.0

    sequence = SequenceMatcher(None, q_norm, a_norm).ratio()
    bigram = dice_coefficient(char_ngrams(q_norm, 2), char_ngrams(a_norm, 2))
    trigram = dice_coefficient(char_ngrams(q_norm, 3), char_ngrams(a_norm, 3))
    tokens = token_jaccard(tokenize(q_norm), tokenize(a_norm))

    containment = 0.0
    if len(q_norm) >= 4 and _boundary_contains(a_norm, q_norm):
        containment = min(0.92, len(q_norm) / max(len(a_norm), 1) + 0.25)
    if len(a_norm) >= 4 and _boundary_contains(q_norm, a_norm):
        containment = max(containment, min(0.92, len(a_norm) / max(len(q_norm), 1) + 0.25))

    return max(containment, 0.35 * sequence + 0.25 * bigram + 0.2 * trigram + 0.2 * tokens)


class RosettaCandidateGenerator:
    """Build HOMBA aliases and generate high-recall candidates for a query."""

    def __init__(
        self,
        homba_csv_path: str | Path,
        *,
        token_rules_csv: str | Path = DEFAULT_TOKEN_RULES_CSV,
        alias_rules_csv: str | Path = DEFAULT_ALIAS_RULES_CSV,
        abbrev_rules_csv: str | Path = DEFAULT_ABBREV_RULES_CSV,
        config: LexiconConfig | None = None,
    ):
        self.homba_csv_path = Path(homba_csv_path)
        self.config = config or load_lexicon_config(token_rules_csv)
        direction_words = {
            "posterior", "ventral", "dorsal", "lateral", "medial",
            "caudal", "rostral", "oral",
        }
        # Lobe labels still provide useful anatomical evidence and are
        # deliberately excluded from weak-only matching.
        lobe_words = {"frontal", "parietal", "temporal", "occipital", "opercular"}
        self._noncontent_tokens = (
            self.config.laterality_words
            | self.config.weak_terms
            | (self.config.modifier_terms & direction_words)
        ) - lobe_words
        self._content_cache: dict[str, frozenset[str]] = {}
        self._area_id_cache: dict[int, frozenset[str]] = {}
        self.alias_rules = load_alias_rules(alias_rules_csv)
        self.abbrev_rules = load_abbrev_rules(abbrev_rules_csv)
        self.terms: list[HOMBATerm] = []
        self.term_index_by_id: dict[str, int] = {}
        self.alias_entries: list[AliasEntry] = []
        self.alias_map: dict[str, set[int]] = defaultdict(set)
        self.token_to_entries: dict[str, set[int]] = defaultdict(set)
        self._bm25_doc_freq: Counter[str] = Counter()
        self._bm25_avg_len = 0.0
        self._load_homba_csv()
        self._build_indexes()

    def _load_homba_csv(self) -> None:
        with self.homba_csv_path.open(newline="", encoding="utf-8-sig") as handle:
            reader = csv.DictReader(handle)
            hierarchy_fields = [
                field
                for field in (reader.fieldnames or [])
                if field.startswith("hierarchy")
                or field.startswith("Unnamed:")
            ]

            for row_index, row in enumerate(reader):
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

                expanded_aliases = self._drop_generic_only_aliases(expanded_aliases)
                aliases = tuple(unique_preserve_order(expanded_aliases))
                name = (row.get(HOMBA_NAME_FIELD) or "").strip()
                if not name:
                    continue

                depth = self._infer_depth(row, hierarchy_fields)
                term = HOMBATerm(
                    row_index=row_index,
                    homba_id=(row.get(HOMBA_ID_FIELD) or "").strip(),
                    name=name,
                    acronym=(row.get(HOMBA_ACRONYM_FIELD) or "").strip(),
                    dhba_name=(row.get(DHBA_NAME_FIELD) or "").strip(),
                    dhba_acronym=(row.get(DHBA_ACRONYM_FIELD) or "").strip(),
                    parent_id=(row.get(PARENT_ID_FIELD) or "").strip(),
                    graph_order=(row.get("graph_order") or "").strip(),
                    depth=depth,
                    aliases=aliases,
                )
                self.term_index_by_id[term.homba_id] = len(self.terms)
                self.terms.append(term)

    def _drop_generic_only_aliases(self, aliases: list[str]) -> list[str]:
        """Remove derived aliases that carry no identifying content.

        Parenthetical expansion turns ``subincertal nucleus (area)`` into the
        bare alias ``area``; ``(dorsal)`` becomes ``dorsal``.  Such tokens are
        stopwords / weak / laterality / modifier words, so an alias made up only
        of them matches any query that happens to share that generic word
        ("Frontoinsular *area*", "Opercular *area* OP2-3") and drags unrelated
        structures to the top.  We keep the first alias unconditionally so a
        term is never left without a searchable name.
        """
        generic = (
            self.config.stopwords
            | self.config.weak_terms
            | self.config.laterality_words
            | self.config.modifier_terms
        )
        kept: list[str] = []
        for index, alias in enumerate(aliases):
            tokens = tokenize(alias, keep_stopwords=True, config=self.config)
            if index == 0 or any(token not in generic for token in tokens):
                kept.append(alias)
        return kept

    @staticmethod
    def _infer_depth(row: dict[str, str], hierarchy_fields: list[str]) -> int:
        parent = (row.get("parent") or "").strip()
        if parent.isdigit():
            try:
                return int(parent) + 1
            except ValueError:
                pass

        nonempty_positions = [
            index for index, field in enumerate(hierarchy_fields) if (row.get(field) or "").strip()
        ]
        return max(nonempty_positions) if nonempty_positions else 0

    def _build_indexes(self) -> None:
        total_tokens = 0
        for term_index, term in enumerate(self.terms):
            for alias in term.aliases:
                normalized = normalize_text(alias)
                if not normalized:
                    continue
                tokens = tuple(tokenize(normalized, config=self.config))
                token_counts = Counter(tokens)
                entry = AliasEntry(
                    term_index=term_index,
                    alias=alias,
                    normalized=normalized,
                    tokens=tokens,
                    token_counts=token_counts,
                )
                self.alias_entries.append(entry)
                entry_index = len(self.alias_entries) - 1
                self.alias_map[normalized].add(term_index)

                token_set = set(tokens)
                self._bm25_doc_freq.update(token_set)
                for token in token_set:
                    self.token_to_entries[token].add(entry_index)
                total_tokens += len(tokens)

        self._bm25_avg_len = total_tokens / max(len(self.alias_entries), 1)

    def generate(self, query: str, top_k: int = 10, per_method_k: int = 40, dhba_filter: str = "both") -> list[dict[str, object]]:
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
            if not normalized:
                continue

            for term_index in self.alias_map.get(normalized, set()):
                self._add_candidate(
                    candidate_state,
                    term_index,
                    method="exact",
                    score=1.0,
                    alias=variant,
                    matched_query=variant,
                )

        for term_index, score, alias, matched_query in self._fuzzy_candidates(variants, per_method_k):
            self._add_candidate(candidate_state, term_index, "fuzzy", score, alias, matched_query)

        for term_index, score, alias, matched_query in self._bm25_candidates(variants, per_method_k):
            self._add_candidate(candidate_state, term_index, "bm25", score, alias, matched_query)

        # Determine which positional words in the query actually *resolve* to a
        # specific structure in the candidate pool.  A positional word is only
        # meaningful for ranking when some candidate that shares the query's core
        # content word also carries that direction: e.g. "lateral" resolves for
        # "substantia nigra (lateral part)" because "substantia nigra, lateral
        # division" exists, so the bare parent should be demoted in its favour.
        # "posterior" does NOT resolve for "posterior insular area" (no insular
        # child names "posterior"), so it must not penalise the parent fallback.
        self._resolvable_positional = self._compute_resolvable_positional(
            query, modifier_terms, candidate_state)

        # Pass 1: score every non-hierarchy candidate so that _promote_common_parents
        # can use penalised final scores (not raw method scores) when deciding how
        # much to boost a common parent.
        prelim_scores: dict[int, float] = {}
        for term_index, state in candidate_state.items():
            prelim_scores[term_index], _ = self._score_candidate(query, modifier_terms, term_index, state)

        self._promote_common_parents(query, modifier_terms, candidate_state, prelim_scores)

        # Pass 2: build the final ranked list (now includes any hierarchy_parent entries).
        ranked = []
        for term_index, state in candidate_state.items():
            term = self.terms[term_index]
            final_score, modifier_score = self._score_candidate(query, modifier_terms, term_index, state)
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
                    "best_method_score": round(state["best_method_score"], 6),
                    "modifier_terms": ";".join(modifier_terms),
                    "modifier_match_score": round(modifier_score, 6),
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
        * Exact match → never penalised (the query directly named the alias).
        * Pure hierarchy_parent (no direct fuzzy/bm25 evidence) → never penalised
          (the promoted score already reflects the penalised child scores).
        * Fuzzy / BM25 match without exact → penalty applied as before.
        """
        term = self.terms[term_index]
        method_scores = state["method_scores"]
        exact = method_scores.get("exact", 0.0)
        fuzzy = method_scores.get("fuzzy", 0.0)
        bm25 = method_scores.get("bm25", 0.0)
        hierarchy = method_scores.get("hierarchy_parent", 0.0)
        token_score = max(
            token_jaccard(tokenize(query, config=self.config), tokenize(alias, config=self.config))
            for alias in term.aliases
        )
        modifier_score = modifier_match_score(modifier_terms, term.aliases)

        final_score = max(
            hierarchy,
            exact,
            0.5 * fuzzy + 0.3 * bm25 + 0.2 * token_score,
            0.75 * fuzzy + 0.25 * token_score,
        )
        if exact:
            final_score = max(final_score, 0.96)

        # Detect fuzzy/BM25 hits supported only by direction, laterality, or
        # generic structure words, with no shared identifying content word.
        weak_only_match = False
        if not exact and not hierarchy and (fuzzy or bm25):
            matched_query = str(state.get("matched_query") or "")
            query_content = self._content_tokens(query) | self._content_tokens(matched_query)
            if query_content:
                alias_content: set[str] = set()
                alias_tokens: set[str] = set()
                for alias in term.aliases:
                    alias_content |= self._content_tokens(alias)
                    alias_tokens |= set(tokenize(alias, config=self.config))
                if not self._content_overlap(query_content, alias_content):
                    query_tokens = set(tokenize(query, config=self.config)) | set(
                        tokenize(matched_query, config=self.config)
                    )
                    overlap = query_tokens & alias_tokens
                    weak_only_match = bool(overlap and overlap <= self._noncontent_tokens)

        # Rank using only *effective* modifiers: genuine subdivision words
        # (core, shell, magnocellular, limb, ...) plus positional words that
        # resolve to a real candidate (see _compute_resolvable_positional).  A
        # non-resolvable direction word ("posterior insular area") neither
        # rewards nor penalises, so the correct parent can surface instead of an
        # unrelated same-direction structure.
        effective = self._effective_modifiers(modifier_terms)
        if effective:
            eff_score = modifier_match_score(effective, term.aliases)
            if eff_score > 0:
                final_score = min(final_score + 0.12 * eff_score, 1.0)
            else:
                final_score = min(final_score * 0.88, 0.88)
        # Apply specificity penalty only to fuzzy/bm25 matches that lack an
        # exact match.  Exact matches and pure hierarchy_parent entries are
        # exempt: the former because the query named the alias directly; the
        # latter because its promoted score already incorporates the children's
        # penalised scores.
        if not exact and (fuzzy or bm25):
            final_score *= self._specificity_penalty(query, modifier_terms, term)

        # Area / cell-group identifier mismatch: if both the query and the
        # candidate carry numeric area identifiers (e.g. cingulate "area 23c"
        # vs "area 5", or the "A1" vs "A8" cell groups) and none are compatible
        # (same alpha prefix + numeric core, ignoring subdivision suffix), they
        # name different parcels.  Penalise so a bare word overlap cannot
        # promote the wrong numbered area above its generic parent.  Subdivisions
        # such as "6a"/"3a" remain compatible with their parent area "6"/"3".
        # A matching identifier gets a small boost so "V3A" can outrank a
        # generic visual-cortex parent that lacks the code.
        if not exact:
            matched_query = str(state.get("matched_query") or "")
            query_ids = set(self._area_ids_from_text(query)) | set(
                self._area_ids_from_text(matched_query))
            cand_ids = set(self._term_area_ids(term_index, term))
            if query_ids and cand_ids:
                if _area_ids_compatible(query_ids, cand_ids):
                    # Boost only for *coded* ids (v3a, a8, op1, …).  Bare
                    # digits ("2", "3") are too common (layers 2-3, area 3) and
                    # must not inflate unrelated layer/subdivision hits.
                    q_coded = [
                        p for t in query_ids
                        if (p := _parse_area_id(t)) and p[0]
                    ]
                    c_coded = [
                        p for t in cand_ids
                        if (p := _parse_area_id(t)) and p[0]
                    ]
                    if q_coded and c_coded and any(q == c for q in q_coded for c in c_coded):
                        final_score = min(final_score + 0.08, 1.0)
                else:
                    final_score *= 0.40

        # Structure-class mismatch (tract↔nucleus, nerve↔ventricle, organ↔
        # nucleus, sulcus↔commissure, …): compare the *head* class of the query
        # with the head class of the candidate's primary name.  Demote so a
        # same-class sibling (e.g. ``olfactory tract`` for a tract query) can
        # surface above ``nucleus of … tract``.
        if not exact:
            q_toks = tokenize(query, keep_stopwords=True, config=self.config)
            matched_query = str(state.get("matched_query") or "")
            if matched_query:
                # Prefer the matched variant's token order when available.
                q_toks = tokenize(matched_query, keep_stopwords=True, config=self.config)
            c_toks = tokenize(term.name, keep_stopwords=True, config=self.config)
            if _structure_class_conflict(q_toks, c_toks):
                final_score *= 0.50
            q_content = self._content_tokens(query) | self._content_tokens(matched_query)
            c_content: set[str] = set()
            for alias in term.aliases:
                c_content |= self._content_tokens(alias)
            if _distinguishing_affix_mismatch(q_content, c_content):
                final_score *= 0.62

        # Keep weak-only matches (no shared identifying content word — only a
        # direction/laterality/generic token overlaps) well below any candidate
        # that shares a real content word, so a structurally-related parent can
        # surface instead of an unrelated same-direction structure.
        if weak_only_match:
            final_score = min(final_score, 0.38)

        return final_score, modifier_score

    def _fuzzy_candidates(
        self, variants: list[str], limit: int
    ) -> list[tuple[int, float, str, str]]:
        best_by_term: dict[int, tuple[float, str, str]] = {}
        for variant in variants:
            query_tokens = tokenize(variant, config=self.config)
            entry_indexes = self._entry_indexes_for_tokens(
                query_tokens, rarest_limit=2, combine="intersection"
            )
            if not entry_indexes and len(normalize_text(variant)) > 5:
                entry_indexes = range(len(self.alias_entries))

            for entry_index in entry_indexes:
                entry = self.alias_entries[entry_index]
                score = string_similarity(variant, entry.alias)
                if score < 0.45:
                    continue
                previous = best_by_term.get(entry.term_index)
                if previous is None or score > previous[0]:
                    best_by_term[entry.term_index] = (score, entry.alias, variant)

        ranked = sorted(best_by_term.items(), key=lambda item: item[1][0], reverse=True)
        return [(term_index, score, alias, matched_query) for term_index, (score, alias, matched_query) in ranked[:limit]]

    def _bm25_candidates(
        self, variants: list[str], limit: int
    ) -> list[tuple[int, float, str, str]]:
        best_by_term: dict[int, tuple[float, str, str]] = {}
        total_docs = max(len(self.alias_entries), 1)
        k1 = 1.5
        b = 0.75

        for variant in variants:
            query_tokens = tokenize(variant, config=self.config)
            if not query_tokens:
                continue
            query_counts = Counter(query_tokens)
            entry_indexes = self._entry_indexes_for_tokens(query_tokens)

            for entry_index in entry_indexes:
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
                normalized_score = raw_score / (raw_score + 4.0)
                previous = best_by_term.get(entry.term_index)
                if previous is None or normalized_score > previous[0]:
                    best_by_term[entry.term_index] = (normalized_score, entry.alias, variant)

        ranked = sorted(best_by_term.items(), key=lambda item: item[1][0], reverse=True)
        return [(term_index, score, alias, matched_query) for term_index, (score, alias, matched_query) in ranked[:limit]]

    def _entry_indexes_for_tokens(
        self,
        tokens: list[str],
        rarest_limit: int | None = None,
        *,
        combine: str = "union",
    ) -> Iterable[int]:
        search_tokens = list(dict.fromkeys(tokens))
        if rarest_limit is not None and len(search_tokens) > rarest_limit:
            search_tokens.sort(key=lambda token: self._bm25_doc_freq.get(token, 0))
            search_tokens = search_tokens[:rarest_limit]

        if not search_tokens:
            return set()

        if combine == "intersection":
            entry_indexes = self.token_to_entries.get(search_tokens[0], set()).copy()
            for token in search_tokens[1:]:
                entry_indexes &= self.token_to_entries.get(token, set())
            return entry_indexes

        entry_indexes: set[int] = set()
        for token in search_tokens:
            entry_indexes.update(self.token_to_entries.get(token, set()))
        return entry_indexes

    def _promote_common_parents(
        self,
        query: str,
        modifier_terms: list[str],
        candidate_state: dict[int, dict[str, object]],
        prelim_scores: dict[int, float],
    ) -> None:
        """Promote a shared parent when 2+ sibling candidates exist.

        Uses *prelim_scores* (pass-1 final scores, already penalised) rather
        than raw method scores so the parent cannot outscore a directly matched
        child purely due to an inflated raw score.
        """
        # An *effective* modifier (a subdivision word, or a direction that
        # resolves to a specific child) names a particular child and blocks
        # parent promotion.  A non-resolvable positional word ("posterior
        # insular area") does not: the direction points at no specific child, so
        # promoting the common parent is safe (and usually correct).
        if self._effective_modifiers(modifier_terms):
            return

        # Query carries only non-resolvable positional words: offer the parent
        # as a *fallback* that never outranks a well-matching child.
        positional_only = bool(modifier_terms)

        query_tokens = set(tokenize(query, config=self.config))
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
            parent_token_score = max(
                token_jaccard(query_tokens, tokenize(alias, config=self.config))
                for alias in parent.aliases
            )
            if parent_token_score <= 0:
                continue

            # Use pass-1 final scores (penalised) so the parent's ceiling
            # reflects the actual quality of its children's matches.
            child_scores = [
                prelim_scores.get(child_index, float(candidate_state[child_index]["best_method_score"]))
                for child_index in child_indexes
            ]
            best_child = max(child_scores)
            if positional_only:
                # The query names a direction but no subdivision word.  Offer the
                # parent only as a *fallback* that never outranks a child which
                # actually matches (so "substantia nigra (lateral part)" keeps
                # its "lateral division" child, while "posterior insular area"
                # can still fall back to "insular lobe" when every child is a
                # weak match).
                promoted_score = max(best_child - 0.03, 0.0)
            elif 0.62 <= best_child < 0.82:
                promoted_score = max(best_child - 0.03, 0.0)
            else:
                promoted_score = min(best_child + 0.08, 0.97)
            self._add_candidate(
                candidate_state,
                parent_index,
                method="hierarchy_parent",
                score=promoted_score,
                alias=parent.name,
                matched_query=query,
                hierarchy_reason=f"common_parent_of_{len(child_indexes)}_candidates",
            )

    @staticmethod
    def _stem_match(left: str, right: str) -> bool:
        """Match identifying words across common morphological variants."""
        if left == right:
            return True
        shorter, longer = (left, right) if len(left) <= len(right) else (right, left)
        if len(shorter) >= 5 and longer.startswith(shorter):
            return True
        if len(shorter) >= 6:
            common = 0
            for left_char, right_char in zip(left, right):
                if left_char != right_char:
                    break
                common += 1
            if common >= len(shorter) - 2 and common >= 6:
                return True
        return False

    def _content_overlap(self, query_tokens: set[str], alias_tokens: set[str]) -> bool:
        """Return whether query and alias share an identifying word."""
        if query_tokens & alias_tokens:
            return True
        return any(
            self._stem_match(query_token, alias_token)
            for query_token in query_tokens
            for alias_token in alias_tokens
        )

    def _compute_resolvable_positional(
        self,
        query: str,
        modifier_terms: list[str],
        candidate_state: dict[int, dict[str, object]],
    ) -> frozenset[str]:
        positional_query = {
            tok
            for term in modifier_terms
            for tok in normalize_text(term).split()
            if tok in POSITIONAL_WORDS
        }
        if not positional_query:
            return frozenset()

        query_content = self._content_tokens(query)
        resolvable: set[str] = set()
        for term_index in candidate_state:
            term = self.terms[term_index]
            alias_content: set[str] = set()
            alias_tokens: set[str] = set()
            for alias in term.aliases:
                alias_content |= self._content_tokens(alias)
                alias_tokens |= set(tokenize(alias, config=self.config))
            # Only candidates that share an identifying content word with the
            # query count: a same-direction but unrelated structure must not make
            # the direction "resolvable".
            if not self._content_overlap(query_content, alias_content):
                continue
            resolvable |= positional_query & alias_tokens
        return frozenset(resolvable)

    def _effective_modifiers(self, modifier_terms: list[str]) -> list[str]:
        """Modifiers that should drive ranking: substantive subdivision words
        plus positional words that resolve to a specific candidate."""
        resolvable = getattr(self, "_resolvable_positional", frozenset())
        effective: list[str] = []
        for term in modifier_terms:
            toks = normalize_text(term).split()
            if any(t not in POSITIONAL_WORDS for t in toks):
                effective.append(term)          # contains a real subdivision word
            elif all(t in resolvable for t in toks) and toks:
                effective.append(term)          # purely positional but resolvable
        return effective

    @staticmethod
    def _area_ids_from_text(text: str) -> frozenset[str]:
        """Extract area / cell-group identifier tokens (e.g. 23c, a8, v3a, 5)."""
        return frozenset(
            tok for tok in normalize_text(text).split() if _AREA_ID_RE.match(tok)
        )

    def _term_area_ids(self, term_index: int, term: HOMBATerm) -> frozenset[str]:
        cached = self._area_id_cache.get(term_index)
        if cached is not None:
            return cached
        ids: set[str] = set()
        for alias in term.aliases:
            ids |= self._area_ids_from_text(alias)
        result = frozenset(ids)
        self._area_id_cache[term_index] = result
        return result

    def _content_tokens(self, text: str) -> frozenset[str]:
        """Return tokens that identify a structure rather than its direction."""
        cached = self._content_cache.get(text)
        if cached is not None:
            return cached
        content = frozenset(
            token
            for token in tokenize(text, config=self.config)
            if token not in self._noncontent_tokens
        )
        self._content_cache[text] = content
        return content

    def _specificity_penalty(self, query: str, modifier_terms: list[str], term: HOMBATerm) -> float:
        if self._effective_modifiers(modifier_terms) or not term.parent_id:
            return 1.0

        query_specificity = specificity_terms(query, self.config)
        candidate_specificity: set[str] = set()
        for alias in term.aliases:
            candidate_specificity.update(specificity_terms(alias, self.config))

        extra_specificity = candidate_specificity - query_specificity
        if not extra_specificity:
            return 1.0

        return 0.86

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
        method_scores = state["method_scores"]
        method_scores[method] = max(method_scores.get(method, 0.0), score)
        if score > state["best_method_score"]:
            state["best_method_score"] = score
            state["matched_alias"] = alias
            state["matched_query"] = matched_query
        if hierarchy_reason:
            state["hierarchy_reason"] = hierarchy_reason


def load_generator(homba_csv_path: str | Path) -> RosettaCandidateGenerator:
    return RosettaCandidateGenerator(homba_csv_path)
