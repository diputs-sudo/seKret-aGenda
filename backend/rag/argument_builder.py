"""Build coherent argument bundles from retrieved evidence cards."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .mechanism import parse_mechanism
from .query_intent import QueryIntent, parse_query_intent
from .relevance import _highlight_text, _terms

MECHANISM_CLUSTER_TERMS = {
    "artificial_intelligence",
    "behavioral_tracking",
    "personalization_targeting",
    "engagement_retention",
    "optimization",
    "revenue_profit",
    "wagering",
    "platform_operator",
}


@dataclass(frozen=True)
class ArgumentCluster:
    id: str
    section: str
    thesis: str
    cards: list[dict[str, Any]]
    supporting_claims: list[str]
    confidence: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ArgumentBundle:
    query: str
    opponent_claim: str | None
    main_claim: str
    warrants: list[str]
    cards: list[dict[str, Any]]
    clusters: list[ArgumentCluster]
    source_status: str
    uncertainty: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["clusters"] = [cluster.to_dict() for cluster in self.clusters]
        return data


@dataclass(frozen=True)
class GeneratedClaim:
    text: str
    supporting_card_ids: list[str]
    source_status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceIntegrityReport:
    source_status: str
    valid_citations: list[str] = field(default_factory=list)
    invalid_citations: list[str] = field(default_factory=list)
    generated_claims: list[GeneratedClaim] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["generated_claims"] = [claim.to_dict() for claim in self.generated_claims]
        return data


class ArgumentBuilder:
    def build(
        self,
        query_or_intent: QueryIntent | str,
        cards: list[dict[str, Any]],
        limit: int = 5,
    ) -> ArgumentBundle:
        intent = (
            parse_query_intent(query_or_intent)
            if isinstance(query_or_intent, str)
            else query_or_intent
        )
        clusters = cluster_arguments(cards, intent)
        selected = select_diverse_cards(clusters, limit=limit)
        main_cluster = clusters[0] if clusters else None
        warrants = _warrants(selected)
        main_claim = _main_claim(intent, main_cluster, warrants)
        source_status = "BACKFILE-SOURCED" if selected else "ANALYSIS ONLY"
        uncertainty = None if selected else "No retrieved cards passed the relevance gate."
        return ArgumentBundle(
            query=intent.raw_query,
            opponent_claim=intent.opponent_claim,
            main_claim=main_claim,
            warrants=warrants,
            cards=selected,
            clusters=clusters,
            source_status=source_status,
            uncertainty=uncertainty,
        )


def cluster_arguments(
    cards: list[dict[str, Any]],
    intent: QueryIntent | None = None,
) -> list[ArgumentCluster]:
    grouped: list[list[dict[str, Any]]] = []
    for card in cards:
        for group in grouped:
            if _cluster_similarity(card, group) >= 0.22:
                group.append(card)
                break
        else:
            grouped.append([card])

    clusters = []
    for index, group in enumerate(grouped, start=1):
        ordered = sorted(group, key=_card_score, reverse=True)
        clusters.append(
            ArgumentCluster(
                id=f"cluster-{index}",
                section=str(ordered[0].get("section") or ""),
                thesis=_cluster_thesis(ordered),
                cards=ordered,
                supporting_claims=_supporting_claims(ordered),
                confidence=_cluster_confidence(ordered, intent),
            )
        )
    clusters.sort(key=lambda cluster: cluster.confidence, reverse=True)
    return clusters


def select_diverse_cards(
    clusters: list[ArgumentCluster],
    limit: int = 5,
    lambda_relevance: float = 0.75,
) -> list[dict[str, Any]]:
    cluster_score_by_card = {
        str(card.get("card_id")): cluster.confidence
        for cluster in clusters
        for card in cluster.cards
    }
    candidates = [card for cluster in clusters for card in cluster.cards]
    selected: list[dict[str, Any]] = []
    while candidates and len(selected) < limit:
        best = max(
            candidates,
            key=lambda card: _mmr_score(
                card,
                selected,
                lambda_relevance,
                cluster_score_by_card,
            ),
        )
        selected.append(best)
        candidates = [card for card in candidates if str(card.get("card_id")) != str(best.get("card_id"))]
    return selected


def validate_sources(answer: str, bundle: ArgumentBundle) -> SourceIntegrityReport:
    allowed = _citation_labels(bundle.cards)
    found = _citations_in_answer(answer, allowed)
    invalid = _unknown_citation_like_spans(answer, allowed)
    source_status = bundle.source_status
    if not bundle.cards:
        source_status = "ANALYSIS ONLY"
    claims = [
        GeneratedClaim(
            text=sentence,
            supporting_card_ids=[str(card.get("card_id")) for card in bundle.cards],
            source_status=source_status,
        )
        for sentence in _sentences(answer)
        if sentence
    ]
    return SourceIntegrityReport(
        source_status=source_status,
        valid_citations=sorted(found),
        invalid_citations=sorted(invalid),
        generated_claims=claims,
    )


def _cluster_thesis(cards: list[dict[str, Any]]) -> str:
    for card in cards:
        tag = str(card.get("tag") or "").strip()
        if tag:
            return tag
    return "Retrieved evidence supports a related response."


def _supporting_claims(cards: list[dict[str, Any]]) -> list[str]:
    claims = []
    for card in cards:
        tag = str(card.get("tag") or "").strip()
        if tag and tag not in claims:
            claims.append(tag)
    return claims


def _cluster_confidence(
    cards: list[dict[str, Any]],
    intent: QueryIntent | None = None,
) -> float:
    if not cards:
        return 0.0
    top3 = sorted((_card_score(card) for card in cards), reverse=True)[:3]
    average_top3 = sum(top3) / len(top3)
    size_bonus = min(0.12, 0.035 * max(len(cards) - 1, 0))
    authors = {str(card.get("author") or card.get("card_name") or "") for card in cards}
    documents = {str(card.get("document") or "") for card in cards}
    diversity_bonus = min(0.08, 0.02 * (len(authors) - 1) + 0.02 * (len(documents) - 1))
    query_bonus = _query_cluster_bonus(cards, intent)
    return round(min(1.0, average_top3 + size_bonus + diversity_bonus + query_bonus), 3)


def _query_cluster_bonus(cards: list[dict[str, Any]], intent: QueryIntent | None) -> float:
    if intent is None:
        return 0.0
    query_text = intent.opponent_claim or intent.search_text or intent.raw_query
    query_terms = _card_like_terms(query_text)
    if not query_terms:
        return 0.0
    cluster_terms = set()
    for card in cards:
        cluster_terms.update(_card_terms(card))
    overlap = len(query_terms & cluster_terms) / len(query_terms)
    return min(0.22, overlap * 0.22)


def _card_score(card: dict[str, Any]) -> float:
    return float(
        card.get("reranker_score")
        or card.get("relevance_score")
        or card.get("retrieval_score")
        or card.get("score")
        or 0
    )


def _mmr_score(
    card: dict[str, Any],
    selected: list[dict[str, Any]],
    lambda_relevance: float,
    cluster_score_by_card: dict[str, float],
) -> float:
    relevance = (
        _card_score(card) * 0.6
        + cluster_score_by_card.get(str(card.get("card_id")), 0.0) * 0.4
    )
    redundancy = max((_similarity(card, other) for other in selected), default=0.0)
    return lambda_relevance * relevance - (1.0 - lambda_relevance) * redundancy


def _cluster_similarity(card: dict[str, Any], group: list[dict[str, Any]]) -> float:
    return max((_similarity(card, other) for other in group), default=0.0)


def _similarity(left: dict[str, Any], right: dict[str, Any]) -> float:
    left_terms = _card_terms(left)
    right_terms = _card_terms(right)
    if not left_terms or not right_terms:
        return 0.0
    lexical = len(left_terms & right_terms) / len(left_terms | right_terms)
    same_author = str(left.get("author") or left.get("card_name") or "") == str(
        right.get("author") or right.get("card_name") or ""
    )
    same_document = str(left.get("document") or "") == str(right.get("document") or "")
    same_section = str(left.get("section") or "") == str(right.get("section") or "")
    mechanism_overlap = bool(
        (left_terms & MECHANISM_CLUSTER_TERMS)
        & (right_terms & MECHANISM_CLUSTER_TERMS)
    )
    mechanism_bonus = 0.22 if same_section and mechanism_overlap else 0.0
    return min(
        1.0,
        lexical
        + (0.15 if same_author else 0)
        + (0.1 if same_document else 0)
        + mechanism_bonus,
    )


def _card_terms(card: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(part)
        for part in [
            card.get("section"),
            card.get("tag"),
            _highlight_text(card),
            card.get("body") or card.get("body_preview"),
        ]
        if part
    )
    mechanism = parse_mechanism(text)
    return _terms(text) | mechanism.object_groups | mechanism.phrase_concepts


def _card_like_terms(text: str) -> set[str]:
    mechanism = parse_mechanism(text)
    return (_terms(text) | mechanism.object_groups | mechanism.phrase_concepts) - mechanism.generic_terms


def _warrants(cards: list[dict[str, Any]]) -> list[str]:
    warrants = []
    for card in cards:
        highlights = card.get("highlights") or []
        text = ""
        if highlights:
            text = str(highlights[0].get("text") or "").strip()
        if not text:
            text = str(card.get("tag") or "").strip()
        if text and text not in warrants:
            warrants.append(text)
    return warrants


def _main_claim(
    intent: QueryIntent,
    cluster: ArgumentCluster | None,
    warrants: list[str],
) -> str:
    if cluster:
        return cluster.thesis
    if intent.opponent_claim:
        return f"No backfile evidence passed the gate for: {intent.opponent_claim}"
    if warrants:
        return warrants[0]
    return "No backfile evidence passed the gate."


def _citation_labels(cards: list[dict[str, Any]]) -> set[str]:
    labels = set()
    for card in cards:
        for key in ("card_name", "citation"):
            value = str(card.get(key) or "").strip()
            if value:
                labels.add(value)
    return labels


def _citations_in_answer(answer: str, allowed: set[str]) -> set[str]:
    return {label for label in allowed if label and label in answer}


def _unknown_citation_like_spans(answer: str, allowed: set[str]) -> set[str]:
    allowed_short = {label.split(",")[0].strip() for label in allowed}
    spans = set(re.findall(r"\b[A-Z][A-Za-z'’-]{2,}\s+(?:\d{4}|[’']\d{2}|\d{2})\b", answer))
    return {span for span in spans if span not in allowed and span not in allowed_short}


def _sentences(answer: str) -> list[str]:
    body = answer.partition("Sources:")[0]
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", body) if part.strip()]
