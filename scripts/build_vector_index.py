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
from backend.models.sqlite_store import (
    complete_index_run,
    delete_embedding_records_by_vector_ids,
    filter_changed_embedding_records,
    record_embedding_upserts,
    stale_embedding_vector_ids,
    start_index_run,
    init_db,
)
from backend.vector_db.chroma_store import ChromaDependencyError, ChromaVectorStore
from backend.vector_db.schema import (
    CARD_DEEP_COLLECTION,
    CARD_FAST_COLLECTION,
    EMBEDDING_VERSION,
)

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
            init_db(connection)
            records = embedding_records(connection, kind=kind)
            collection = args.collection or COLLECTION_BY_KIND[kind]

            print(f"Loaded {len(records)} {kind.value} records from SQLite.")
            print(f"Indexing {kind.value} embeddings into {collection}.")

            store = ChromaVectorStore(args.chroma, collection)
            if args.reset:
                print(f"Resetting Chroma collection: {collection}")
                store.reset()
                changed_records = records
                skipped = 0
                stale_ids = []
            else:
                stale_ids = stale_embedding_vector_ids(
                    connection,
                    kind=kind,
                    embedding_model=embedder.model,
                    live_card_ids={str(record["card_id"]) for record in records},
                )
                changed_records, skipped = filter_changed_embedding_records(
                    connection,
                    records,
                    kind=kind,
                    embedding_model=embedder.model,
                )

            run_id = start_index_run(
                connection,
                parser_version=_parser_version(records),
                embedding_model=embedder.model,
                embedding_version=EMBEDDING_VERSION,
                embedding_kind=kind.value,
                vector_collection=collection,
            )
            deleted = store.delete_ids(stale_ids)
            delete_embedding_records_by_vector_ids(
                connection,
                kind=kind,
                embedding_model=embedder.model,
                vector_ids=stale_ids,
            )
            indexed = store.add_cards(changed_records, embedder)
            record_embedding_upserts(
                connection,
                changed_records,
                kind=kind,
                embedding_model=embedder.model,
                vector_collection=collection,
            )
            complete_index_run(
                connection,
                run_id,
                cards_added=indexed,
                cards_updated=indexed,
                cards_deleted=deleted,
                cards_skipped=skipped,
            )
            connection.close()
            totals.append((collection, indexed, skipped, deleted))
    except ChromaDependencyError as exc:
        print(f"Vector index build failed: {exc}")
        raise SystemExit(1) from exc
    except EmbeddingError as exc:
        print(f"Vector index build failed: {exc}")
        print("Make sure Ollama is running and run: ollama pull nomic-embed-text")
        raise SystemExit(1) from exc

    for collection, total, skipped, deleted in totals:
        print(
            f"Indexed {total} cards into {collection}. "
            f"Skipped {skipped} unchanged. Deleted {deleted} stale vectors."
        )


def _selected_kinds(kind: str) -> list[EmbeddingKind]:
    if kind == "all":
        return [EmbeddingKind.FAST, EmbeddingKind.DEEP]
    return [EmbeddingKind(kind)]


def _parser_version(records: list[dict[str, object]]) -> str:
    versions = sorted({str(record.get("parser_version") or "") for record in records})
    return ",".join(version for version in versions if version)


if __name__ == "__main__":
    main()
