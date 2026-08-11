"""C++-shaped models for perspective-aware debate retrieval."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class Owner(str, Enum):
    US = "us"
    OPPONENT = "opponent"
    SHARED = "shared"
    UNKNOWN = "unknown"


class DebateSide(str, Enum):
    AFFIRMATIVE = "affirmative"
    NEGATIVE = "negative"
    UNKNOWN = "unknown"


class Stance(str, Enum):
    SUPPORTS = "supports"
    OPPOSES = "opposes"
    QUALIFIES = "qualifies"
    TURNS = "turns"
    INDICTS = "indicts"
    NON_UNIQUE = "non_unique"
    MITIGATES = "mitigates"
    IMPACT = "impact"
    UNKNOWN = "unknown"


class Perspective(str, Enum):
    OURS = "ours"
    OPPONENT = "opponent"
    BOTH = "both"
    NEUTRAL = "neutral"


class DebateIntent(str, Enum):
    ANSWER = "answer"
    THEIR_EVIDENCE = "their_evidence"
    COMPARE = "compare"
    TURN = "turn"
    INDICT = "indict"
    SEARCH = "search"


class ClaimRelationship(str, Enum):
    SUPPORTS = "SUPPORTS"
    CONTRADICTS = "CONTRADICTS"
    TURNS = "TURNS"
    NON_UNIQUE = "NON_UNIQUE"
    QUALIFIES = "QUALIFIES"
    MITIGATES = "MITIGATES"
    INDICTS = "INDICTS"
    BACKGROUND = "BACKGROUND"
    IRRELEVANT = "IRRELEVANT"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class RelationshipResult:
    relationship: ClaimRelationship
    confidence: float
    topic_match: float
    mechanism_match: float
    warrant_match: float
    directness: float
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "relationship": self.relationship.value,
            "confidence": self.confidence,
            "topic_match": self.topic_match,
            "mechanism_match": self.mechanism_match,
            "warrant_match": self.warrant_match,
            "directness": self.directness,
            "reasons": self.reasons,
        }


@dataclass(frozen=True)
class RoundContext:
    our_side: DebateSide = DebateSide.UNKNOWN
    opponent_side: DebateSide = DebateSide.UNKNOWN
    resolution: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "our_side": self.our_side.value,
            "opponent_side": self.opponent_side.value,
            "resolution": self.resolution,
        }


@dataclass(frozen=True)
class DebateQuery:
    raw: str
    semantic_query: str
    perspective: Perspective = Perspective.NEUTRAL
    intent: DebateIntent = DebateIntent.SEARCH
    opponent_claim: str | None = None
    topics: list[str] = field(default_factory=list)
    mechanisms: list[str] = field(default_factory=list)
    control_language: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "raw": self.raw,
            "semantic_query": self.semantic_query,
            "perspective": self.perspective.value,
            "intent": self.intent.value,
            "opponent_claim": self.opponent_claim,
            "topics": self.topics,
            "mechanisms": self.mechanisms,
            "control_language": self.control_language,
        }


@dataclass(frozen=True)
class SideCandidate:
    card_id: str
    retrieval_score: float
    owner: Owner
    formal_side: DebateSide
    topic_score: float
    mechanism_score: float
    warrant_score: float
    relationship: str
    relationship_confidence: float
    directness: float
    evidence_strength: float
    owner_utility: float
    relationship_utility: float
    final_score: float
    card: dict[str, Any]
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["owner"] = self.owner.value
        data["formal_side"] = self.formal_side.value
        return data


@dataclass(frozen=True)
class LaneResult:
    name: str
    purpose: str
    candidates: list[SideCandidate]

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "purpose": self.purpose,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class SideSearchResult:
    query: DebateQuery
    round_context: RoundContext
    our_lane: LaneResult
    opponent_lane: LaneResult

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query.to_dict(),
            "round_context": self.round_context.to_dict(),
            "our_lane": self.our_lane.to_dict(),
            "opponent_lane": self.opponent_lane.to_dict(),
        }
