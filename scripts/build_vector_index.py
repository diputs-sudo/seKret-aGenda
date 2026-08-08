#!/usr/bin/env python3
"""Build Chroma card embeddings from the SQLite source-of-truth DB."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.embeddings import EmbeddingError, OllamaEmbedder
from backend.models import EmbeddingKind
from backend.models.sqlite_store import connect, embedding_records
from backend.vector_db.chroma_store import ChromaDependencyError, ChromaVectorStore
from backend.vector_db.schema import CARD_DEEP_COLLECTION, CARD_FAST_COLLECTION

COLLECTION_BY_KIND = {
    EmbeddingKind.FAST: CARD_FAST_COLLECTION,
    EmbeddingKind.DEEP: CARD_DEEP_COLLECTION,
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--chroma", type=Path, default=Path("var/chroma"))
    parser.add_argument("--kind", choices=["fast", "deep", "all"], default="all")
    parser.add_argument("--collection", default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    if args.kind == "all" and args.collection:
        parser.error("--collection can only be used with --kind fast or --kind deep")

    try:
        embedder = OllamaEmbedder(model=args.model)
        totals = []
        for kind in _selected_kinds(args.kind):
            connection = connect(args.db)
            records = embedding_records(connection, kind=kind)
            connection.close()
            collection = args.collection or COLLECTION_BY_KIND[kind]

            print(f"Loaded {len(records)} {kind.value} records from SQLite.")
            print(f"Indexing {kind.value} embeddings into {collection}.")

            store = ChromaVectorStore(args.chroma, collection)
            if args.reset:
                print(f"Resetting Chroma collection: {collection}")
                store.reset()
            totals.append((collection, store.add_cards(records, embedder)))
    except ChromaDependencyError as exc:
        print(f"Vector index build failed: {exc}")
        raise SystemExit(1) from exc
    except EmbeddingError as exc:
        print(f"Vector index build failed: {exc}")
        print("Make sure Ollama is running and run: ollama pull nomic-embed-text")
        raise SystemExit(1) from exc

    for collection, total in totals:
        print(f"Indexed {total} cards into {collection}.")


def _selected_kinds(kind: str) -> list[EmbeddingKind]:
    if kind == "all":
        return [EmbeddingKind.FAST, EmbeddingKind.DEEP]
    return [EmbeddingKind(kind)]


if __name__ == "__main__":
    main()
