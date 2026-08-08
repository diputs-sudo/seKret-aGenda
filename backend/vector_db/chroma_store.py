"""Chroma vector store for evidence-card embeddings."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from backend.embeddings import Embedder
from backend.vector_db.schema import CARD_FAST_COLLECTION, EMBEDDING_VERSION


class ChromaDependencyError(RuntimeError):
    """Raised when chromadb is not installed."""


class ChromaVectorStore:
    def __init__(
        self,
        persist_path: str | Path = "var/chroma",
        collection_name: str = CARD_FAST_COLLECTION,
        client: Any | None = None,
    ):
        self.persist_path = Path(persist_path)
        if client is None:
            try:
                import chromadb
            except ModuleNotFoundError as exc:
                raise ChromaDependencyError(
                    "chromadb is not installed. Install it with: python3 -m pip install chromadb"
                ) from exc
            client = chromadb.PersistentClient(path=str(self.persist_path))

        self.client = client
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

    def reset(self) -> None:
        name = self.collection.name
        self.client.delete_collection(name)
        self.collection = self.client.get_or_create_collection(
            name=name,
            metadata={"hnsw:space": "cosine"},
        )

    def add_cards(
        self,
        records: list[dict[str, Any]],
        embedder: Embedder,
        batch_size: int = 16,
    ) -> int:
        total = 0
        for start in range(0, len(records), batch_size):
            batch = records[start : start + batch_size]
            ids = [str(record["card_id"]) for record in batch]
            documents = [str(record["embedding_text"]) for record in batch]
            embeddings = [embedder.embed(document) for document in documents]
            metadatas = [_metadata(record, embedder.model) for record in batch]
            self.collection.upsert(
                ids=ids,
                documents=documents,
                embeddings=embeddings,
                metadatas=metadatas,
            )
            total += len(batch)
        return total

    def search(
        self,
        query: str,
        embedder: Embedder,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        query_embedding = embedder.embed(query)
        result = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=limit,
            include=["metadatas", "distances", "documents"],
        )
        ids = result.get("ids", [[]])[0]
        metadatas = result.get("metadatas", [[]])[0]
        distances = result.get("distances", [[]])[0]
        documents = result.get("documents", [[]])[0]
        rows = []
        for index, card_id in enumerate(ids):
            distance = float(distances[index]) if index < len(distances) else 0.0
            metadata = dict(metadatas[index] or {}) if index < len(metadatas) else {}
            rows.append(
                {
                    "card_id": card_id,
                    "distance": distance,
                    "score": _score_from_distance(distance),
                    "metadata": metadata,
                    "document": documents[index] if index < len(documents) else "",
                }
            )
        return rows


def _metadata(record: dict[str, Any], embedding_model: str) -> dict[str, Any]:
    return {
        "card_id": record["card_id"],
        "embedding_kind": record.get("embedding_kind") or "fast",
        "section": record["section"],
        "tag": record["tag"],
        "card_name": record.get("card_name") or "",
        "argument_name": record.get("argument_name") or "",
        "citation": record.get("citation") or "",
        "author": record.get("author") or "",
        "year": record.get("year") or 0,
        "category": record.get("category") or "",
        "topical": record.get("topical")
        if record.get("topical") is not None
        else "",
        "document": record["document_name"],
        "document_name": record["document_name"],
        "source_path": record.get("source_path") or "",
        "source_format": record.get("source_format") or "",
        "content_hash": record.get("content_hash") or "",
        "source_text_hash": record.get("source_text_hash") or "",
        "embedding_model": embedding_model,
        "embedding_version": EMBEDDING_VERSION,
        "parser_version": record.get("parser_version") or "",
        "highlight_text": record.get("highlight_text") or "",
    }


def _score_from_distance(distance: float) -> float:
    return round(max(0.0, min(1.0, 1.0 - distance)), 3)
