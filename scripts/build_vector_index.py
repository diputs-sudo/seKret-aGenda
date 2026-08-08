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
from backend.models.sqlite_store import connect, embedding_records
from backend.vector_db.chroma_store import ChromaDependencyError, ChromaVectorStore
from backend.vector_db.schema import CARD_FAST_COLLECTION


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--chroma", type=Path, default=Path("var/chroma"))
    parser.add_argument("--collection", default=CARD_FAST_COLLECTION)
    parser.add_argument("--model", default=None)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    connection = connect(args.db)
    records = embedding_records(connection)
    connection.close()

    print(f"Loaded {len(records)} cards from SQLite.")
    print("Embedding text shape: section + tag + highlights.")

    try:
        store = ChromaVectorStore(args.chroma, args.collection)
        if args.reset:
            print("Resetting Chroma collection.")
            store.reset()
        embedder = OllamaEmbedder(model=args.model)
        total = store.add_cards(records, embedder)
    except ChromaDependencyError as exc:
        print(f"Vector index build failed: {exc}")
        raise SystemExit(1) from exc
    except EmbeddingError as exc:
        print(f"Vector index build failed: {exc}")
        print("Make sure Ollama is running and run: ollama pull nomic-embed-text")
        raise SystemExit(1) from exc

    print(f"Indexed {total} cards into {args.collection}.")


if __name__ == "__main__":
    main()

