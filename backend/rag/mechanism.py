"""Deterministic causal/mechanism parsing for debate retrieval."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from .relevance import QUERY_EXPANSIONS, STOPWORDS, _terms

ACTOR_GROUPS = {
    "ai": {"ai", "artificial", "intelligence", "algorithm", "autonomous"},
    "human": {"human", "humans", "analyst", "analysts", "decision-makers", "judgment"},
    "state": {"state", "states", "local", "nevada", "missouri"},
    "federal": {"federal", "congress", "ftc", "national"},
    "company": {"company", "companies", "corporation", "corporations", "operators"},
}

MECHANISM_GROUPS = {
    "ai_automation": {
        "ai_automation",
        "automation",
        "automated",
        "autonomous",
        "algorithm",
        "decision",
        "decision-making",
    },
    "automation": {
        "automation",
        "automated",
        "autonomous",
        "algorithm",
        "decision",
        "decision-making",
    },
    "conflict_escalation": {
        "conflict_escalation",
        "escalate",
        "escalates",
        "escalation",
        "aggression",
        "conflict",
        "war",
        "launch",
        "warning",
        "alarms",
        "alarm",
    },
    "human_control": {
        "human_control",
        "human_oversight",
        "human_decision_making",
        "oversight",
        "human",
        "humans",
        "judgment",
        "decision-makers",
        "decision-making",
    },
    "government_control": {"government_control", "government", "federal", "state"},
    "corporate_control": {"corporate_control", "corporate", "corporation"},
    "risk_confidence": {
        "risk",
        "cautious",
        "confidence",
        "uncertainty",
        "limited",
        "false",
        "alarms",
    },
    "state_regulation": {
        "state_regulation",
        "regulation",
        "regulations",
        "regulatory",
        "state",
        "states",
    },
    "federal_regulation": {
        "federal_regulation",
        "regulation",
        "regulations",
        "regulatory",
        "act",
        "law",
        "laws",
        "compliance",
        "ftc",
        "congress",
    },
    "revenue": {"revenue", "profit", "money", "bottom", "line", "market"},
    "sports_betting": {"sports_betting", "gambling", "betting", "sportsbook", "casino", "lottery"},
    "black_market": {"black_market", "illegal", "offshore"},
    "cybersecurity": {"cybersecurity", "cyber", "hackers", "breach"},
    "encryption": {"quantum_encryption", "encryption", "data", "keys"},
    "quantum": {"quantum_encryption", "quantum", "computing", "computer", "computers"},
    "federalism": {"federalism", "states", "state", "federal", "power"},
    "military_decision_making": {
        "military_decision_making",
        "military",
        "war",
        "decision",
        "decision-making",
    },
}

PHRASE_CONCEPTS = {
    "human_control": (
        "human control",
        "human in the loop",
        "humans in the loop",
        "human judgment",
    ),
    "human_oversight": ("human oversight", "human review"),
    "human_decision_making": (
        "human decision-making",
        "human decision making",
        "human decisions",
        "decision-makers",
    ),
    "ai_automation": (
        "ai automation",
        "automated ai",
        "autonomous ai",
        "artificial intelligence automation",
    ),
    "ai_escalation": ("ai escalation", "ai escalates", "ai escalating"),
    "conflict_escalation": (
        "conflict escalation",
        "military escalation",
        "war escalation",
        "unintended escalation",
    ),
    "military_decision_making": (
        "military decision-making",
        "military decision making",
        "military ai",
        "military command",
    ),
    "sports_betting": ("sports betting", "sportsbook", "sports book"),
    "black_market": ("black market", "illegal market", "offshore betting"),
    "state_regulation": ("state regulation", "state regulations", "state laws"),
    "federal_regulation": (
        "federal regulation",
        "federal regulations",
        "federal framework",
        "federal law",
    ),
    "government_control": ("government control", "federal control", "state control"),
    "corporate_control": ("corporate control", "company control"),
    "quantum_encryption": ("quantum encryption", "quantum breaks encryption"),
    "machine_learning": ("machine learning",),
    "slot_machine": ("slot machine", "slot machines"),
}

PHRASE_ALIASES = {
    "human_oversight": "human_control",
    "human_decision_making": "human_control",
    "ai_escalation": "conflict_escalation",
    "machine_learning": "ai_automation",
}

GENERIC_CONCEPTS = {
    "risk",
    "system",
    "systems",
    "technology",
    "state",
    "states",
    "policy",
    "machine",
    "control",
    "market",
    "data",
}

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
    "escalate",
    "escalates",
    "worsen",
    "worsens",
    "risk",
}

NEGATIVE_CAUSAL_TERMS = {
    "reduce",
    "reduces",
    "lower",
    "lowers",
    "decrease",
    "decreases",
    "prevent",
    "prevents",
    "stop",
    "stops",
    "defuse",
    "defuses",
    "mitigate",
    "mitigates",
    "stabilize",
    "stabilizes",
    "control",
    "cautious",
    "confidence",
    "avoid",
    "avoids",
}

BECAUSE_RE = re.compile(r"\bbecause\s+(?:of\s+)?(.+)$", re.IGNORECASE)
CAUSE_RE = re.compile(
    r"(.+?)\b(?:causes?|creates?|drives?|fuels?|leads?\s+to|results?\s+in|"
    r"increases?|escalates?|reduces?|lowers?|prevents?|stops?|defuses?|"
    r"mitigates?|stabilizes?)\b(.+)",
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
    raw_terms = _terms(text)
    terms = _expanded_terms(text)
    phrase_concepts = extract_phrase_concepts(text)
    typed_terms = raw_terms | phrase_concepts
    actor_groups = _matching_groups(typed_terms, ACTOR_GROUPS)
    object_groups = _matching_groups(typed_terms, MECHANISM_GROUPS)
    object_groups.update(_concept_groups(phrase_concepts))
    cause_terms, effect_terms = _split_cause_effect_terms(text)
    cause_groups = _matching_groups(cause_terms | phrase_concepts, MECHANISM_GROUPS)
    effect_groups = _matching_groups(effect_terms | phrase_concepts, MECHANISM_GROUPS)

    if not cause_groups and "ai_automation" in object_groups:
        cause_groups.add("ai_automation")
    elif not cause_groups and "automation" in object_groups:
        cause_groups.add("automation")
    if not effect_groups:
        effect_groups.update(
            group
            for group in object_groups
            if group
            in {
                "conflict_escalation",
                "human_control",
                "risk_confidence",
                "revenue",
                "encryption",
            }
        )

    return Mechanism(
        raw_text=text,
        actor_groups=actor_groups,
        cause_groups=cause_groups,
        effect_groups=effect_groups,
        object_groups=object_groups,
        phrase_concepts=phrase_concepts,
        ignored_stopwords=ignored_stopwords(text),
        generic_terms=raw_terms & GENERIC_CONCEPTS,
        polarity=_polarity(raw_terms),
        terms=terms,
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

    generic_penalty = 0.15 if _generic_only_match(query, card) else 1.0
    return round(
        (actor * 0.2 + cause * 0.3 + effect * 0.35 + phrases * 0.1 + objects * 0.05)
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

    for group in query.actor_groups:
        (matched if group in card.actor_groups else missing).add(group)

    for group in query.cause_groups:
        (matched if group in card.cause_groups or group in card_all else missing).add(
            group
        )

    for group in query.effect_groups:
        (matched if group in card.effect_groups or group in card_all else missing).add(
            group
        )

    if not query.cause_groups and not query.effect_groups:
        for group in query.object_groups:
            (matched if group in card_all else missing).add(group)

    for concept in query.phrase_concepts:
        canonical = PHRASE_ALIASES.get(concept, concept)
        (matched if canonical in card_all or concept in card.phrase_concepts else missing).add(
            canonical
        )

    return sorted(matched), sorted(missing)


def extract_phrase_concepts(text: str) -> set[str]:
    normalized = _normalize_text(text)
    concepts = {
        concept
        for concept, phrases in PHRASE_CONCEPTS.items()
        if any(_phrase_in_text(phrase, normalized) for phrase in phrases)
    }
    return {PHRASE_ALIASES.get(concept, concept) for concept in concepts}


def ignored_stopwords(text: str) -> set[str]:
    return {token.lower() for token in re.findall(r"[A-Za-z0-9']+", text) if token.lower() in STOPWORDS}


def _split_cause_effect_terms(text: str) -> tuple[set[str], set[str]]:
    because_match = BECAUSE_RE.search(text)
    cause_terms = _terms(because_match.group(1)) if because_match else set()

    effect_terms: set[str] = set()
    cause_match = CAUSE_RE.search(text)
    if cause_match:
        left = _terms(cause_match.group(1))
        if not cause_terms:
            cause_terms = left
            effect_terms = _terms(cause_match.group(2))

    all_terms = _terms(text)
    for group_name, group_terms in MECHANISM_GROUPS.items():
        if all_terms & group_terms and group_name in {
            "conflict_escalation",
            "human_control",
            "risk_confidence",
        }:
            effect_terms.update(all_terms & group_terms)

    return cause_terms, effect_terms


def _expanded_terms(text: str) -> set[str]:
    terms = _terms(text)
    expanded = set(terms)
    for term in terms:
        expanded.update(QUERY_EXPANSIONS.get(term, set()))
    return expanded


def _matching_groups(
    terms: set[str],
    groups: dict[str, set[str]],
) -> set[str]:
    return {name for name, group_terms in groups.items() if terms & group_terms}


def _concept_groups(concepts: set[str]) -> set[str]:
    groups = set()
    for concept in concepts:
        for group_name, group_terms in MECHANISM_GROUPS.items():
            if concept in group_terms or concept == group_name:
                groups.add(group_name)
    return groups


def _polarity(terms: set[str]) -> int:
    negative = bool(terms & NEGATIVE_CAUSAL_TERMS)
    positive = bool(terms & POSITIVE_CAUSAL_TERMS)
    if negative and not positive:
        return -1
    if positive and not negative:
        return 1
    if negative and positive:
        return -1
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
    )
    card_specific = (
        card.actor_groups
        | card.cause_groups
        | card.effect_groups
        | card.object_groups
        | card.phrase_concepts
    )
    if query_specific & card_specific:
        return False
    return bool(query.generic_terms & card.generic_terms)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text.lower().replace("-", " ")).strip()


def _phrase_in_text(phrase: str, normalized_text: str) -> bool:
    normalized_phrase = _normalize_text(phrase)
    return re.search(rf"\b{re.escape(normalized_phrase)}\b", normalized_text) is not None
