"""Claim-card relationship classification for debate side routing."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from backend.rag.mechanism import extract_phrase_concepts, mechanism_match, parse_mechanism
from backend.rag.relevance import _highlight_text, _terms

from .model import ClaimRelationship, RelationshipResult

NEGATION_CUES = {
    "cannot",
    "doesn",
    "doesn't",
    "fail",
    "fails",
    "failed",
    "false",
    "no",
    "not",
    "prevent",
    "prevents",
    "reduce",
    "reduces",
    "wrong",
}
POSITIVE_DIRECTION_CUES = {
    "causes",
    "creates",
    "encourage",
    "encourages",
    "guarantee",
    "guarantees",
    "grow",
    "grows",
    "increase",
    "increases",
    "solve",
    "solves",
    "strengthen",
    "strengthens",
}
NEGATIVE_DIRECTION_CUES = {
    "delete",
    "deletes",
    "destroy",
    "destroys",
    "lower",
    "lowers",
    "prevent",
    "prevents",
    "reduce",
    "reduces",
    "undermine",
    "undermines",
}
GENERIC_EQUIVALENCES = {
    "baseline": "standard",
    "baselines": "standard",
    "black_market": "illegal",
    "books": "betting",
    "diplomatic": "diplomacy",
    "enforcement": "regulation",
    "escalates": "escalation",
    "escalat": "escalation",
    "fragmented": "vary",
    "individualized": "personalization",
    "offshore": "illegal",
    "promotions": "personalization",
    "rules": "regulation",
    "settlement": "diplomacy",
    "uniformity": "standard",
}
NON_UNIQUE_CUES = {
    "already",
    "currently",
    "existing",
    "multi-billion",
    "non-unique",
    "nonunique",
    "status quo",
    "squo",
    "today",
}
MITIGATION_CUES = {
    "ban",
    "bans",
    "check",
    "checks",
    "limit",
    "limits",
    "lower",
    "lowers",
    "mitigate",
    "mitigates",
    "prevent",
    "prevents",
    "prohibit",
    "prohibits",
    "reduce",
    "reduces",
}
INDICT_CUES = {
    "assumes",
    "bad evidence",
    "flawed",
    "indict",
    "methodology",
    "no evidence",
    "overstates",
    "underfunded",
    "wrong",
}
TURN_CUES = {
    "backfire",
    "backfires",
    "helps our side",
    "impact turn",
    "link turn",
    "turns the argument",
}


@dataclass(frozen=True)
class ClaimRelationAssessment:
    relationship: ClaimRelationship
    confidence: float
    overlap: float
    mechanism: float
    directness: float
    reasons: list[str]

    def to_dict(self) -> dict[str, object]:
        return {
            "relationship": self.relationship.value,
            "confidence": self.confidence,
            "overlap": self.overlap,
            "mechanism": self.mechanism,
            "directness": self.directness,
            "reasons": self.reasons,
        }

    def to_result(self) -> RelationshipResult:
        return RelationshipResult(
            relationship=self.relationship,
            confidence=self.confidence,
            topic_match=self.overlap,
            mechanism_match=self.mechanism,
            warrant_match=max(self.overlap * 0.6, self.mechanism),
            directness=self.directness,
            reasons=self.reasons,
        )


def classify_claim_relationship(
    claim: str,
    card: dict[str, Any] | str,
) -> ClaimRelationAssessment:
    card_text = card if isinstance(card, str) else card_relationship_text(card)
    front_text = card if isinstance(card, str) else front_relationship_text(card)
    claim_terms = _concepts(claim)
    card_terms = _concepts(card_text)
    if not claim_terms:
        return _assessment(ClaimRelationship.UNKNOWN, 0.0, 0.0, 0.0, ["empty claim"])

    overlap = len(claim_terms & card_terms) / len(claim_terms)
    claim_mechanism = parse_mechanism(claim)
    card_mechanism = parse_mechanism(card_text)
    mech = mechanism_match(claim_mechanism, card_mechanism)
    polarity_opposes = (
        claim_mechanism.polarity != 0
        and card_mechanism.polarity != 0
        and claim_mechanism.polarity != card_mechanism.polarity
        and mech >= 0.2
    )
    cues = _cue_matches(card_text)

    if overlap < 0.08 and mech < 0.08:
        return _assessment(
            ClaimRelationship.IRRELEVANT,
            0.9,
            overlap,
            mech,
            ["topic and mechanism mismatch"],
        )
    direction = _direction(claim_terms, card_terms)
    if _is_non_unique_response(claim_terms, card_text, cues) and (overlap >= 0.16 or mech >= 0.18):
        return _assessment(
            ClaimRelationship.NON_UNIQUE,
            _confidence(overlap, mech, 0.78),
            overlap,
            mech,
            ["non-unique/status quo cues"],
        )
    front_assessment = _front_support_assessment(
        claim=claim,
        front_text=front_text,
        claim_terms=claim_terms,
    )
    if front_assessment is not None:
        return front_assessment

    if cues["indict"] and (overlap >= 0.04 or mech >= 0.08):
        return _assessment(
            ClaimRelationship.INDICTS,
            _confidence(overlap, mech, 0.82),
            overlap,
            mech,
            ["warrant/source/mechanism indictment cues"],
        )
    if cues["turn"] and (overlap >= 0.12 or mech >= 0.12):
        return _assessment(
            ClaimRelationship.TURNS,
            _confidence(overlap, mech, 0.82),
            overlap,
            mech,
            ["turn cues"],
        )
    if polarity_opposes or direction == "opposes" or (_has_negation(card_text) and overlap >= 0.22):
        if cues["mitigate"] and not _direct_effect_opposition(claim_mechanism, card_terms):
            return _assessment(
                ClaimRelationship.MITIGATES,
                _confidence(overlap, mech, 0.78),
                overlap,
                mech,
                ["mitigation cues oppose claim"],
            )
        return _assessment(
            ClaimRelationship.CONTRADICTS,
            _confidence(overlap, mech, 0.82),
            overlap,
            mech,
            ["opposes claim mechanism"],
        )
    if cues["mitigate"] and direction != "supports" and _direct_effect_opposition(claim_mechanism, card_terms):
        return _assessment(
            ClaimRelationship.CONTRADICTS,
            _confidence(overlap, mech, 0.78),
            overlap,
            mech,
            ["mitigation cue directly negates claim effect"],
        )
    if cues["mitigate"] and direction != "supports" and (overlap >= 0.08 or mech >= 0.12):
        return _assessment(
            ClaimRelationship.MITIGATES,
            _confidence(overlap, mech, 0.72),
            overlap,
            mech,
            ["mitigation cues"],
        )
    if direction == "supports" and (overlap >= 0.1 or mech >= 0.12):
        return _assessment(
            ClaimRelationship.SUPPORTS,
            _confidence(overlap, mech, 0.8),
            overlap,
            mech,
            ["same causal direction"],
        )
    if overlap >= 0.55 or (overlap >= 0.35 and mech >= 0.12):
        return _assessment(
            ClaimRelationship.SUPPORTS,
            _confidence(overlap, mech, 0.86),
            overlap,
            mech,
            ["card substantially proves the claim"],
        )
    if overlap >= 0.2 or mech >= 0.18:
        return _assessment(
            ClaimRelationship.QUALIFIES,
            _confidence(overlap, mech, 0.55),
            overlap,
            mech,
            ["related but not a direct answer"],
        )
    return _assessment(
        ClaimRelationship.BACKGROUND,
        _confidence(overlap, mech, 0.35),
        overlap,
        mech,
        ["background overlap"],
    )


def card_relationship_text(card: dict[str, Any]) -> str:
    return "\n".join(
        str(part)
        for part in [
            card.get("section") or card.get("section_name"),
            card.get("tag"),
            card.get("card_name"),
            card.get("citation"),
            _highlight_text(card),
            card.get("body") or card.get("body_preview"),
        ]
        if part
    )


def front_relationship_text(card: dict[str, Any]) -> str:
    return "\n".join(
        str(part)
        for part in [
            card.get("section") or card.get("section_name"),
            card.get("tag"),
            _highlight_text(card),
        ]
        if part
    )


def _concepts(text: str) -> set[str]:
    concepts = _terms(text) | extract_phrase_concepts(text)
    expanded = set(concepts)
    for concept in concepts:
        expanded.add(GENERIC_EQUIVALENCES.get(concept, concept))
    return expanded


def _cue_matches(text: str) -> dict[str, bool]:
    lowered = text.lower()
    terms = _terms(text)
    return {
        "indict": _has_phrase(lowered, INDICT_CUES),
        "mitigate": bool(terms & MITIGATION_CUES) or _has_phrase(lowered, MITIGATION_CUES),
        "non_unique": _has_phrase(lowered, NON_UNIQUE_CUES),
        "turn": bool(terms & TURN_CUES) or _has_phrase(lowered, TURN_CUES),
    }


def _has_phrase(text: str, phrases: set[str]) -> bool:
    for phrase in phrases:
        if " " not in phrase and "-" not in phrase:
            if re.search(rf"\b{re.escape(phrase)}\b", text):
                return True
            continue
        pattern = r"\b" + r"\s+".join(re.escape(part) for part in phrase.split()) + r"\b"
        if re.search(pattern, text):
            return True
    return False


def _has_negation(text: str) -> bool:
    lowered = text.lower()
    terms = _terms(text)
    return bool(terms & NEGATION_CUES) or bool(
        re.search(r"\b(?:no|not|cannot|doesn't|doesn['’]?t)\b", lowered)
    )


def _is_non_unique_response(
    claim_terms: set[str],
    card_text: str,
    cues: dict[str, bool],
) -> bool:
    if not cues["non_unique"]:
        return False
    lowered = card_text.lower()
    if re.search(r"\b(?:non-unique|nonunique|status quo|squo)\b", lowered):
        return True
    return bool(claim_terms & {"unique", "uniquely", "new"})


def _direction(claim_terms: set[str], card_terms: set[str]) -> str:
    claim_positive = bool(claim_terms & POSITIVE_DIRECTION_CUES)
    claim_negative = bool(claim_terms & NEGATIVE_DIRECTION_CUES)
    card_positive = bool(card_terms & POSITIVE_DIRECTION_CUES)
    card_negative = bool(card_terms & NEGATIVE_DIRECTION_CUES)
    if claim_positive and card_positive:
        return "supports"
    if claim_negative and card_negative:
        return "supports"
    if claim_positive and card_negative:
        return "opposes"
    if claim_negative and card_positive:
        return "opposes"
    return "unknown"


def _front_support_assessment(
    *,
    claim: str,
    front_text: str,
    claim_terms: set[str],
) -> ClaimRelationAssessment | None:
    if not front_text:
        return None
    front_terms = _concepts(front_text)
    if not front_terms:
        return None
    overlap = len(claim_terms & front_terms) / len(claim_terms)
    claim_mechanism = parse_mechanism(claim)
    front_mechanism = parse_mechanism(front_text)
    mech = mechanism_match(claim_mechanism, front_mechanism)
    direction = _direction(claim_terms, front_terms)
    if direction == "opposes":
        return None
    if overlap >= 0.55 or (overlap >= 0.35 and mech >= 0.12):
        return _assessment(
            ClaimRelationship.SUPPORTS,
            _confidence(overlap, mech, 0.88),
            overlap,
            mech,
            ["front matter substantially proves the claim"],
        )
    return None


def _direct_effect_opposition(claim_mechanism, card_terms: set[str]) -> bool:
    effects = (
        claim_mechanism.effect_groups
        - claim_mechanism.actor_groups
        - claim_mechanism.cause_groups
        - claim_mechanism.generic_terms
    )
    if not effects:
        effects = (
            claim_mechanism.object_groups
            - claim_mechanism.actor_groups
            - claim_mechanism.cause_groups
            - claim_mechanism.generic_terms
        )
    expanded_effects = set(effects)
    for effect in effects:
        expanded_effects.add(GENERIC_EQUIVALENCES.get(effect, effect))
    return bool(expanded_effects & card_terms)


def _confidence(overlap: float, mechanism: float, base: float) -> float:
    return round(max(0.0, min(1.0, base * 0.45 + overlap * 0.35 + mechanism * 0.2)), 3)


def _assessment(
    relationship: ClaimRelationship,
    confidence: float,
    overlap: float,
    mechanism: float,
    reasons: list[str],
) -> ClaimRelationAssessment:
    directness = _directness(overlap, mechanism, relationship, reasons)
    return ClaimRelationAssessment(
        relationship=relationship,
        confidence=round(confidence, 3),
        overlap=round(overlap, 3),
        mechanism=round(mechanism, 3),
        directness=round(directness, 3),
        reasons=reasons,
    )


def _directness(
    overlap: float,
    mechanism: float,
    relationship: ClaimRelationship,
    reasons: list[str],
) -> float:
    base = max(overlap * 0.65, mechanism)
    if relationship in {
        ClaimRelationship.SUPPORTS,
        ClaimRelationship.CONTRADICTS,
        ClaimRelationship.TURNS,
        ClaimRelationship.NON_UNIQUE,
    }:
        base += 0.12
    if any("front matter" in reason or "directly" in reason for reason in reasons):
        base += 0.18
    if relationship in {ClaimRelationship.BACKGROUND, ClaimRelationship.QUALIFIES}:
        base -= 0.08
    if relationship == ClaimRelationship.IRRELEVANT:
        base = 0.0
    return max(0.0, min(1.0, base))
