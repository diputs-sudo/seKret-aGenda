"""Hybrid retrieval across vector, lexical, and citation indexes."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.embeddings import Embedder
from backend.models.sqlite_store import (
    connect,
    load_cards_by_ids,
    lookup_author_cards,
    lookup_citation_cards,
    lookup_section_cards,
    search_author_citation_cards,
    search_cards,
)
from backend.vector_db.chroma_store import ChromaVectorStore
from backend.vector_db.schema import CARD_DEEP_COLLECTION, CARD_FAST_COLLECTION

from .argument_builder import ArgumentBuilder
from .candidate_assessment import RelevanceGate
from .fusion import reciprocal_rank_fusion
from .full_context_reranker import FullContextReranker
from .query_intent import QueryIntent, SearchMode, parse_query_intent

CITATION_LOOKUP_RE = re.compile(
    r"\b[A-Z][A-Za-z'’-]{2,}\s+(?:\d{4}|[‘'’]\d{2}|\d{2})\b"
)
GENERAL_MIN_RELEVANCE = 0.18


@dataclass(frozen=True)
class HybridSearchRequest:
    query: str
    mode: str = "search"
    limit: int = 10
    vector_limit: int = 50
    lexical_limit: int = 50
    citation_limit: int = 20
    query_embedding: list[float] | None = None


class HybridRetrievalEngine:
    def __init__(
        self,
        db_path: str | Path,
        embedder: Embedder,
        chroma_path: str | Path = "var/chroma",
        fast_store: ChromaVectorStore | None = None,
        deep_store: ChromaVectorStore | None = None,
        reranker: FullContextReranker | None = None,
        gate: RelevanceGate | None = None,
    ):
        self.db_path = Path(db_path)
        self.embedder = embedder
        self.chroma_path = Path(chroma_path)
        self._fast_store = fast_store
        self._deep_store = deep_store
        self.reranker = reranker or FullContextReranker()
        self.gate = gate or RelevanceGate()
        self.argument_builder = ArgumentBuilder()

    def search(
        self, request: HybridSearchRequest | str, limit: int | None = None
    ) -> list[dict[str, Any]]:
        if isinstance(request, str):
            request = HybridSearchRequest(query=request, limit=limit or 10)

        intent = parse_query_intent(request.query, mode=request.mode)
        lookup = self._lookup(intent, request)
        if lookup is not None:
            return lookup[: intent.requested_count or request.limit]

        source_results = self.retrieve_candidates(intent, request)
        fused = reciprocal_rank_fusion(source_results)
        fused = self._expand_cards(fused)
        filtered = [row for row in fused if _matches_filters(row, intent)]
        reranked = self.reranker.rerank(intent, filtered)
        if intent.search_mode == SearchMode.ARGUMENT:
            accepted, _ = self.gate.split(reranked)
            bundle = self.argument_builder.build(
                intent,
                accepted,
                limit=intent.requested_count or request.limit,
            )
            return bundle.cards
        accepted = _general_accept(reranked)
        bundle = self.argument_builder.build(
            intent,
            accepted,
            limit=intent.requested_count or request.limit,
        )
        return bundle.cards

    def retrieve_candidates(
        self,
        intent: QueryIntent,
        request: HybridSearchRequest,
    ) -> dict[str, list[dict[str, Any]]]:
        source_results, _ = self._retrieve_candidates_timed(intent, request)
        return source_results

    def _retrieve_candidates_timed(
        self,
        intent: QueryIntent,
        request: HybridSearchRequest,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, float]]:
        search_text = retrieval_text(intent)
        citation_query = _citation_lookup_query(intent)
        timings: dict[str, float] = {}

        started = time.perf_counter()
        with connect(self.db_path) as connection:
            lexical = search_cards(connection, search_text, request.lexical_limit)
            citation = (
                search_author_citation_cards(
                    connection, citation_query, request.citation_limit
                )
                if citation_query
                else []
            )
        timings["sqlite"] = _elapsed_ms(started)

        query_embedding = request.query_embedding
        if query_embedding is None:
            started = time.perf_counter()
            query_embedding = self.embedder.embed(search_text)
            timings["query_embedding"] = _elapsed_ms(started)
        else:
            timings["query_embedding"] = 0.0

        started = time.perf_counter()
        fast_vector = _search_vector_store(
            self._fast_store_or_create(),
            search_text,
            query_embedding,
            self.embedder,
            request.vector_limit,
        )
        timings["fast_vector"] = _elapsed_ms(started)

        started = time.perf_counter()
        deep_vector = _search_vector_store(
            self._deep_store_or_create(),
            search_text,
            query_embedding,
            self.embedder,
            request.vector_limit,
        )
        timings["deep_vector"] = _elapsed_ms(started)

        return {
            "fast_vector": fast_vector,
            "deep_vector": deep_vector,
            "sqlite_fts": _normalize_sqlite_rows(lexical),
            "author_citation": _normalize_sqlite_rows(citation),
        }, timings

    def debug_trace(self, request: HybridSearchRequest | str) -> dict[str, Any]:
        trace_started = time.perf_counter()
        timings: dict[str, float] = {}
        if isinstance(request, str):
            request = HybridSearchRequest(query=request)
        started = time.perf_counter()
        intent = parse_query_intent(request.query, mode=request.mode)
        timings["parse_intent"] = _elapsed_ms(started)
        started = time.perf_counter()
        lookup = self._lookup(intent, request)
        timings["lookup"] = _elapsed_ms(started)
        if lookup is not None:
            started = time.perf_counter()
            bundle = self.argument_builder.build(
                intent,
                lookup,
                limit=intent.requested_count or request.limit,
            )
            timings["bundle"] = _elapsed_ms(started)
            timings["total"] = _elapsed_ms(trace_started)
            timings["accounted"] = _accounted_ms(timings)
            timings["unaccounted"] = max(
                0.0, timings["total"] - timings["accounted"]
            )
            return {
                "intent": intent,
                "retrieval_text": retrieval_text(intent),
                "source_results": {_lookup_source_name(intent): lookup},
                "fused": lookup,
                "reranked": lookup,
                "accepted": lookup,
                "rejected": [],
                "selected": bundle.cards,
                "clusters": [cluster.to_dict() for cluster in bundle.clusters],
                "argument_bundle": bundle.to_dict(),
                "timings": timings,
                "bundle_debug": self.argument_builder.last_debug,
            }

        source_results, retrieval_timings = self._retrieve_candidates_timed(
            intent, request
        )
        started = time.perf_counter()
        fused = reciprocal_rank_fusion(source_results)
        fusion_ms = _elapsed_ms(started)
        started = time.perf_counter()
        expanded = self._expand_cards(fused)
        hydrate_ms = _elapsed_ms(started)
        started = time.perf_counter()
        filtered = [row for row in expanded if _matches_filters(row, intent)]
        filter_ms = _elapsed_ms(started)
        started = time.perf_counter()
        reranked = self.reranker.rerank(intent, filtered)
        rerank_ms = _elapsed_ms(started)
        started = time.perf_counter()
        if intent.search_mode == SearchMode.ARGUMENT:
            accepted, rejected = self.gate.split(reranked)
        else:
            accepted = _general_accept(reranked)
            rejected = [row for row in reranked if row not in accepted]
        gate_ms = _elapsed_ms(started)
        started = time.perf_counter()
        bundle = self.argument_builder.build(
            intent,
            accepted,
            limit=intent.requested_count or request.limit,
        )
        bundle_ms = _elapsed_ms(started)
        timings = {
            **timings,
            **retrieval_timings,
            "fusion": fusion_ms,
            "sqlite_hydration": hydrate_ms,
            "filter": filter_ms,
            "rerank": rerank_ms,
            "gate": gate_ms,
            "bundle": bundle_ms,
        }
        timings["total"] = _elapsed_ms(trace_started)
        timings["accounted"] = _accounted_ms(timings)
        timings["unaccounted"] = max(0.0, timings["total"] - timings["accounted"])
        return {
            "intent": intent,
            "retrieval_text": retrieval_text(intent),
            "source_results": source_results,
            "fused": fused,
            "reranked": reranked,
            "accepted": accepted,
            "rejected": rejected,
            "selected": bundle.cards,
            "clusters": [cluster.to_dict() for cluster in bundle.clusters],
            "argument_bundle": bundle.to_dict(),
            "timings": timings,
            "bundle_debug": self.argument_builder.last_debug,
        }

    def candidate_trace(self, request: HybridSearchRequest | str) -> dict[str, Any]:
        """Return cheap first-pass candidates without hydration/rerank/bundling."""
        trace_started = time.perf_counter()
        timings: dict[str, float] = {}
        if isinstance(request, str):
            request = HybridSearchRequest(query=request)
        started = time.perf_counter()
        intent = parse_query_intent(request.query, mode=request.mode)
        timings["parse_intent"] = _elapsed_ms(started)
        started = time.perf_counter()
        lookup = self._lookup(intent, request)
        timings["lookup"] = _elapsed_ms(started)
        if lookup is not None:
            timings["total"] = _elapsed_ms(trace_started)
            timings["accounted"] = _accounted_ms(timings)
            timings["unaccounted"] = max(
                0.0, timings["total"] - timings["accounted"]
            )
            return {
                "intent": intent,
                "retrieval_text": retrieval_text(intent),
                "source_results": {_lookup_source_name(intent): lookup},
                "candidates": lookup,
                "timings": timings,
            }

        source_results, retrieval_timings = self._retrieve_candidates_timed(
            intent, request
        )
        started = time.perf_counter()
        candidates = reciprocal_rank_fusion(source_results)
        timings = {
            **timings,
            **retrieval_timings,
            "fusion": _elapsed_ms(started),
        }
        timings["total"] = _elapsed_ms(trace_started)
        timings["accounted"] = _accounted_ms(timings)
        timings["unaccounted"] = max(0.0, timings["total"] - timings["accounted"])
        return {
            "intent": intent,
            "retrieval_text": retrieval_text(intent),
            "source_results": source_results,
            "candidates": candidates,
            "timings": timings,
        }

    def rerank_candidates(
        self,
        query: str,
        rows: list[dict[str, Any]],
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, float]]:
        """Hydrate and rerank a global candidate pool once."""
        started_total = time.perf_counter()
        timings: dict[str, float] = {}
        started = time.perf_counter()
        intent = parse_query_intent(query)
        timings["parse_intent"] = _elapsed_ms(started)
        started = time.perf_counter()
        expanded = self._expand_cards(rows)
        timings["sqlite_hydration"] = _elapsed_ms(started)
        started = time.perf_counter()
        filtered = [row for row in expanded if _matches_filters(row, intent)]
        timings["filter"] = _elapsed_ms(started)
        started = time.perf_counter()
        reranked = self.reranker.rerank(intent, filtered, limit=limit)
        timings["rerank"] = _elapsed_ms(started)
        timings["total"] = _elapsed_ms(started_total)
        timings["accounted"] = _accounted_ms(timings)
        timings["unaccounted"] = max(0.0, timings["total"] - timings["accounted"])
        return reranked, timings

    def _lookup(
        self,
        intent: QueryIntent,
        request: HybridSearchRequest,
    ) -> list[dict[str, Any]] | None:
        if intent.search_mode not in {
            SearchMode.AUTHOR,
            SearchMode.CITATION,
            SearchMode.SECTION,
        }:
            return None

        limit = intent.requested_count or request.limit
        with connect(self.db_path) as connection:
            if intent.search_mode == SearchMode.CITATION and intent.author_filter and intent.year_min:
                rows = lookup_citation_cards(
                    connection,
                    intent.author_filter,
                    intent.year_min,
                    limit=limit,
                )
            elif intent.search_mode == SearchMode.AUTHOR and intent.author_filter:
                rows = lookup_author_cards(connection, intent.author_filter, limit=limit)
            elif intent.search_mode == SearchMode.SECTION and intent.section_filter:
                rows = lookup_section_cards(connection, intent.section_filter, limit=limit)
            else:
                rows = []

        if not rows and _should_fallback_to_general(intent):
            return None
        return _normalize_lookup_rows(rows, _lookup_source_name(intent))

    def _expand_cards(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        card_ids = [str(row["card_id"]) for row in rows]
        with connect(self.db_path) as connection:
            cards = load_cards_by_ids(connection, card_ids)

        expanded = []
        for row in rows:
            card = cards.get(str(row["card_id"]))
            if not card:
                continue
            merged = dict(row)
            for key, value in card.items():
                if key == "metadata":
                    merged[key] = {
                        **(merged.get(key) if isinstance(merged.get(key), dict) else {}),
                        **(value if isinstance(value, dict) else {}),
                    }
                elif key == "highlights" or _is_missing(merged.get(key)):
                    merged[key] = value
            expanded.append(merged)
        return expanded

    def _fast_store_or_create(self) -> ChromaVectorStore:
        if self._fast_store is None:
            self._fast_store = ChromaVectorStore(
                self.chroma_path, CARD_FAST_COLLECTION
            )
        return self._fast_store

    def _deep_store_or_create(self) -> ChromaVectorStore:
        if self._deep_store is None:
            self._deep_store = ChromaVectorStore(
                self.chroma_path, CARD_DEEP_COLLECTION
            )
        return self._deep_store


def _normalize_sqlite_rows(rows: list[dict[str, object]]) -> list[dict[str, Any]]:
    normalized = []
    for row in rows:
        item = dict(row)
        item["card_id"] = item.get("id") or item.get("card_id")
        normalized.append(item)
    return normalized


def _search_vector_store(
    store,
    search_text: str,
    query_embedding: list[float],
    embedder: Embedder,
    limit: int,
) -> list[dict[str, Any]]:
    if hasattr(store, "search_by_embedding"):
        return store.search_by_embedding(query_embedding, limit)
    return store.search(search_text, embedder, limit)


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def _accounted_ms(timings: dict[str, float]) -> float:
    excluded = {"total", "accounted", "unaccounted"}
    return sum(value for key, value in timings.items() if key not in excluded)


def _normalize_lookup_rows(
    rows: list[dict[str, object]],
    source_name: str,
) -> list[dict[str, Any]]:
    normalized = []
    for rank, row in enumerate(_normalize_sqlite_rows(rows), start=1):
        item = dict(row)
        item["section"] = item.get("section") or item.get("section_name")
        item["document"] = item.get("document") or item.get("document_name")
        item["retrieval_score"] = round(1.0 / rank, 6)
        item["reranker_score"] = item["retrieval_score"]
        item["source_ranks"] = {source_name: rank}
        item["source_scores"] = {source_name: float(item.get("score") or 1.0)}
        item["candidate_assessment"] = {
            "relationship": "EXACT_LOOKUP",
            "confidence": 1.0,
            "relevance_score": item["retrieval_score"],
            "topic_match": 1.0,
            "mechanism_match": None,
            "warrant_match": None,
            "evidence_strength": 1.0,
            "rejection_reason": None,
            "matched_concepts": [],
            "missing_concepts": [],
            "reasons": [f"direct {source_name} lookup"],
        }
        item["reranker_assessment"] = item["candidate_assessment"]
        normalized.append(item)
    return normalized


def _lookup_source_name(intent: QueryIntent) -> str:
    if intent.search_mode == SearchMode.CITATION:
        return "citation_lookup"
    if intent.search_mode == SearchMode.AUTHOR:
        return "author_lookup"
    if intent.search_mode == SearchMode.SECTION:
        return "section_lookup"
    return "lookup"


def _should_fallback_to_general(intent: QueryIntent) -> bool:
    return (
        intent.search_mode == SearchMode.AUTHOR
        and bool(intent.search_text)
        and f"author:{intent.author_filter}".lower() not in intent.raw_query.lower()
    )


def _general_accept(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    threshold = _general_threshold(rows)
    return [
        row
        for row in rows
        if float(row.get("reranker_score") or 0) >= threshold
    ]


def _general_threshold(rows: list[dict[str, Any]]) -> float:
    scores = sorted((float(row.get("reranker_score") or 0) for row in rows), reverse=True)
    if not scores:
        return GENERAL_MIN_RELEVANCE
    top = scores[0]
    if top >= 0.75:
        return max(GENERAL_MIN_RELEVANCE, top * 0.35)
    if top >= 0.45:
        return max(GENERAL_MIN_RELEVANCE, top * 0.45)
    return max(GENERAL_MIN_RELEVANCE, top * 0.7)


def retrieval_text(intent: QueryIntent) -> str:
    return intent.opponent_claim or intent.search_text or intent.raw_query


def _citation_lookup_query(intent: QueryIntent) -> str | None:
    if intent.author_filter:
        parts = [intent.author_filter]
        if intent.year_min is not None:
            parts.append(str(intent.year_min))
        return " ".join(parts)

    raw_query = intent.raw_query.strip()
    search_text = intent.search_text.strip()
    if CITATION_LOOKUP_RE.search(raw_query):
        return raw_query
    if len(search_text.split()) <= 4 and re.search(r"\d{2,4}|[‘'’]\d{2}", search_text):
        return search_text
    return None


def _matches_filters(card: dict[str, Any], intent: QueryIntent) -> bool:
    if intent.author_filter:
        author = str(card.get("author") or "").lower()
        card_name = str(card.get("card_name") or "").lower()
        expected = intent.author_filter.lower()
        if expected not in author and expected not in card_name:
            return False

    if intent.year_min is not None:
        year = _int_or_none(card.get("year"))
        if year is None or year < intent.year_min:
            return False
    if intent.year_max is not None:
        year = _int_or_none(card.get("year"))
        if year is None or year > intent.year_max:
            return False

    if intent.section_filter:
        section = str(card.get("section") or "").lower()
        if intent.section_filter.lower() not in section:
            return False

    if intent.category_filter:
        category = str(card.get("category") or "").lower()
        if category != intent.category_filter.lower():
            return False

    if intent.topical_filter is not None:
        topical = card.get("topical")
        if isinstance(topical, str):
            topical = topical.lower() in {"true", "yes", "1"}
        if topical is None or bool(topical) is not intent.topical_filter:
            return False

    return True


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []
