"""Build coherent argument bundles from retrieved evidence cards."""

from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass, field
from typing import Any

from .mechanism import parse_mechanism
from .query_intent import QueryIntent, parse_query_intent
from .relevance import _highlight_text, _terms

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
    def __init__(self):
        self.last_debug: dict[str, Any] = {}

    def build(
        self,
        query_or_intent: QueryIntent | str,
        cards: list[dict[str, Any]],
        limit: int = 5,
    ) -> ArgumentBundle:
        started_total = time.perf_counter()
        stats: dict[str, Any] = {
            "input_cards": len(cards),
            "unique_evidence": len({_evidence_key(card) for card in cards}),
            "term_cache_hits": 0,
            "term_cache_misses": 0,
            "phrase_cache_hits": 0,
            "phrase_cache_misses": 0,
            "pair_comparisons": 0,
        }
        cache = _BuildCache()
        started = time.perf_counter()
        intent = (
            parse_query_intent(query_or_intent)
            if isinstance(query_or_intent, str)
            else query_or_intent
        )
        timings = {"parse_intent": _elapsed_ms(started)}
        started = time.perf_counter()
        clusters = cluster_arguments(cards, intent, cache=cache, stats=stats)
        timings["cluster"] = _elapsed_ms(started)
        stats["clusters"] = len(clusters)
        started = time.perf_counter()
        selected = select_diverse_cards(
            clusters,
            limit=limit,
            cache=cache,
            stats=stats,
        )
        timings["select"] = _elapsed_ms(started)
        stats["selected_cards"] = len(selected)
        main_cluster = clusters[0] if clusters else None
        started = time.perf_counter()
        warrants = _warrants(selected)
        timings["warrants"] = _elapsed_ms(started)
        started = time.perf_counter()
        main_claim = _main_claim(intent, main_cluster, warrants)
        timings["main_claim"] = _elapsed_ms(started)
        source_status = "BACKFILE-SOURCED" if selected else "ANALYSIS ONLY"
        uncertainty = None if selected else "No retrieved cards passed the relevance gate."
        started = time.perf_counter()
        bundle = ArgumentBundle(
            query=intent.raw_query,
            opponent_claim=intent.opponent_claim,
            main_claim=main_claim,
            warrants=warrants,
            cards=selected,
            clusters=clusters,
            source_status=source_status,
            uncertainty=uncertainty,
        )
        timings["construct"] = _elapsed_ms(started)
        timings["total"] = _elapsed_ms(started_total)
        self.last_debug = {
            "timings": timings,
            "stats": stats,
        }
        return bundle


def cluster_arguments(
    cards: list[dict[str, Any]],
    intent: QueryIntent | None = None,
    cache: "_BuildCache | None" = None,
    stats: dict[str, Any] | None = None,
) -> list[ArgumentCluster]:
    cache = cache or _BuildCache()
    stats = stats if stats is not None else {}
    grouped: list[list[dict[str, Any]]] = []
    for card in cards:
        for group in grouped:
            if _cluster_similarity(card, group, cache, stats) >= 0.22:
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
                confidence=_cluster_confidence(ordered, intent, cache, stats),
            )
        )
    clusters.sort(key=lambda cluster: cluster.confidence, reverse=True)
    return clusters


def select_diverse_cards(
    clusters: list[ArgumentCluster],
    limit: int = 5,
    lambda_relevance: float = 0.75,
    cache: "_BuildCache | None" = None,
    stats: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    cache = cache or _BuildCache()
    stats = stats if stats is not None else {}
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
                cache,
                stats,
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
    cache: "_BuildCache | None" = None,
    stats: dict[str, Any] | None = None,
) -> float:
    cache = cache or _BuildCache()
    stats = stats if stats is not None else {}
    if not cards:
        return 0.0
    top3 = sorted((_card_score(card) for card in cards), reverse=True)[:3]
    average_top3 = sum(top3) / len(top3)
    size_bonus = min(0.12, 0.035 * max(len(cards) - 1, 0))
    authors = {str(card.get("author") or card.get("card_name") or "") for card in cards}
    documents = {str(card.get("document") or "") for card in cards}
    diversity_bonus = min(0.08, 0.02 * (len(authors) - 1) + 0.02 * (len(documents) - 1))
    query_bonus = _query_cluster_bonus(cards, intent, cache, stats)
    return round(min(1.0, average_top3 + size_bonus + diversity_bonus + query_bonus), 3)


def _query_cluster_bonus(
    cards: list[dict[str, Any]],
    intent: QueryIntent | None,
    cache: "_BuildCache",
    stats: dict[str, Any],
) -> float:
    if intent is None:
        return 0.0
    query_text = intent.opponent_claim or intent.search_text or intent.raw_query
    query_terms = _card_like_terms(query_text)
    if not query_terms:
        return 0.0
    cluster_terms = set()
    for card in cards:
        cluster_terms.update(_card_terms(card, cache, stats))
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
    cache: "_BuildCache",
    stats: dict[str, Any],
) -> float:
    relevance = (
        _card_score(card) * 0.6
        + cluster_score_by_card.get(str(card.get("card_id")), 0.0) * 0.4
    )
    redundancy = max(
        (_similarity(card, other, cache, stats) for other in selected),
        default=0.0,
    )
    return lambda_relevance * relevance - (1.0 - lambda_relevance) * redundancy


def _cluster_similarity(
    card: dict[str, Any],
    group: list[dict[str, Any]],
    cache: "_BuildCache",
    stats: dict[str, Any],
) -> float:
    return max(
        (_similarity(card, other, cache, stats) for other in group),
        default=0.0,
    )


def _similarity(
    left: dict[str, Any],
    right: dict[str, Any],
    cache: "_BuildCache",
    stats: dict[str, Any],
) -> float:
    stats["pair_comparisons"] = int(stats.get("pair_comparisons") or 0) + 1
    left_terms = _card_terms(left, cache, stats)
    right_terms = _card_terms(right, cache, stats)
    if not left_terms or not right_terms:
        return 0.0
    lexical = len(left_terms & right_terms) / len(left_terms | right_terms)
    same_author = str(left.get("author") or left.get("card_name") or "") == str(
        right.get("author") or right.get("card_name") or ""
    )
    same_document = str(left.get("document") or "") == str(right.get("document") or "")
    same_section = str(left.get("section") or "") == str(right.get("section") or "")
    shared_phrases = _phrase_terms(left, cache, stats) & _phrase_terms(right, cache, stats)
    mechanism_bonus = 0.18 if same_section and shared_phrases else 0.0
    return min(
        1.0,
        lexical
        + (0.15 if same_author else 0)
        + (0.1 if same_document else 0)
        + mechanism_bonus,
    )


@dataclass
class _BuildCache:
    card_terms: dict[str, set[str]] = field(default_factory=dict)
    phrase_terms: dict[str, set[str]] = field(default_factory=dict)


def _card_terms(
    card: dict[str, Any],
    cache: _BuildCache | None = None,
    stats: dict[str, Any] | None = None,
) -> set[str]:
    cache = cache or _BuildCache()
    stats = stats if stats is not None else {}
    key = _evidence_key(card)
    cached = cache.card_terms.get(key)
    if cached is not None:
        stats["term_cache_hits"] = int(stats.get("term_cache_hits") or 0) + 1
        return cached
    stats["term_cache_misses"] = int(stats.get("term_cache_misses") or 0) + 1
    text = " ".join(
        str(part)
        for part in [
            card.get("section"),
            card.get("tag"),
            _highlight_text(card),
            _bundle_body_text(card),
        ]
        if part
    )
    mechanism = parse_mechanism(text)
    terms = _terms(text) | mechanism.object_groups | mechanism.phrase_concepts
    cache.card_terms[key] = terms
    return terms


def _card_like_terms(text: str) -> set[str]:
    mechanism = parse_mechanism(text)
    return (_terms(text) | mechanism.object_groups | mechanism.phrase_concepts) - mechanism.generic_terms


def _phrase_terms(
    card: dict[str, Any],
    cache: _BuildCache,
    stats: dict[str, Any],
) -> set[str]:
    key = _evidence_key(card)
    cached = cache.phrase_terms.get(key)
    if cached is not None:
        stats["phrase_cache_hits"] = int(stats.get("phrase_cache_hits") or 0) + 1
        return cached
    stats["phrase_cache_misses"] = int(stats.get("phrase_cache_misses") or 0) + 1
    phrases = {term for term in _card_terms(card, cache, stats) if "_" in term}
    cache.phrase_terms[key] = phrases
    return phrases


def _bundle_body_text(card: dict[str, Any]) -> str:
    return str(card.get("body_preview") or card.get("body") or "")[:2000]


def _evidence_key(card: dict[str, Any]) -> str:
    metadata = card.get("metadata") or {}
    for key in ("content_hash", "evidence_id"):
        value = card.get(key) or metadata.get(key)
        if value:
            return f"{key}:{value}"
    return "|".join(
        str(card.get(key) or "")
        for key in ("card_id", "card_name", "citation", "tag")
    ).lower()


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


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
