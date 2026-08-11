"""Deterministic retrieval probes for perspective-aware debate search."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.rag.relevance import _terms

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
        probes.extend(_answer_side_probes(parts, claim))

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


def _answer_side_probes(parts: ClaimParts, claim: str) -> list[RetrievalProbe]:
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
