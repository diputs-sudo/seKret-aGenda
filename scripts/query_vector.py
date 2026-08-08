#!/usr/bin/env python3
"""Query the Chroma vector index."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.embeddings import EmbeddingError, OllamaEmbedder
from backend.models.sqlite_store import connect, search_cards
from backend.rag import RelevanceReranker
from backend.vector_db.chroma_store import ChromaDependencyError, ChromaVectorStore
from backend.vector_db.schema import CARD_FAST_COLLECTION


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--chroma", type=Path, default=Path("var/chroma"))
    parser.add_argument("--collection", default=CARD_FAST_COLLECTION)
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--rerank", action="store_true")
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--compare-sqlite", action="store_true")
    args = parser.parse_args()

    try:
        store = ChromaVectorStore(args.chroma, args.collection)
        embedder = OllamaEmbedder(model=args.model)
        rows = store.search(args.query, embedder, args.limit)
    except ChromaDependencyError as exc:
        print(f"Vector query failed: {exc}")
        raise SystemExit(1) from exc
    except EmbeddingError as exc:
        print(f"Vector query failed: {exc}")
        print("Make sure Ollama is running and run: ollama pull nomic-embed-text")
        raise SystemExit(1) from exc

    print("Vector results")
    print("-" * 45)
    for row in rows:
        metadata = row["metadata"]
        source = metadata.get("card_name") or metadata.get("author") or "Unknown"
        print(
            f"{row['score']:.3f}  {source:<18} "
            f"{metadata.get('section')}  |  {metadata.get('tag')}"
        )

    if args.rerank:
        reranker = RelevanceReranker()
        normalized = [_normalize_vector_row(row) for row in rows]
        reranked = reranker.rerank(args.query, normalized, args.top)
        print()
        print("Reranked vector results")
        print("-" * 45)
        if not reranked:
            print("No cards passed the relevance gate.")
        for row in reranked:
            print(
                f"{row['score']:.3f} rel={row['relevance_score']:.3f}  "
                f"{row.get('card_name'):<18} {row.get('section')}  |  {row.get('tag')}"
            )

    if args.compare_sqlite:
        print()
        print("SQLite FTS results")
        print("-" * 45)
        connection = connect(args.db)
        sqlite_rows = search_cards(connection, args.query, args.limit)
        connection.close()
        for row in sqlite_rows:
            source = row.get("card_name") or row.get("author") or "Unknown"
            print(f"{row['score']:.3f}  {source:<18} {row.get('section_name')}  |  {row.get('tag')}")


def _normalize_vector_row(row):
    metadata = row["metadata"]
    return {
        "card_id": row["card_id"],
        "score": row["score"],
        "section": metadata.get("section"),
        "tag": metadata.get("tag"),
        "card_name": metadata.get("card_name"),
        "author": metadata.get("author"),
        "year": metadata.get("year"),
        "metadata": metadata,
    }


if __name__ == "__main__":
    main()
