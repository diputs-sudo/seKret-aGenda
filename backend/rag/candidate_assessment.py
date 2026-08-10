"""Candidate assessment and relevance gating."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any

from .mechanism import Mechanism


class Relationship(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    QUALIFIES = "QUALIFIES"
    BACKGROUND = "BACKGROUND"
    IRRELEVANT = "IRRELEVANT"


@dataclass(frozen=True)
class CandidateAssessment:
    card_id: str
    relevance_score: float
    topic_match: float
    mechanism_match: float
    warrant_match: float
    relationship: Relationship
    supports_claim: bool
    contradicts_claim: bool
    evidence_strength: float
    confidence: float
    rejection_reason: str | None
    matched_concepts: list[str]
    missing_concepts: list[str]
    match_locations: dict[str, list[str]]
    reasons: list[str]
    query_mechanism: Mechanism
    card_mechanism: Mechanism

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["relationship"] = self.relationship.value
        data["query_mechanism"] = self.query_mechanism.to_dict()
        data["card_mechanism"] = self.card_mechanism.to_dict()
        return data


class RelevanceGate:
    def __init__(
        self,
        min_relevance: float = 0.22,
        min_confidence: float = 0.2,
        allow_background: bool = False,
    ):
        self.min_relevance = min_relevance
        self.min_confidence = min_confidence
        self.allow_background = allow_background

    def split(
        self, cards: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        accepted = []
        rejected = []
        min_relevance = _dynamic_min_relevance(cards, self.min_relevance)
        min_confidence = _dynamic_min_confidence(cards, self.min_confidence)
        for card in cards:
            assessment = card.get("candidate_assessment") or {}
            relationship = assessment.get("relationship")
            relevance = float(assessment.get("relevance_score") or 0)
            confidence = float(assessment.get("confidence") or 0)
            rejection_reason = assessment.get("rejection_reason")
            gate_reason = _gate_rejection_reason(
                relationship=relationship,
                rejection_reason=rejection_reason,
                relevance=relevance,
                confidence=confidence,
                min_relevance=min_relevance,
                min_confidence=min_confidence,
                allow_background=self.allow_background,
            )
            if gate_reason:
                rejected.append(_with_rejection_reason(card, gate_reason))
            else:
                accepted.append(card)
        return accepted, rejected


def classify_relationship(
    *,
    query_mechanism: Mechanism,
    card_mechanism: Mechanism,
    topic_match: float,
    mechanism_match: float,
    warrant_match: float,
) -> Relationship:
    direct_match = _direct_mechanism_match(query_mechanism, card_mechanism, mechanism_match)
    partial_match = _partial_mechanism_match(
        query_mechanism, card_mechanism, mechanism_match
    )
    polarity_match = _polarity_overlap(query_mechanism, card_mechanism)

    if mechanism_match < 0.08 and topic_match < 0.15:
        return Relationship.IRRELEVANT
    if polarity_match and _opposes_claim(query_mechanism, card_mechanism):
        return Relationship.CONTRADICTS
    if polarity_match and _supports_claim(query_mechanism, card_mechanism):
        return Relationship.SUPPORTS
    if not direct_match and not partial_match:
        if mechanism_match >= 0.08 or topic_match >= 0.18:
            return Relationship.BACKGROUND
        return Relationship.IRRELEVANT
    if not direct_match:
        if warrant_match >= 0.15 or mechanism_match >= 0.45:
            return Relationship.QUALIFIES
        return Relationship.BACKGROUND
    if _opposes_claim(query_mechanism, card_mechanism):
        return Relationship.CONTRADICTS
    if _supports_claim(query_mechanism, card_mechanism):
        return Relationship.SUPPORTS
    if warrant_match >= 0.15 or mechanism_match >= 0.45:
        return Relationship.QUALIFIES
    return Relationship.BACKGROUND


def rejection_reason(
    *,
    relationship: Relationship,
    relevance_score: float,
    mechanism_match: float,
    same_section_only: bool,
) -> str | None:
    if same_section_only:
        return "matches section but not card mechanism"
    if relationship == Relationship.IRRELEVANT:
        return "topic and mechanism mismatch"
    if relationship == Relationship.BACKGROUND:
        return "background topic overlap without usable mechanism match"
    if relevance_score < 0.18:
        return "low relevance score"
    return None


def confidence_score(
    *,
    relevance_score: float,
    mechanism_match: float,
    warrant_match: float,
    evidence_strength: float,
    relationship: Relationship,
) -> float:
    confidence = (
        relevance_score * 0.35
        + mechanism_match * 0.3
        + warrant_match * 0.2
        + evidence_strength * 0.15
    )
    if relationship == Relationship.IRRELEVANT:
        confidence = min(confidence, 0.2)
    elif relationship == Relationship.BACKGROUND:
        confidence = min(confidence, 0.55)
    return round(max(0.0, min(1.0, confidence)), 3)


def _opposes_claim(query_mechanism: Mechanism, card_mechanism: Mechanism) -> bool:
    if query_mechanism.polarity == 0 or card_mechanism.polarity == 0:
        return False
    return query_mechanism.polarity != card_mechanism.polarity


def _supports_claim(query_mechanism: Mechanism, card_mechanism: Mechanism) -> bool:
    if query_mechanism.polarity == 0 or card_mechanism.polarity == 0:
        return False
    return query_mechanism.polarity == card_mechanism.polarity


def _polarity_overlap(query_mechanism: Mechanism, card_mechanism: Mechanism) -> bool:
    query_core = (
        query_mechanism.cause_groups
        | query_mechanism.effect_groups
        | query_mechanism.object_groups
    ) - query_mechanism.generic_terms
    card_core = (
        card_mechanism.cause_groups
        | card_mechanism.effect_groups
        | card_mechanism.object_groups
    ) - card_mechanism.generic_terms
    return bool(query_core & card_core)


def _direct_mechanism_match(
    query_mechanism: Mechanism,
    card_mechanism: Mechanism,
    mechanism_match: float,
) -> bool:
    if mechanism_match < 0.25:
        return False
    actor_match = (
        not query_mechanism.actor_groups
        or bool(query_mechanism.actor_groups & card_mechanism.actor_groups)
    )
    effect_match = (
        not query_mechanism.effect_groups
        or bool(
            query_mechanism.effect_groups
            & (card_mechanism.effect_groups | card_mechanism.object_groups)
        )
    )
    cause_match = (
        not query_mechanism.cause_groups
        or bool(
            query_mechanism.cause_groups
            & (card_mechanism.cause_groups | card_mechanism.object_groups)
        )
    )
    return actor_match and effect_match and (cause_match or mechanism_match >= 0.45)


def _partial_mechanism_match(
    query_mechanism: Mechanism,
    card_mechanism: Mechanism,
    mechanism_match: float,
) -> bool:
    if mechanism_match < 0.12:
        return False
    cause_match = bool(
        query_mechanism.cause_groups
        & (card_mechanism.cause_groups | card_mechanism.object_groups)
    )
    effect_match = bool(
        query_mechanism.effect_groups
        & (card_mechanism.effect_groups | card_mechanism.object_groups)
    )
    return cause_match or effect_match


def _gate_rejection_reason(
    *,
    relationship: str | None,
    rejection_reason: str | None,
    relevance: float,
    confidence: float,
    min_relevance: float,
    min_confidence: float,
    allow_background: bool,
) -> str | None:
    if rejection_reason:
        return rejection_reason
    if relationship == Relationship.IRRELEVANT.value:
        return "topic and mechanism mismatch"
    if relationship == Relationship.BACKGROUND.value and not allow_background:
        return "background evidence excluded by gate"
    if relevance < min_relevance:
        return "low relevance score"
    if confidence < min_confidence:
        return "low confidence"
    return None


def _dynamic_min_relevance(cards: list[dict[str, Any]], floor: float) -> float:
    scores = sorted(
        (float((card.get("candidate_assessment") or {}).get("relevance_score") or 0) for card in cards),
        reverse=True,
    )
    if not scores:
        return floor
    top = scores[0]
    if top >= 0.75:
        return max(floor, top * 0.35)
    if top >= 0.45:
        return max(floor, top * 0.45)
    return max(0.16, min(floor, top * 0.65))


def _dynamic_min_confidence(cards: list[dict[str, Any]], floor: float) -> float:
    confidences = sorted(
        (float((card.get("candidate_assessment") or {}).get("confidence") or 0) for card in cards),
        reverse=True,
    )
    if not confidences:
        return floor
    top = confidences[0]
    if top >= 0.7:
        return max(floor, top * 0.35)
    return max(0.16, min(floor, top * 0.55))


def _with_rejection_reason(card: dict[str, Any], reason: str) -> dict[str, Any]:
    enriched = dict(card)
    assessment = dict(enriched.get("candidate_assessment") or {})
    if not assessment.get("rejection_reason"):
        assessment["rejection_reason"] = reason
        reasons = list(assessment.get("reasons") or [])
        reasons.append(f"rejected: {reason}")
        assessment["reasons"] = reasons
    enriched["candidate_assessment"] = assessment
    enriched["reranker_assessment"] = assessment
    return enriched
