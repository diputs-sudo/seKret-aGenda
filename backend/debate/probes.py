"""Deterministic retrieval probes for perspective-aware debate search."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.rag.relevance import _terms

from .claims import ClaimRelation, StructuredClaim, parse_structured_claim
from .model import DebateIntent, DebateQuery


@dataclass(frozen=True)
class RetrievalProbe:
    kind: str
    text: str
    purpose: str
    channel: str = "both"


CAUSAL_VERB_RE = re.compile(
    r"\b(?:causes?|creates?|deletes?|destroys?|drives?|fuels?|guarantees?|"
    r"harms?|hurts?|increases?|leads?\s+to|lowers?|prevents?|reduces?|"
    r"solves?|strengthens?|undermines?|worsens?)\b",
    re.IGNORECASE,
)


OPPOSITE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(rf"\b{source}\b", re.IGNORECASE), replacement)
    for source, replacement in [
        ("causes?", "does not cause"),
        ("creates?", "does not create"),
        ("deletes?", "preserves improves"),
        ("destroys?", "preserves improves"),
        ("escalates?", "de-escalates stabilizes"),
        ("guarantees?", "does not guarantee"),
        ("harms?", "helps protects"),
        ("hurts?", "helps protects"),
        ("increases?", "decreases reduces"),
        ("lowers?", "raises increases"),
        ("prevents?", "allows enables"),
        ("reduces?", "increases restores"),
        ("solves?", "fails to solve"),
        ("strengthens?", "weakens undermines"),
        ("undermines?", "strengthens protects"),
        ("worsens?", "improves mitigates"),
    ]
)


def build_retrieval_probes(query: DebateQuery) -> list[RetrievalProbe]:
    """Build broad candidate-generation probes without using an LLM."""
    claim = query.opponent_claim or query.semantic_query
    structured_claim = parse_structured_claim(claim)
    probes = [
        RetrievalProbe(
            kind="original",
            text=claim,
            purpose="literal claim and opponent evidence",
            channel="both",
        )
    ]

    parts = _claim_parts(claim)
    for lexical in _lexical_probes(parts):
        if lexical.lower() != claim.lower():
            probes.append(
                RetrievalProbe(
                    kind="lexical",
                    text=lexical,
                    purpose="compact FTS query over the claim's core terms",
                    channel="lexical",
                )
            )

    mechanism = _mechanism_probe(parts)
    if mechanism and mechanism.lower() != claim.lower():
        probes.append(
            RetrievalProbe(
                kind="mechanism",
                text=mechanism,
                purpose="same actors/mechanism with less sentence noise",
                channel="both",
            )
        )

    if query.intent in {DebateIntent.ANSWER, DebateIntent.TURN, DebateIntent.INDICT}:
        probes.extend(_answer_side_probes(parts, claim, structured_claim))

    return _dedupe_probes(probes)


@dataclass(frozen=True)
class ClaimParts:
    claim: str
    subject: str
    outcome: str
    terms: list[str]


def _claim_parts(text: str) -> ClaimParts:
    compact = " ".join(text.split()).strip(" .")
    match = CAUSAL_VERB_RE.search(compact)
    if match:
        subject = compact[: match.start()].strip(" ,.;:")
        outcome = compact[match.end() :].strip(" ,.;:")
    else:
        terms = _ordered_terms(compact)
        midpoint = max(1, len(terms) // 2)
        subject = " ".join(terms[:midpoint])
        outcome = " ".join(terms[midpoint:])
    return ClaimParts(
        claim=compact,
        subject=subject or compact,
        outcome=outcome or compact,
        terms=_ordered_terms(compact),
    )


def _lexical_probes(parts: ClaimParts) -> list[str]:
    subject_terms = _ordered_terms(parts.subject)
    outcome_terms = _ordered_terms(parts.outcome)
    probes = [
        " ".join(parts.terms[:8]),
        " ".join(subject_terms[:4] + outcome_terms[:4]),
        " ".join(subject_terms[-3:] + outcome_terms[:4]),
    ]
    return [probe for probe in probes if probe]


def _mechanism_probe(parts: ClaimParts) -> str:
    subject_terms = _ordered_terms(parts.subject)
    outcome_terms = _ordered_terms(parts.outcome)
    terms = subject_terms + [term for term in outcome_terms if term not in subject_terms]
    return " ".join(terms[:10]).strip()


def _counterclaim(text: str) -> str:
    rewritten = text
    changed = False
    for pattern, replacement in OPPOSITE_PATTERNS:
        rewritten, count = pattern.subn(replacement, rewritten)
        changed = changed or count > 0
    if changed:
        return " ".join(rewritten.split())
    return f"not {text}"


def _answer_side_probes(
    parts: ClaimParts,
    claim: str,
    structured_claim: StructuredClaim,
) -> list[RetrievalProbe]:
    if structured_claim.has_structure:
        return _structured_answer_side_probes(structured_claim)
    return _legacy_answer_side_probes(parts, claim)


def _structured_answer_side_probes(claim: StructuredClaim) -> list[RetrievalProbe]:
    if claim.relation == ClaimRelation.PREVENTS:
        return _prevents_answer_side_probes(claim)
    if claim.relation in {ClaimRelation.CAUSES, ClaimRelation.INCREASES, ClaimRelation.ENABLES}:
        return _causes_answer_side_probes(claim)
    if claim.relation in {ClaimRelation.UNDERMINES, ClaimRelation.DECREASES}:
        return _undermines_answer_side_probes(claim)
    return _generic_structured_answer_side_probes(claim)


def _prevents_answer_side_probes(claim: StructuredClaim) -> list[RetrievalProbe]:
    subject = _congressionalize(claim.subject.value)
    actor = claim.target_actor.value
    action = claim.target_action.value
    obj = claim.target_object.value
    effect = claim.actor_action_object
    prevention_effect = claim.effect.value or effect
    actor_possessive = _possessive(actor)
    return [
        RetrievalProbe(
            kind="denial",
            text=f"{subject} does not prevent {prevention_effect}",
            purpose="logical denial of the prevention claim",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="turn",
            text=f"{subject} increases or enables {effect}",
            purpose="cards that say the prevention claim is backwards",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="circumvention",
            text=f"{actor} can {action} {obj} despite {subject}",
            purpose="cards about bypassing the alleged constraint",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="no_link",
            text=f"{subject} does not meaningfully constrain {actor_possessive} ability to {action} {obj}",
            purpose="cards that sever the claimed prevention mechanism",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="non_unique",
            text=f"{actor} is already constrained from {_gerund(claim.target_action.value)} {obj} independently of {subject}",
            purpose="cards that say the claimed restraint exists without the plan",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="alt_cause",
            text=f"other institutional or strategic constraints determine {actor_possessive} ability to {action} {obj} rather than {subject}",
            purpose="cards that identify an alternative mechanism",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="mitigation",
            text=f"{subject} only partially reduces {actor_possessive} ability to {action} {obj}",
            purpose="cards that mitigate the claimed restraint",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="indict",
            text=f"claims that {subject} restrains presidential {obj} overstate Congress's ability to constrain presidential action",
            purpose="cards that indict the warrant or evidence",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="empirical_denial",
            text=f"congressional authorization or oversight has failed to prevent presidential military escalation",
            purpose="empirical cards against congressional restraint",
            channel="semantic",
        ),
    ]


def _causes_answer_side_probes(claim: StructuredClaim) -> list[RetrievalProbe]:
    subject = claim.subject.value
    effect = claim.actor_action_object
    return [
        RetrievalProbe("denial", f"{subject} does not cause {effect}", "logical denial of the causal claim", "semantic"),
        RetrievalProbe("turn", f"{subject} reduces or prevents {effect}", "cards that reverse the claimed causal direction", "semantic"),
        RetrievalProbe("alt_cause", f"other causes produce {effect} rather than {subject}", "cards that identify an alternative cause", "semantic"),
        RetrievalProbe("non_unique", f"{effect} already occurs independently of {subject}", "cards that say the impact is non-unique", "semantic"),
        RetrievalProbe("mitigation", f"{subject} has only a small effect on {effect}", "cards that minimize the causal link", "semantic"),
        RetrievalProbe("indict", f"claims that {subject} causes {effect} lack evidence and overstate the causal relationship", "cards that indict the warrant", "semantic"),
    ]


def _undermines_answer_side_probes(claim: StructuredClaim) -> list[RetrievalProbe]:
    subject = claim.subject.value
    effect = claim.actor_action_object
    return [
        RetrievalProbe("denial", f"{subject} does not undermine {effect}", "logical denial of the claim", "semantic"),
        RetrievalProbe("turn", f"{subject} protects or strengthens {effect}", "cards that reverse the claimed harm", "semantic"),
        RetrievalProbe("no_link", f"{subject} does not determine {effect}", "cards that sever the claimed link", "semantic"),
        RetrievalProbe("alt_cause", f"other factors undermine {effect} rather than {subject}", "cards that identify an alternative cause", "semantic"),
        RetrievalProbe("mitigation", f"{subject} only partially affects {effect}", "cards that mitigate the link", "semantic"),
        RetrievalProbe("indict", f"claims that {subject} undermines {effect} lack evidence and overstate the causal relationship", "cards that indict the warrant", "semantic"),
    ]


def _generic_structured_answer_side_probes(claim: StructuredClaim) -> list[RetrievalProbe]:
    subject = claim.subject.value
    effect = claim.actor_action_object or claim.effect.value
    relation = claim.relation_text or "causes"
    return [
        RetrievalProbe("denial", f"{subject} does not {relation} {effect}", "logical denial of the claim", "semantic"),
        RetrievalProbe("no_link", f"{subject} does not determine {effect}", "cards that sever the claimed link", "semantic"),
        RetrievalProbe("alt_cause", f"other factors determine {effect} rather than {subject}", "cards that identify an alternative cause", "semantic"),
        RetrievalProbe("mitigation", f"{subject} only partially affects {effect}", "cards that mitigate the link", "semantic"),
        RetrievalProbe("indict", f"claims about {subject} and {effect} lack evidence and overstate the relationship", "cards that indict the warrant", "semantic"),
    ]


def _legacy_answer_side_probes(parts: ClaimParts, claim: str) -> list[RetrievalProbe]:
    subject = parts.subject
    outcome = parts.outcome
    counterclaim = _counterclaim(claim)
    return [
        RetrievalProbe(
            kind="counterclaim",
            text=counterclaim,
            purpose="proposition likely used by direct answer cards",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="turn",
            text=f"{subject} improves {outcome} and creates reasons the claimed harm is reversed",
            purpose="cards that say the claim is backwards",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="no_link",
            text=f"{subject} does not determine {outcome} and the claimed causal link is weak",
            purpose="cards that sever the claimed causal chain",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="non_unique",
            text=f"{outcome} already exists independently of {subject}",
            purpose="cards that say the harm is already happening",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="mitigation",
            text=f"{subject} mitigates reduces or prevents the claimed harm to {outcome}",
            purpose="cards that reduce or sever the claimed link",
            channel="semantic",
        ),
        RetrievalProbe(
            kind="indict",
            text=f"claims that {subject} causes {outcome} lack evidence and overstate the causal relationship",
            purpose="cards that indict the warrant or evidence",
            channel="semantic",
        ),
    ]


def _congressionalize(text: str) -> str:
    lowered = text.lower()
    if "congress" in lowered and "congressional" not in lowered:
        return re.sub(r"\bCongress\b", "Congressional", text, flags=re.IGNORECASE)
    return text


def _possessive(actor: str) -> str:
    if not actor:
        return "their"
    if actor.lower().endswith("s"):
        return f"{actor}'"
    return f"{actor}'s"


def _gerund(action: str) -> str:
    if not action:
        return ""
    if action.endswith("e"):
        return action[:-1] + "ing"
    return action + "ing"


def _dedupe_probes(probes: list[RetrievalProbe]) -> list[RetrievalProbe]:
    seen: set[str] = set()
    unique: list[RetrievalProbe] = []
    for probe in probes:
        text = " ".join(probe.text.split())
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        unique.append(RetrievalProbe(probe.kind, text, probe.purpose, probe.channel))
    return unique


def _ordered_terms(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    valid_terms = _terms(text)
    for token in re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)?", text):
        lowered = token.lower()
        if lowered not in valid_terms:
            continue
        if lowered in seen:
            continue
        seen.add(lowered)
        ordered.append(lowered)
    return ordered
