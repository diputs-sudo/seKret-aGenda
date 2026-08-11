"""Structured claim parsing for argument-aware retrieval."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from enum import Enum


class ClaimRelation(str, Enum):
    CAUSES = "CAUSES"
    PREVENTS = "PREVENTS"
    INCREASES = "INCREASES"
    DECREASES = "DECREASES"
    ENABLES = "ENABLES"
    UNDERMINES = "UNDERMINES"
    SOLVES = "SOLVES"
    PROTECTS = "PROTECTS"
    DETERS = "DETERS"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ClaimSlot:
    value: str
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class StructuredClaim:
    raw: str
    subject: ClaimSlot
    relation: ClaimRelation
    relation_text: str
    effect: ClaimSlot
    target_actor: ClaimSlot
    target_action: ClaimSlot
    target_object: ClaimSlot
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {
            "raw": self.raw,
            "subject": self.subject.to_dict(),
            "relation": self.relation.value,
            "relation_text": self.relation_text,
            "effect": self.effect.to_dict(),
            "target_actor": self.target_actor.to_dict(),
            "target_action": self.target_action.to_dict(),
            "target_object": self.target_object.to_dict(),
            "display_effect": self.display_effect,
            "confidence": self.confidence,
        }

    @property
    def has_structure(self) -> bool:
        return self.relation != ClaimRelation.UNKNOWN and self.confidence >= 0.55

    @property
    def actor_action_object(self) -> str:
        actor = self.target_actor.value
        action = _inflect_action(self.target_action.value)
        obj = self.target_object.value
        if actor and action and obj:
            return f"{actor} {action} {obj}"
        return self.effect.value

    @property
    def display_effect(self) -> str:
        return self.actor_action_object or self.effect.value


RELATION_PATTERNS: tuple[tuple[ClaimRelation, str], ...] = (
    (ClaimRelation.PREVENTS, r"prevents?|stops?|blocks?|constrains?|restricts?"),
    (ClaimRelation.CAUSES, r"causes?|creates?|drives?|fuels?|leads?\s+to|results?\s+in|guarantees?"),
    (ClaimRelation.INCREASES, r"increases?|escalates?|expands?|worsens?"),
    (ClaimRelation.DECREASES, r"decreases?|reduces?|lowers?|mitigates?"),
    (ClaimRelation.ENABLES, r"enables?|allows?|empowers?"),
    (ClaimRelation.UNDERMINES, r"undermines?|deletes?|destroys?|harms?|hurts?"),
    (ClaimRelation.SOLVES, r"solves?|fixes?|resolves?"),
    (ClaimRelation.PROTECTS, r"protects?|preserves?|safeguards?"),
    (ClaimRelation.DETERS, r"deters?|discourages?"),
)
RELATION_RE = re.compile(
    r"\b(?P<relation>"
    + "|".join(f"(?:{pattern})" for _, pattern in RELATION_PATTERNS)
    + r")\b",
    re.IGNORECASE,
)
FROM_ACTION_RE = re.compile(
    r"^(?P<actor>[A-Z][A-Za-z0-9'’-]*(?:\s+[A-Z][A-Za-z0-9'’-]*)?|"
    r"presidents?|executives?|congress|courts?|military|leaders?)\s+"
    r"from\s+(?P<action>[A-Za-z'’-]+)\s+(?P<object>.+)$",
    re.IGNORECASE,
)
ACTOR_ACTION_RE = re.compile(
    r"^(?P<actor>[A-Z][A-Za-z0-9'’-]*(?:\s+[A-Z][A-Za-z0-9'’-]*)?|"
    r"presidents?|executives?|congress|courts?|military|leaders?)\s+"
    r"(?P<action>[A-Za-z'’-]+(?:ing|e|es|s)?)\s+(?P<object>.+)$",
    re.IGNORECASE,
)


def parse_structured_claim(text: str) -> StructuredClaim:
    raw = " ".join(text.split()).strip(" .")
    match = RELATION_RE.search(raw)
    if not match:
        return _unknown_claim(raw)

    subject = raw[: match.start()].strip(" ,.;:")
    effect = raw[match.end() :].strip(" ,.;:")
    relation_text = match.group("relation")
    relation = _normalize_relation(relation_text)
    target_actor, target_action, target_object, slot_confidence = _parse_effect(effect)
    confidence = _claim_confidence(subject, effect, relation, slot_confidence)
    return StructuredClaim(
        raw=raw,
        subject=ClaimSlot(subject, 0.92 if subject else 0.0),
        relation=relation,
        relation_text=relation_text,
        effect=ClaimSlot(effect, 0.9 if effect else 0.0),
        target_actor=ClaimSlot(target_actor, slot_confidence if target_actor else 0.0),
        target_action=ClaimSlot(target_action, slot_confidence if target_action else 0.0),
        target_object=ClaimSlot(target_object, slot_confidence if target_object else 0.0),
        confidence=confidence,
    )


def _unknown_claim(raw: str) -> StructuredClaim:
    return StructuredClaim(
        raw=raw,
        subject=ClaimSlot(raw, 0.2 if raw else 0.0),
        relation=ClaimRelation.UNKNOWN,
        relation_text="",
        effect=ClaimSlot("", 0.0),
        target_actor=ClaimSlot("", 0.0),
        target_action=ClaimSlot("", 0.0),
        target_object=ClaimSlot("", 0.0),
        confidence=0.2 if raw else 0.0,
    )


def _normalize_relation(text: str) -> ClaimRelation:
    lowered = text.lower()
    for relation, pattern in RELATION_PATTERNS:
        if re.fullmatch(pattern, lowered, flags=re.IGNORECASE):
            return relation
    return ClaimRelation.UNKNOWN


def _parse_effect(effect: str) -> tuple[str, str, str, float]:
    text = effect.strip(" .")
    from_match = FROM_ACTION_RE.match(text)
    if from_match:
        return (
            from_match.group("actor"),
            _normalize_action(from_match.group("action")),
            from_match.group("object").strip(" ."),
            0.92,
        )
    action_match = ACTOR_ACTION_RE.match(text)
    if action_match:
        return (
            action_match.group("actor"),
            _normalize_action(action_match.group("action")),
            action_match.group("object").strip(" ."),
            0.72,
        )
    return "", "", text, 0.42 if text else 0.0


def _claim_confidence(
    subject: str,
    effect: str,
    relation: ClaimRelation,
    slot_confidence: float,
) -> float:
    if relation == ClaimRelation.UNKNOWN:
        return 0.2
    score = 0.35
    if subject:
        score += 0.2
    if effect:
        score += 0.2
    score += min(0.25, slot_confidence * 0.25)
    return round(min(1.0, score), 3)


def _normalize_action(action: str) -> str:
    lowered = action.lower().strip(" .")
    irregular = {
        "escalating": "escalate",
        "deescalating": "de-escalate",
        "using": "use",
        "striking": "strike",
        "launching": "launch",
        "checking": "check",
    }
    if lowered in irregular:
        return irregular[lowered]
    if lowered.endswith("ing") and len(lowered) > 5:
        return lowered[:-3]
    if lowered.endswith("es") and len(lowered) > 4:
        return lowered[:-2]
    if lowered.endswith("s") and len(lowered) > 3:
        return lowered[:-1]
    return lowered


def _inflect_action(action: str) -> str:
    if not action:
        return ""
    if action.endswith("e"):
        return action[:-1] + "ing"
    return action + "ing"
