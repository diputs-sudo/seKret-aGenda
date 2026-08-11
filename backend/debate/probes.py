"""Deterministic retrieval probes for perspective-aware debate search."""

from __future__ import annotations

import re
from dataclasses import dataclass

from backend.rag.mechanism import extract_phrase_concepts
from backend.rag.relevance import _terms

from .model import DebateIntent, DebateQuery


@dataclass(frozen=True)
class RetrievalProbe:
    kind: str
    text: str
    purpose: str


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
        )
    ]

    mechanism = _mechanism_probe(claim)
    if mechanism and mechanism.lower() != claim.lower():
        probes.append(
            RetrievalProbe(
                kind="mechanism",
                text=mechanism,
                purpose="same actors/mechanism with less sentence noise",
            )
        )

    if query.intent in {DebateIntent.ANSWER, DebateIntent.TURN, DebateIntent.INDICT}:
        counterclaim = _counterclaim(claim)
        if counterclaim.lower() != claim.lower():
            probes.append(
                RetrievalProbe(
                    kind="counterclaim",
                    text=counterclaim,
                    purpose="language likely used by opposing answer cards",
                )
            )
        probes.extend(_attack_probes(claim))

    return _dedupe_probes(probes)


def _mechanism_probe(text: str) -> str:
    phrases = sorted(
        {phrase.replace("_", " ") for phrase in extract_phrase_concepts(text)},
        key=lambda item: (-len(item), item),
    )
    terms = sorted(_terms(text))
    phrase_terms = set(" ".join(phrases).split())
    parts = phrases + [term for term in terms if term not in phrase_terms]
    return " ".join(parts[:14]).strip()


def _counterclaim(text: str) -> str:
    rewritten = text
    changed = False
    for pattern, replacement in OPPOSITE_PATTERNS:
        rewritten, count = pattern.subn(replacement, rewritten)
        changed = changed or count > 0
    if changed:
        return " ".join(rewritten.split())
    return f"not {text}"


def _attack_probes(text: str) -> list[RetrievalProbe]:
    mechanism = _mechanism_probe(text) or text
    return [
        RetrievalProbe(
            kind="non_unique",
            text=f"already status quo non unique {mechanism}",
            purpose="cards that say the harm is already happening",
        ),
        RetrievalProbe(
            kind="mitigation",
            text=f"mitigates reduces prevents no link {mechanism}",
            purpose="cards that reduce or sever the claimed link",
        ),
        RetrievalProbe(
            kind="indict",
            text=f"flawed assumes no evidence overstates {mechanism}",
            purpose="cards that indict the warrant or evidence",
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
        unique.append(RetrievalProbe(probe.kind, text, probe.purpose))
    return unique
