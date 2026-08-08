"""Retrieval engine interface.

The retrieval engine owns search quality. Storage, vector databases, APIs, and
LLMs should call this layer instead of reaching into SQLite directly.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from backend.models.sqlite_store import connect, search_cards


@dataclass(frozen=True)
class SearchRequest:
    query: str
    limit: int = 10
    include_body_preview: bool = False


class RetrievalEngine:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def search(self, request: SearchRequest | str, limit: int | None = None) -> list[dict[str, Any]]:
        if isinstance(request, str):
            request = SearchRequest(query=request, limit=limit or 10)

        with connect(self.db_path) as connection:
            rows = search_cards(connection, request.query, request.limit)

        results = [self._to_search_result(row) for row in rows]
        if not request.include_body_preview:
            for result in results:
                result.pop("body_preview", None)
        return results

    def rerank(
        self, query: str, results: list[dict[str, Any]], limit: int | None = None
    ) -> list[dict[str, Any]]:
        # Placeholder for vector reranking. Keep the method in the interface now
        # so API/CLI/LLM code does not change when reranking becomes real.
        del query
        return results[:limit] if limit is not None else results

    def expand(self, card_id: str) -> dict[str, Any] | None:
        with connect(self.db_path) as connection:
            row = _load_card(connection, card_id)
        return dict(row) if row else None

    def _to_search_result(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "card_id": row["id"],
            "score": row["score"],
            "tag": row["tag"],
            "section": row["section_name"],
            "citation": row["citation"],
            "card_name": row["card_name"],
            "argument_name": row.get("argument_name"),
            "author": row["author"],
            "year": row["year"],
            "document": row["document_name"],
            "side": row.get("side"),
            "source_path": row.get("source_path"),
            "highlights": row["highlights"],
            "body_preview": row.get("body_preview"),
        }


def _load_card(connection: sqlite3.Connection, card_id: str) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT
            evidence_cards.id AS card_id,
            debate_documents.name AS document,
            sections.name AS section,
            evidence_cards.tag,
            evidence_cards.card_name,
            evidence_cards.argument_name,
            evidence_cards.side,
            evidence_cards.source_path,
            citations.raw AS citation,
            citations.author,
            citations.year,
            evidence_cards.body
        FROM evidence_cards
        JOIN sections ON sections.id = evidence_cards.section_id
        JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
        LEFT JOIN citations ON citations.card_id = evidence_cards.id
        WHERE evidence_cards.id = ?
        """,
        (card_id,),
    ).fetchone()
