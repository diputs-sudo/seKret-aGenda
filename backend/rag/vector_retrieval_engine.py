"""Vector-backed retrieval engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.embeddings import Embedder
from backend.models.sqlite_store import card_highlights, connect
from backend.vector_db.chroma_store import ChromaVectorStore


class VectorRetrievalEngine:
    def __init__(
        self,
        db_path: str | Path,
        vector_store: ChromaVectorStore,
        embedder: Embedder,
    ):
        self.db_path = Path(db_path)
        self.vector_store = vector_store
        self.embedder = embedder

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        vector_rows = self.vector_store.search(query, self.embedder, limit)
        card_ids = [str(row["card_id"]) for row in vector_rows]
        cards = _load_cards(self.db_path, card_ids)

        results = []
        for row in vector_rows:
            card = cards.get(str(row["card_id"]))
            if not card:
                continue
            result = dict(card)
            result["score"] = row["score"]
            result["distance"] = row["distance"]
            results.append(result)
        return results


def _load_cards(db_path: Path, card_ids: list[str]) -> dict[str, dict[str, Any]]:
    if not card_ids:
        return {}

    placeholders = ",".join("?" for _ in card_ids)
    with connect(db_path) as connection:
        rows = connection.execute(
            f"""
            SELECT
                evidence_cards.id AS card_id,
                debate_documents.name AS document,
                sections.name AS section,
                evidence_cards.tag,
                evidence_cards.card_name,
                citations.raw AS citation,
                citations.author,
                citations.year
            FROM evidence_cards
            JOIN sections ON sections.id = evidence_cards.section_id
            JOIN debate_documents ON debate_documents.id = evidence_cards.document_id
            LEFT JOIN citations ON citations.card_id = evidence_cards.id
            WHERE evidence_cards.id IN ({placeholders})
            """,
            card_ids,
        ).fetchall()

        cards = {str(row["card_id"]): dict(row) for row in rows}
        for card_id in cards:
            cards[card_id]["highlights"] = card_highlights(connection, card_id)

    return cards
