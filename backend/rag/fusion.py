"""Rank-based fusion for broad retrieval candidates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Candidate:
    card_id: str
    card: dict[str, Any]
    ranks: dict[str, int] = field(default_factory=dict)
    scores: dict[str, float] = field(default_factory=dict)


def reciprocal_rank_fusion(
    source_results: dict[str, list[dict[str, Any]]],
    k: int = 60,
) -> list[dict[str, Any]]:
    candidates: dict[str, Candidate] = {}

    for source_name, rows in source_results.items():
        for rank, row in enumerate(rows, start=1):
            card_id = str(row.get("card_id") or row.get("id") or "")
            if not card_id:
                continue
            candidate = candidates.get(card_id)
            normalized = _normalize_card(row)
            if candidate is None:
                candidate = Candidate(card_id=card_id, card=normalized)
                candidates[card_id] = candidate
            else:
                candidate.card = _merge_card(candidate.card, normalized)
            candidate.ranks[source_name] = min(rank, candidate.ranks.get(source_name, rank))
            if row.get("score") is not None:
                candidate.scores[source_name] = float(row["score"])

    fused = []
    for candidate in candidates.values():
        retrieval_score = sum(1.0 / (k + rank) for rank in candidate.ranks.values())
        row = dict(candidate.card)
        row["card_id"] = candidate.card_id
        row["retrieval_score"] = round(retrieval_score, 6)
        row["source_ranks"] = dict(sorted(candidate.ranks.items()))
        row["source_scores"] = dict(sorted(candidate.scores.items()))
        fused.append(row)

    fused.sort(
        key=lambda row: (
            float(row["retrieval_score"]),
            -min(row["source_ranks"].values()),
        ),
        reverse=True,
    )
    return fused


def _normalize_card(row: dict[str, Any]) -> dict[str, Any]:
    metadata = row.get("metadata") or {}
    return {
        "card_id": row.get("card_id") or row.get("id"),
        "score": row.get("score"),
        "distance": row.get("distance"),
        "section": row.get("section") or row.get("section_name") or metadata.get("section"),
        "tag": row.get("tag") or metadata.get("tag"),
        "card_name": row.get("card_name") or metadata.get("card_name"),
        "argument_name": row.get("argument_name") or metadata.get("argument_name"),
        "citation": row.get("citation") or metadata.get("citation"),
        "author": row.get("author") or metadata.get("author"),
        "year": row.get("year") or metadata.get("year"),
        "document": row.get("document")
        or row.get("document_name")
        or metadata.get("document")
        or metadata.get("document_name"),
        "category": row.get("category") or metadata.get("category"),
        "topical": row.get("topical") if row.get("topical") is not None else metadata.get("topical"),
        "side": row.get("side") or metadata.get("side"),
        "source_path": row.get("source_path") or metadata.get("source_path"),
        "highlights": row.get("highlights") or [],
        "metadata": metadata,
    }


def _merge_card(existing: dict[str, Any], incoming: dict[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in incoming.items():
        if key == "metadata":
            metadata = dict(existing.get("metadata") or {})
            metadata.update(value or {})
            merged[key] = metadata
        elif key == "highlights":
            if not merged.get("highlights") and value:
                merged[key] = value
        elif _is_missing(merged.get(key)) and not _is_missing(value):
            merged[key] = value
    return merged


def _is_missing(value: Any) -> bool:
    return value is None or value == "" or value == []
