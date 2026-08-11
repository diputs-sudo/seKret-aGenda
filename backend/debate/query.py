"""Deterministic parser for debate-control language."""

from __future__ import annotations

import re

from backend.rag.mechanism import extract_phrase_concepts
from backend.rag.relevance import _terms

from .claims import parse_structured_claim
from .model import DebateIntent, DebateQuery, Perspective

COMMAND_RE = re.compile(r"^\s*(?P<command>[a-z-]+)>\s*(?P<body>.+)$", re.IGNORECASE)
OPPONENT_CLAIM_RE = re.compile(
    r"^\s*(?:opponent|opponents|they|other team)\s+"
    r"(?P<verb>says?|argues?|claims?|contends?)\s+",
    re.IGNORECASE,
)

COMMAND_INTENTS = {
    "answer": DebateIntent.ANSWER,
    "their": DebateIntent.THEIR_EVIDENCE,
    "compare": DebateIntent.COMPARE,
    "turn": DebateIntent.TURN,
    "indict": DebateIntent.INDICT,
    "search": DebateIntent.SEARCH,
}


def parse_debate_query(raw: str) -> DebateQuery:
    text = " ".join(raw.split())
    command_match = COMMAND_RE.match(text)
    command = command_match.group("command").lower() if command_match else ""
    body = command_match.group("body").strip() if command_match else text
    control_language = []
    if command:
        control_language.append(f"{command}>")

    opponent_match = OPPONENT_CLAIM_RE.match(body)
    opponent_claim = None
    if opponent_match:
        control_language.append(opponent_match.group(0).strip())
        opponent_claim = OPPONENT_CLAIM_RE.sub("", body).strip(" .")

    intent = COMMAND_INTENTS.get(command) or (
        DebateIntent.ANSWER if opponent_claim else DebateIntent.SEARCH
    )
    perspective = _perspective(intent=intent, opponent_claim=opponent_claim)
    semantic_query = opponent_claim or body
    structured_claim = parse_structured_claim(semantic_query)

    return DebateQuery(
        raw=raw,
        semantic_query=semantic_query,
        perspective=perspective,
        intent=intent,
        opponent_claim=opponent_claim,
        topics=sorted(_terms(semantic_query)),
        mechanisms=sorted(extract_phrase_concepts(semantic_query)),
        control_language=control_language,
        claim_structure=structured_claim.to_dict(),
    )


def _perspective(
    *,
    intent: DebateIntent,
    opponent_claim: str | None,
) -> Perspective:
    if intent in {DebateIntent.ANSWER, DebateIntent.TURN, DebateIntent.INDICT}:
        return Perspective.OPPONENT
    if intent == DebateIntent.THEIR_EVIDENCE:
        return Perspective.OPPONENT
    if intent == DebateIntent.COMPARE:
        return Perspective.BOTH
    if opponent_claim:
        return Perspective.OPPONENT
    return Perspective.NEUTRAL
