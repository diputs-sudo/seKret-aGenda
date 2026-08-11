"""Two-lane debate side engine over already-retrieved candidates."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from .model import (
    ClaimRelationship,
    DebateIntent,
    DebateQuery,
    DebateSide,
    LaneResult,
    Owner,
    RoundContext,
    SideCandidate,
    SideSearchResult,
)
from .query import parse_debate_query
from .relationships import claim_component_coverage, classify_claim_relationship


class DebateSideEngine:
    """Split retrieval candidates into our-evidence and opponent-evidence lanes."""

    def build(
        self,
        query: DebateQuery | str,
        candidates: list[dict[str, Any]],
        *,
        round_context: RoundContext | None = None,
        limit_per_lane: int = 5,
    ) -> SideSearchResult:
        debate_query = parse_debate_query(query) if isinstance(query, str) else query
        context = round_context or RoundContext()
        side_candidates = self.assess_candidates(debate_query, candidates, context)
        return self.build_from_assessed(
            debate_query,
            side_candidates,
            round_context=context,
            limit_per_lane=limit_per_lane,
        )

    def assess_candidates(
        self,
        query: DebateQuery | str,
        candidates: list[dict[str, Any]],
        round_context: RoundContext | None = None,
    ) -> list[SideCandidate]:
        debate_query = parse_debate_query(query) if isinstance(query, str) else query
        context = round_context or RoundContext()
        relationship_cache = {}
        return [
            self.assess_candidate(
                debate_query,
                candidate,
                context,
                relationship_cache=relationship_cache,
            )
            for candidate in candidates
        ]

    def build_from_assessed(
        self,
        query: DebateQuery,
        side_candidates: list[SideCandidate],
        *,
        round_context: RoundContext | None = None,
        limit_per_lane: int = 5,
    ) -> SideSearchResult:
        context = round_context or RoundContext()
        our_candidates = [
            candidate
            for candidate in side_candidates
            if candidate.owner in {Owner.US, Owner.SHARED}
            and _useful_in_our_lane(candidate, query.intent)
        ]
        opponent_candidates = [
            candidate
            for candidate in side_candidates
            if candidate.owner in {Owner.OPPONENT, Owner.SHARED}
            and _useful_in_opponent_lane(candidate, query.intent)
        ]
        if not our_candidates:
            our_candidates = [
                candidate
                for candidate in side_candidates
                if candidate.owner == Owner.UNKNOWN
                and _useful_in_our_lane(candidate, query.intent)
            ]
        if not opponent_candidates:
            opponent_candidates = [
                candidate
                for candidate in side_candidates
                if candidate.owner == Owner.UNKNOWN
                and _useful_in_opponent_lane(candidate, query.intent)
            ]

        return SideSearchResult(
            query=query,
            round_context=context,
            our_lane=LaneResult(
                name="our_evidence",
                purpose="cards we can read or use as answers",
                candidates=_top_lane(our_candidates, query.intent, "our", limit_per_lane),
            ),
            opponent_lane=LaneResult(
                name="opponent_evidence",
                purpose="cards that model, qualify, or expose their position",
                candidates=_top_lane(
                    opponent_candidates,
                    query.intent,
                    "opponent",
                    limit_per_lane,
                ),
            ),
        )

    def assess_candidate(
        self,
        query: DebateQuery,
        card: dict[str, Any],
        round_context: RoundContext,
        relationship_cache: dict[tuple[str, str], Any] | None = None,
    ) -> SideCandidate:
        owner = _owner(card)
        formal_side = _debate_side(card.get("side") or _metadata(card).get("side"))
        assessment = card.get("candidate_assessment") or card.get("reranker_assessment") or {}
        claim_text = query.opponent_claim or query.semantic_query
        cache_key = (claim_text.strip().lower(), _evidence_key(card))
        if relationship_cache is not None and cache_key in relationship_cache:
            claim_assessment = relationship_cache[cache_key]
        else:
            claim_assessment = classify_claim_relationship(claim_text, card)
            if relationship_cache is not None:
                relationship_cache[cache_key] = claim_assessment
        coverage = claim_component_coverage(claim_text, card)
        original_relationship = str(
            assessment.get("relationship") or ClaimRelationship.IRRELEVANT.value
        )
        relationship = claim_assessment.relationship.value
        retrieval_score = _float(card.get("retrieval_score") or card.get("score"))
        coverage_score = _coverage_score(coverage)
        attack_score = _attack_alignment_score(coverage)
        source_quality = _coverage_source_quality(coverage)
        relevance_score = max(
            claim_assessment.overlap,
            coverage_score,
            _float(assessment.get("relevance_score")) * 0.55,
        )
        topic_score = max(claim_assessment.overlap, _float(assessment.get("topic_match")) * 0.5)
        mechanism_score = max(
            claim_assessment.mechanism,
            _float(assessment.get("mechanism_match")) * 0.5,
            attack_score * 0.62,
        )
        warrant_score = max(
            claim_assessment.to_result().warrant_match,
            _float(assessment.get("warrant_match")) * 0.5,
            attack_score * 0.55,
        )
        relationship_confidence = max(
            claim_assessment.confidence,
            _float(assessment.get("confidence")) * 0.6,
        )
        directness = round(
            claim_assessment.directness * 0.42
            + coverage_score * 0.32
            + attack_score * 0.2
            + source_quality * 0.06,
            3,
        )
        evidence_strength = _float(assessment.get("evidence_strength"))
        owner_utility = _owner_utility(query.intent, owner)
        relationship_utility = _relationship_utility(query.intent, relationship)
        side_utility = _side_utility(formal_side, round_context)
        final_score = _final_score(
            retrieval_score=retrieval_score,
            topic_score=topic_score,
            mechanism_score=mechanism_score,
            warrant_score=warrant_score,
            relationship_confidence=relationship_confidence,
            directness=directness,
            coverage_score=coverage_score,
            attack_score=attack_score,
            source_quality=source_quality,
            evidence_strength=evidence_strength,
            owner_utility=owner_utility,
            relationship_utility=relationship_utility,
            side_utility=side_utility,
        )

        reasons = [
            f"owner={owner.value}",
            f"side={formal_side.value}",
            f"relationship={relationship}",
            f"retrieval_relationship={original_relationship}",
            f"relevance={relevance_score:.3f}",
            f"directness={directness:.3f}",
            f"coverage={coverage_score:.3f}",
            f"attack={attack_score:.3f}",
            f"source_quality={source_quality:.3f}",
        ]
        reasons.extend(str(warning) for warning in coverage.get("warnings", [])[:2])
        reasons.extend(claim_assessment.reasons[:2])
        if owner == Owner.OPPONENT and query.intent == DebateIntent.ANSWER:
            reasons.append("kept in opponent lane, not as our answer")
        if relationship_utility > 0.75:
            reasons.append("relationship is useful for this intent")

        return SideCandidate(
            card_id=str(card.get("card_id") or card.get("id") or ""),
            retrieval_score=retrieval_score,
            owner=owner,
            formal_side=formal_side,
            relevance_score=relevance_score,
            topic_score=topic_score,
            mechanism_score=mechanism_score,
            warrant_score=warrant_score,
            coverage=coverage,
            relationship=relationship,
            relationship_confidence=relationship_confidence,
            directness=directness,
            evidence_strength=evidence_strength,
            owner_utility=owner_utility,
            relationship_utility=relationship_utility,
            final_score=final_score,
            card=card,
            reasons=reasons,
        )

    def lane_decision(
        self,
        candidate: SideCandidate,
        intent: DebateIntent,
        lane: str,
    ) -> dict[str, Any]:
        eligible = (
            candidate.owner in {Owner.US, Owner.SHARED}
            and _useful_in_our_lane(candidate, intent)
            if lane == "our"
            else candidate.owner in {Owner.OPPONENT, Owner.SHARED}
            and _useful_in_opponent_lane(candidate, intent)
        )
        owner_utility = _owner_utility_for_lane(intent, candidate.owner, lane)
        relationship_utility = _relationship_utility_for_lane(
            intent,
            candidate.relationship,
            lane,
        )
        gate_reason = _hard_gate_reason(candidate, lane, relationship_utility)
        final_score = 0.0
        if eligible and gate_reason is None:
            final_score = _final_score(
                retrieval_score=candidate.retrieval_score,
                topic_score=candidate.topic_score,
                mechanism_score=candidate.mechanism_score,
                warrant_score=candidate.warrant_score,
                relationship_confidence=candidate.relationship_confidence,
                directness=candidate.directness,
                coverage_score=_coverage_score(candidate.coverage),
                attack_score=_attack_alignment_score(candidate.coverage),
                source_quality=_coverage_source_quality(candidate.coverage),
                evidence_strength=candidate.evidence_strength,
                owner_utility=owner_utility,
                relationship_utility=relationship_utility,
                side_utility=0.5,
            )

        return {
            "lane": lane,
            "eligible": eligible,
            "accepted": eligible and gate_reason is None and final_score > 0,
            "reason": _lane_rejection_reason(
                candidate,
                lane,
                eligible,
                gate_reason,
            ),
            "owner_utility": owner_utility,
            "relationship_utility": relationship_utility,
            "final_score": final_score,
        }


def _top_lane(
    candidates: list[SideCandidate],
    intent: DebateIntent,
    lane: str,
    limit: int,
) -> list[SideCandidate]:
    scored = []
    for candidate in candidates:
        owner_utility = _owner_utility_for_lane(intent, candidate.owner, lane)
        relationship_utility = _relationship_utility_for_lane(
            intent,
            candidate.relationship,
            lane,
        )
        if _fails_hard_gate(candidate, lane, relationship_utility):
            continue
        final_score = _final_score(
            retrieval_score=candidate.retrieval_score,
            topic_score=candidate.topic_score,
            mechanism_score=candidate.mechanism_score,
            warrant_score=candidate.warrant_score,
            relationship_confidence=candidate.relationship_confidence,
            directness=candidate.directness,
            coverage_score=_coverage_score(candidate.coverage),
            attack_score=_attack_alignment_score(candidate.coverage),
            source_quality=_coverage_source_quality(candidate.coverage),
            evidence_strength=candidate.evidence_strength,
            owner_utility=owner_utility,
            relationship_utility=relationship_utility,
            side_utility=0.5,
        )
        if final_score <= 0:
            continue
        scored.append(
            replace(
                candidate,
                owner_utility=owner_utility,
                relationship_utility=relationship_utility,
                final_score=final_score,
            )
        )
    return sorted(scored, key=lambda candidate: candidate.final_score, reverse=True)[:limit]


def _useful_in_our_lane(candidate: SideCandidate, intent: DebateIntent) -> bool:
    relationship = _claim_relationship(candidate.relationship)
    if intent in {DebateIntent.ANSWER, DebateIntent.TURN, DebateIntent.INDICT}:
        return relationship in {
            ClaimRelationship.CONTRADICTS,
            ClaimRelationship.TURNS,
            ClaimRelationship.NON_UNIQUE,
            ClaimRelationship.MITIGATES,
            ClaimRelationship.INDICTS,
        }
    return relationship not in {
        ClaimRelationship.IRRELEVANT,
        ClaimRelationship.UNKNOWN,
    }


def _useful_in_opponent_lane(candidate: SideCandidate, intent: DebateIntent) -> bool:
    relationship = _claim_relationship(candidate.relationship)
    if intent in {DebateIntent.ANSWER, DebateIntent.THEIR_EVIDENCE, DebateIntent.COMPARE}:
        return relationship in {
            ClaimRelationship.SUPPORTS,
            ClaimRelationship.QUALIFIES,
            ClaimRelationship.BACKGROUND,
        }
    return relationship not in {
        ClaimRelationship.IRRELEVANT,
        ClaimRelationship.UNKNOWN,
    }


def _final_score(
    *,
    retrieval_score: float,
    topic_score: float,
    mechanism_score: float,
    warrant_score: float,
    relationship_confidence: float,
    directness: float,
    coverage_score: float,
    attack_score: float,
    source_quality: float,
    evidence_strength: float,
    owner_utility: float,
    relationship_utility: float,
    side_utility: float,
) -> float:
    strategic_utility = max(0.0, relationship_utility)
    base = (
        max(0.05, retrieval_score)
        * max(0.05, relationship_confidence)
        * max(0.05, strategic_utility)
        * max(0.2, owner_utility)
    )
    score = base * 0.72 + (
        topic_score * 0.04
        + mechanism_score * 0.08
        + warrant_score * 0.05
        + directness * 0.065
        + coverage_score * 0.07
        + attack_score * 0.085
        + source_quality * 0.03
        + evidence_strength * 0.015
        + side_utility * 0.005
    )
    return round(max(0.0, min(1.0, score)), 3)


def _owner_utility(intent: DebateIntent, owner: Owner) -> float:
    return _owner_utility_for_lane(intent, owner, "our")


def _owner_utility_for_lane(intent: DebateIntent, owner: Owner, lane: str) -> float:
    if lane == "opponent":
        return {
            Owner.OPPONENT: 1.0,
            Owner.SHARED: 0.75,
            Owner.UNKNOWN: 0.45,
            Owner.US: 0.1,
        }[owner]
    if intent in {DebateIntent.ANSWER, DebateIntent.TURN, DebateIntent.INDICT}:
        return {
            Owner.US: 1.0,
            Owner.SHARED: 0.85,
            Owner.UNKNOWN: 0.45,
            Owner.OPPONENT: 0.15,
        }[owner]
    if intent == DebateIntent.THEIR_EVIDENCE:
        return {
            Owner.OPPONENT: 1.0,
            Owner.SHARED: 0.75,
            Owner.UNKNOWN: 0.45,
            Owner.US: 0.1,
        }[owner]
    if intent == DebateIntent.COMPARE:
        return {
            Owner.US: 0.8,
            Owner.OPPONENT: 0.8,
            Owner.SHARED: 0.7,
            Owner.UNKNOWN: 0.45,
        }[owner]
    return 0.55 if owner == Owner.UNKNOWN else 0.7


def _relationship_utility(intent: DebateIntent, relationship: str) -> float:
    return _relationship_utility_for_lane(intent, relationship, "our")


def _relationship_utility_for_lane(
    intent: DebateIntent,
    relationship: str,
    lane: str,
) -> float:
    normalized = relationship.upper()
    if lane == "opponent":
        return {
            ClaimRelationship.SUPPORTS.value: 1.0,
            ClaimRelationship.QUALIFIES.value: 0.8,
            ClaimRelationship.BACKGROUND.value: 0.45,
            ClaimRelationship.CONTRADICTS.value: 0.0,
            ClaimRelationship.MITIGATES.value: 0.0,
            ClaimRelationship.INDICTS.value: 0.0,
            ClaimRelationship.NON_UNIQUE.value: 0.0,
            ClaimRelationship.TURNS.value: -0.5,
            ClaimRelationship.IRRELEVANT.value: -1.0,
            ClaimRelationship.UNKNOWN.value: 0.0,
        }.get(normalized, 0.35)
    if intent == DebateIntent.TURN:
        if normalized in {ClaimRelationship.TURNS.value, ClaimRelationship.CONTRADICTS.value}:
            return 0.9
    if intent == DebateIntent.INDICT:
        if normalized in {ClaimRelationship.INDICTS.value, ClaimRelationship.CONTRADICTS.value}:
            return 0.75
    if intent == DebateIntent.ANSWER:
        return {
            ClaimRelationship.TURNS.value: 1.0,
            ClaimRelationship.CONTRADICTS.value: 0.95,
            ClaimRelationship.NON_UNIQUE.value: 0.85,
            ClaimRelationship.INDICTS.value: 0.8,
            ClaimRelationship.MITIGATES.value: 0.7,
            ClaimRelationship.QUALIFIES.value: 0.25,
            ClaimRelationship.BACKGROUND.value: 0.0,
            ClaimRelationship.SUPPORTS.value: -1.0,
            ClaimRelationship.IRRELEVANT.value: -1.0,
            ClaimRelationship.UNKNOWN.value: -0.5,
        }.get(normalized, 0.35)
    if intent == DebateIntent.THEIR_EVIDENCE:
        return {
            ClaimRelationship.SUPPORTS.value: 1.0,
            ClaimRelationship.QUALIFIES.value: 0.8,
            ClaimRelationship.BACKGROUND.value: 0.55,
            ClaimRelationship.CONTRADICTS.value: 0.0,
            ClaimRelationship.MITIGATES.value: 0.0,
            ClaimRelationship.INDICTS.value: 0.0,
            ClaimRelationship.NON_UNIQUE.value: 0.0,
            ClaimRelationship.TURNS.value: -0.5,
            ClaimRelationship.IRRELEVANT.value: -1.0,
            ClaimRelationship.UNKNOWN.value: 0.0,
        }.get(normalized, 0.45)
    return 0.55


def _side_utility(side: DebateSide, context: RoundContext) -> float:
    if side == DebateSide.UNKNOWN:
        return 0.5
    if side == context.our_side:
        return 0.75
    if side == context.opponent_side:
        return 0.75
    return 0.4


def _owner(card: dict[str, Any]) -> Owner:
    return _enum_value(Owner, card.get("owner") or _metadata(card).get("owner"))


def _debate_side(value: Any) -> DebateSide:
    return _enum_value(DebateSide, value)


def _metadata(card: dict[str, Any]) -> dict[str, Any]:
    metadata = card.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _evidence_key(card: dict[str, Any]) -> str:
    metadata = _metadata(card)
    for key in ("content_hash", "evidence_id"):
        value = card.get(key) or metadata.get(key)
        if value:
            return f"{key}:{value}"
    content_key = "|".join(
        str(card.get(key) or "")
        for key in ("card_name", "citation", "tag", "body_preview", "body")
    ).strip()
    if content_key:
        return f"content:{content_key}"
    for key in ("card_id", "id"):
        value = card.get(key) or metadata.get(key)
        if value:
            return f"{key}:{value}"
    return "unknown"


def _fails_hard_gate(
    candidate: SideCandidate,
    lane: str,
    relationship_utility: float,
) -> bool:
    return _hard_gate_reason(candidate, lane, relationship_utility) is not None


def _hard_gate_reason(
    candidate: SideCandidate,
    lane: str,
    relationship_utility: float,
) -> str | None:
    relationship = _claim_relationship(candidate.relationship)
    if relationship in {ClaimRelationship.IRRELEVANT, ClaimRelationship.UNKNOWN}:
        return f"{relationship.value} relationship"
    if relationship_utility <= 0:
        return "relationship utility <= 0"
    if candidate.relationship_confidence < 0.32:
        return "relationship confidence < 0.32"
    if lane == "our" and candidate.relationship_confidence < 0.5:
        return "our-answer relationship confidence < 0.50"
    if lane == "our" and candidate.directness < 0.25:
        return "our-answer directness < 0.25"
    if lane == "our" and relationship in {ClaimRelationship.SUPPORTS, ClaimRelationship.BACKGROUND}:
        return f"{relationship.value} opponent claim"
    if lane == "opponent" and relationship in {ClaimRelationship.TURNS, ClaimRelationship.IRRELEVANT}:
        return f"{relationship.value} is not opponent evidence"
    if lane == "opponent" and relationship not in {
        ClaimRelationship.SUPPORTS,
        ClaimRelationship.QUALIFIES,
        ClaimRelationship.BACKGROUND,
    }:
        return f"{relationship.value} is not opponent evidence"
    if (
        lane == "opponent"
        and relationship == ClaimRelationship.SUPPORTS
        and candidate.relationship_confidence < 0.5
    ):
        return "opponent-support confidence < 0.50"
    if (
        lane == "opponent"
        and relationship == ClaimRelationship.SUPPORTS
        and candidate.topic_score < 0.2
    ):
        return "opponent-support topic < 0.20"
    if (
        lane == "opponent"
        and relationship == ClaimRelationship.SUPPORTS
        and candidate.directness < 0.2
    ):
        return "opponent-support directness < 0.20"
    if (
        lane == "opponent"
        and relationship
        not in {
            ClaimRelationship.SUPPORTS,
            ClaimRelationship.QUALIFIES,
            ClaimRelationship.BACKGROUND,
        }
        and candidate.relationship_confidence < 0.5
    ):
        return "opponent-side conflict confidence < 0.50"
    if candidate.topic_score < 0.08 and candidate.mechanism_score < 0.08:
        return "topic and mechanism below floor"
    return None


def _lane_rejection_reason(
    candidate: SideCandidate,
    lane: str,
    eligible: bool,
    gate_reason: str | None,
) -> str:
    if not eligible:
        if lane == "our" and candidate.owner == Owner.OPPONENT:
            return "wrong owner for our lane"
        if lane == "opponent" and candidate.owner == Owner.US:
            return "wrong owner for opponent lane"
        return "relationship not useful for lane"
    if gate_reason:
        return gate_reason
    return "accepted"


def _enum_value(enum_type, value: Any):
    text = str(value or "unknown").strip().lower().replace("-", "_")
    aliases = {
        "ours": "us",
        "we": "us",
        "them": "opponent",
        "their": "opponent",
        "aff": "affirmative",
        "neg": "negative",
        "pro": "affirmative",
        "con": "negative",
        "nonunique": "non_unique",
        "non-unique": "non_unique",
        "turn": "turns",
        "indict": "indicts",
        "mitigate": "mitigates",
    }
    text = aliases.get(text, text)
    try:
        return enum_type(text)
    except ValueError:
        return enum_type.UNKNOWN


def _claim_relationship(value: Any) -> ClaimRelationship:
    try:
        return ClaimRelationship(str(value or "UNKNOWN").upper())
    except ValueError:
        return ClaimRelationship.UNKNOWN


def _float(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _coverage_score(coverage: dict[str, Any]) -> float:
    return _float((coverage or {}).get("score"))


def _coverage_source_quality(coverage: dict[str, Any]) -> float:
    return _float((coverage or {}).get("source_quality"))


def _attack_alignment_score(coverage: dict[str, Any]) -> float:
    attack = (coverage or {}).get("attack_alignment") or {}
    return _float(attack.get("score") if isinstance(attack, dict) else 0.0)
