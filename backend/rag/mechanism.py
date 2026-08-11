"""Topic-agnostic mechanism parsing for debate retrieval.

The parser intentionally avoids topic-specific dictionaries. It derives
concepts from the query/card text itself so the retrieval system can work on
new resolutions, authors, and backfiles without code changes.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .relevance import SEMANTIC_STOPWORDS, STOPWORDS, _terms

# Deliberately empty: semantic classes must be learned from the corpus or supplied
# by configuration later, not hard-coded for one topic/test packet.
SEMANTIC_MECHANISMS: dict[str, set[str]] = {}

POSITIVE_CAUSAL_TERMS = {
    "cause",
    "causes",
    "caused",
    "create",
    "creates",
    "created",
    "drive",
    "drives",
    "fuel",
    "fuels",
    "increase",
    "increases",
    "lead",
    "leads",
    "result",
    "results",
    "worsen",
    "worsens",
}

NEGATIVE_CAUSAL_TERMS = {
    "avoid",
    "avoids",
    "decrease",
    "decreases",
    "defuse",
    "defuses",
    "lower",
    "lowers",
    "mitigate",
    "mitigates",
    "prevent",
    "prevents",
    "reduce",
    "reduces",
    "stabilize",
    "stabilizes",
    "stop",
    "stops",
}

BECAUSE_RE = re.compile(r"\bbecause\s+(?:of\s+)?(.+)$", re.IGNORECASE)
CAUSE_RE = re.compile(
    r"(.+?)\b(?:causes?|creates?|drives?|fuels?|leads?\s+to|results?\s+in|"
    r"increases?|reduces?|lowers?|prevents?|stops?|defuses?|mitigates?|"
    r"stabilizes?|worsens?)\b(.+)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Mechanism:
    raw_text: str
    actor_groups: set[str]
    cause_groups: set[str]
    effect_groups: set[str]
    object_groups: set[str]
    phrase_concepts: set[str]
    ignored_stopwords: set[str]
    generic_terms: set[str]
    polarity: int
    terms: set[str]

    def to_dict(self) -> dict[str, object]:
        data = asdict(self)
        for key in (
            "actor_groups",
            "cause_groups",
            "effect_groups",
            "object_groups",
            "phrase_concepts",
            "ignored_stopwords",
            "generic_terms",
            "terms",
        ):
            data[key] = sorted(data[key])
        return data


def parse_mechanism(text: str) -> Mechanism:
    raw_terms = _surface_terms(text)
    normalized_terms = _normalized_terms(text)
    phrase_concepts = extract_phrase_concepts(text)
    actor_terms, cause_terms, effect_terms = _split_mechanism_terms(text)

    actor_groups = _normalized_terms_from_terms(actor_terms)
    cause_groups = _normalized_terms_from_terms(cause_terms)
    effect_groups = _normalized_terms_from_terms(effect_terms)
    object_groups = normalized_terms | phrase_concepts
    object_groups.update(_semantic_classes(normalized_terms | phrase_concepts))
    actor_groups.update(_semantic_classes(actor_groups))
    cause_groups.update(_semantic_classes(cause_groups))
    effect_groups.update(_semantic_classes(effect_groups))

    return Mechanism(
        raw_text=text,
        actor_groups=actor_groups,
        cause_groups=cause_groups,
        effect_groups=effect_groups,
        object_groups=object_groups,
        phrase_concepts=phrase_concepts,
        ignored_stopwords=ignored_stopwords(text),
        generic_terms={term for term in normalized_terms if _is_generic_term(term)},
        polarity=_polarity(text, raw_terms),
        terms=normalized_terms,
    )


def mechanism_match(query: Mechanism, card: Mechanism) -> float:
    actor = _overlap_score(query.actor_groups, card.actor_groups)
    cause = _overlap_score(query.cause_groups, card.cause_groups)
    effect = _overlap_score(query.effect_groups, card.effect_groups)
    objects = _overlap_score(query.object_groups, card.object_groups)
    phrases = _overlap_score(query.phrase_concepts, card.phrase_concepts)

    if not query.cause_groups:
        cause = objects
    if not query.effect_groups:
        effect = objects

    generic_penalty = 0.25 if _generic_only_match(query, card) else 1.0
    return round(
        (actor * 0.15 + cause * 0.3 + effect * 0.35 + phrases * 0.15 + objects * 0.05)
        * generic_penalty,
        3,
    )


def mechanism_concepts(
    query: Mechanism, card: Mechanism
) -> tuple[list[str], list[str]]:
    """Return user-facing matched and missing mechanism concepts."""
    matched: set[str] = set()
    missing: set[str] = set()
    card_all = (
        card.actor_groups
        | card.cause_groups
        | card.effect_groups
        | card.object_groups
        | card.phrase_concepts
    )

    query_concepts = (
        query.actor_groups
        | query.cause_groups
        | query.effect_groups
        | query.phrase_concepts
    )
    if not query_concepts:
        query_concepts = query.object_groups

    for concept in query_concepts:
        (matched if concept in card_all else missing).add(concept)

    return sorted(matched), sorted(missing)


def extract_phrase_concepts(text: str) -> set[str]:
    raw_tokens = [
        token.lower().replace("-", "_")
        for token in _tokenize(text)
        if token
        and token not in STOPWORDS
        and token not in SEMANTIC_STOPWORDS
    ]
    tokens = [_canonical_term(token) for token in raw_tokens]
    tokens = [
        token
        for token in tokens
        if token
        and token not in STOPWORDS
        and token not in SEMANTIC_STOPWORDS
    ]
    phrases: set[str] = set()
    for size in (2, 3):
        for index in range(0, len(tokens) - size + 1):
            window = tokens[index : index + size]
            if any(_is_generic_term(token) for token in window):
                continue
            phrases.add("_".join(window))
    for size in (2, 3):
        for index in range(0, len(raw_tokens) - size + 1):
            window = raw_tokens[index : index + size]
            if any(_is_generic_term(token) for token in window):
                continue
            phrases.add("_".join(window))
    phrases.update(_semantic_classes(set(tokens) | phrases))
    return phrases


def ignored_stopwords(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9']+", text)
        if token.lower() in STOPWORDS
    }


def _split_mechanism_terms(text: str) -> tuple[set[str], set[str], set[str]]:
    because_match = BECAUSE_RE.search(text)
    if because_match:
        before = text[: because_match.start()]
        after = because_match.group(1)
        actor_terms = set(_ordered_terms(before)[:1])
        return actor_terms, _terms(after), _terms(before) - actor_terms

    cause_match = CAUSE_RE.search(text)
    if cause_match:
        left = cause_match.group(1)
        right = cause_match.group(2)
        return _first_clause_terms(left), _terms(left), _terms(right)

    terms = _terms(text)
    return _first_clause_terms(text), set(), terms


def _first_clause_terms(text: str) -> set[str]:
    clause = re.split(r"\b(?:causes?|creates?|drives?|fuels?|leads?|results?|"
                      r"increases?|reduces?|lowers?|prevents?|stops?|defuses?|"
                      r"mitigates?|stabilizes?|worsens?|because)\b",
                      text,
                      maxsplit=1,
                      flags=re.IGNORECASE)[0]
    terms = _ordered_terms(clause)
    return set(terms[:2])


def _normalized_terms(text: str) -> set[str]:
    terms = _normalized_terms_from_terms(_terms(text))
    terms.update(_semantic_classes(terms))
    return terms


def _normalized_terms_from_terms(terms: set[str]) -> set[str]:
    normalized = {term.lower().replace("-", "_") for term in terms}
    normalized.update(_canonical_term(term) for term in terms)
    return {term for term in normalized if term}


def _canonical_term(term: str) -> str:
    token = term.lower().replace("-", "_").strip("_")
    if len(token) <= 3:
        return token
    for suffix in ("ization", "isation", "ations", "ments", "ition"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[: -len(suffix)]
    if token.endswith("ation") and len(token) > 8:
        return token[:-3]
    for suffix in ("ing", "ers", "ies", "ied", "ed", "es", "s"):
        if token.endswith(suffix) and len(token) > len(suffix) + 3:
            return token[: -len(suffix)]
    return token


def _semantic_classes(terms: set[str]) -> set[str]:
    classes = set()
    for concept, aliases in SEMANTIC_MECHANISMS.items():
        canonical_aliases = {_canonical_term(alias) for alias in aliases}
        canonical_aliases.update(alias.replace("-", "_") for alias in aliases)
        if terms & canonical_aliases:
            classes.add(concept)
    return classes


def _polarity(text: str, terms: set[str]) -> int:
    canonical_terms = {_canonical_term(term) for term in terms}
    positive = bool(canonical_terms & {_canonical_term(term) for term in POSITIVE_CAUSAL_TERMS})
    negative = bool(canonical_terms & {_canonical_term(term) for term in NEGATIVE_CAUSAL_TERMS})
    if negative and not positive:
        return -1
    if positive and not negative:
        return 1
    if negative and positive:
        return -1
    if BECAUSE_RE.search(text):
        return 1
    return 0


def _overlap_score(query_values: set[str], card_values: set[str]) -> float:
    if not query_values:
        return 0.0
    return len(query_values & card_values) / len(query_values)


def _generic_only_match(query: Mechanism, card: Mechanism) -> bool:
    query_specific = (
        query.actor_groups
        | query.cause_groups
        | query.effect_groups
        | query.object_groups
        | query.phrase_concepts
    ) - query.generic_terms
    card_specific = (
        card.actor_groups
        | card.cause_groups
        | card.effect_groups
        | card.object_groups
        | card.phrase_concepts
    ) - card.generic_terms
    if query_specific & card_specific:
        return False
    return bool(query.generic_terms & card.generic_terms)


def _is_generic_term(term: str) -> bool:
    if len(term) <= 2:
        return True
    if term.isdigit():
        return True
    if term in {"artificial_intelligence", "ai"}:
        return True
    return term in STOPWORDS or term in SEMANTIC_STOPWORDS


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text.lower())


def _surface_terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?", text)
        if token.lower() not in STOPWORDS
    }


def _ordered_terms(text: str) -> list[str]:
    terms = []
    for token in re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?", text):
        lowered = token.lower()
        if lowered in STOPWORDS or lowered in SEMANTIC_STOPWORDS:
            continue
        terms.append(lowered)
    return terms
