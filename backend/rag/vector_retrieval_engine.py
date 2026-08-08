"""Vector-backed retrieval engine."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.embeddings import Embedder
from backend.models.sqlite_store import connect, load_cards_by_ids
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
        with connect(self.db_path) as connection:
            cards = load_cards_by_ids(connection, card_ids)

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
