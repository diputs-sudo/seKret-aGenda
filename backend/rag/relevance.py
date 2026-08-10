"""Temporary lexical relevance gate for retrieved cards.

This is scaffolding until a trained reranker or relevance classifier is added.
It prevents obviously off-target cards from surviving just because they share a
section or a high first-pass retrieval score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "because",
    "by",
    "for",
    "from",
    "how",
    "in",
    "is",
    "it",
    "of",
    "on",
    "or",
    "says",
    "that",
    "the",
    "this",
    "to",
    "with",
    "what",
    "why",
}

SEMANTIC_STOPWORDS = {
    "able",
    "become",
    "becomes",
    "became",
    "do",
    "does",
    "did",
    "doing",
    "get",
    "gets",
    "got",
    "give",
    "gives",
    "given",
    "make",
    "makes",
    "made",
    "provide",
    "provides",
    "provided",
    "show",
    "shows",
    "showing",
    "use",
    "uses",
    "used",
    "using",
}

@dataclass(frozen=True)
class RerankResult:
    card: dict[str, Any]
    relevance_score: float


class RelevanceReranker:
    def __init__(self, threshold: float = 2.0):
        self.threshold = threshold

    def rerank(
        self, query: str, cards: list[dict[str, Any]], limit: int = 3
    ) -> list[dict[str, Any]]:
        scored = []
        for card in cards:
            score = self.score(query, card)
            if score >= self.threshold:
                enriched = dict(card)
                enriched["relevance_score"] = round(score, 3)
                scored.append(RerankResult(enriched, score))

        scored.sort(
            key=lambda item: (
                item.relevance_score,
                float(item.card.get("score", 0)),
            ),
            reverse=True,
        )

        selected = []
        seen: set[tuple[str, str]] = set()
        for item in scored:
            key = (str(item.card.get("section")), str(item.card.get("tag")))
            if key in seen:
                continue
            seen.add(key)
            selected.append(item.card)
            if len(selected) >= limit:
                break
        return selected

    def score(self, query: str, card: dict[str, Any]) -> float:
        query_terms = _expanded_terms(query)
        if not query_terms:
            return 0.0

        tag_terms = _terms(str(card.get("tag") or ""))
        section_terms = _terms(str(card.get("section") or card.get("section_name") or ""))
        highlight_terms = _terms(_highlight_text(card))
        card_terms = tag_terms | section_terms | highlight_terms
        if not _covers_query_concepts(query, card_terms):
            return 0.0

        tag_hits = len(query_terms & tag_terms)
        highlight_hits = len(query_terms & highlight_terms)
        section_hits = len(query_terms & section_terms)
        return tag_hits * 3.0 + highlight_hits * 1.5 + section_hits * 0.5


def _expanded_terms(query: str) -> set[str]:
    return _terms(query)


def _covers_query_concepts(query: str, card_terms: set[str]) -> bool:
    query_terms = _terms(query)
    if not query_terms:
        return False
    return bool(query_terms & card_terms)


def _terms(text: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)?", text)
        if token.lower() not in STOPWORDS
        and token.lower() not in SEMANTIC_STOPWORDS
    }


def _highlight_text(card: dict[str, Any]) -> str:
    highlights = card.get("highlights") or []
    if highlights:
        return " ".join(str(item.get("text", "")) for item in highlights)
    metadata = card.get("metadata") or {}
    return str(metadata.get("highlight_text") or "")
