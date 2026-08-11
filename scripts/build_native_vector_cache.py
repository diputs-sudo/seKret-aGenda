#!/usr/bin/env python3
"""Build the native desktop vector cache inside the SQLite source DB."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Protocol

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.embeddings import EmbeddingError, OllamaEmbedder
from backend.models import EmbeddingKind
from backend.models.sqlite_store import connect, embedding_records, init_db

NATIVE_VECTOR_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS native_card_vectors (
    card_id TEXT NOT NULL,
    embedding_kind TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (card_id, embedding_kind, embedding_model),
    FOREIGN KEY (card_id) REFERENCES evidence_cards(id) ON DELETE CASCADE
)
"""

NATIVE_VECTOR_INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_native_card_vectors_kind_model
    ON native_card_vectors(embedding_kind, embedding_model)
"""


class Embedder(Protocol):
    @property
    def model(self) -> str: ...

    def embed(self, text: str) -> list[float]: ...


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--kind", choices=["fast", "deep", "all"], default="all")
    parser.add_argument("--model", default=None)
    parser.add_argument(
        "--max-chars",
        type=int,
        default=int(os.environ.get("SEKRET_NATIVE_VECTOR_MAX_CHARS", "6000")),
        help="Maximum characters sent to Ollama per embedding text.",
    )
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()

    try:
        embedder = OllamaEmbedder(model=args.model)
        totals = build_native_vector_cache(
            args.db,
            embedder,
            kinds=_selected_kinds(args.kind),
            reset=args.reset,
            max_chars=args.max_chars,
        )
    except EmbeddingError as exc:
        print(f"Native vector cache build failed: {exc}")
        print("Make sure Ollama is running and run: ollama pull nomic-embed-text")
        raise SystemExit(1) from exc

    for kind, total in totals.items():
        print(f"Cached {total} {kind} native vectors.")


def build_native_vector_cache(
    db_path: Path,
    embedder: Embedder,
    *,
    kinds: list[EmbeddingKind],
    reset: bool = False,
    max_chars: int = 12000,
) -> dict[str, int]:
    connection = connect(db_path)
    init_db(connection)
    ensure_native_vector_table(connection)

    totals: dict[str, int] = {}
    try:
        for kind in kinds:
            if reset:
                with connection:
                    connection.execute(
                        """
                        DELETE FROM native_card_vectors
                        WHERE embedding_kind = ? AND embedding_model = ?
                        """,
                        (kind.value, embedder.model),
                    )
            records = embedding_records(connection, kind=kind)
            total = 0
            with connection:
                for record in records:
                    vector = embedder.embed(_clip_embedding_text(str(record["embedding_text"]), max_chars))
                    connection.execute(
                        """
                        INSERT INTO native_card_vectors (
                            card_id, embedding_kind, embedding_model, vector_json, updated_at
                        )
                        VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                        ON CONFLICT(card_id, embedding_kind, embedding_model)
                        DO UPDATE SET
                            vector_json = excluded.vector_json,
                            updated_at = excluded.updated_at
                        """,
                        (
                            record["card_id"],
                            kind.value,
                            embedder.model,
                            json.dumps(vector, separators=(",", ":")),
                        ),
                    )
                    total += 1
            totals[kind.value] = total
    finally:
        connection.close()
    return totals


def _clip_embedding_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    clipped = text[:max_chars].rstrip()
    paragraph_break = clipped.rfind("\n\n")
    if paragraph_break >= max_chars // 2:
        return clipped[:paragraph_break].rstrip()
    sentence_break = max(clipped.rfind(". "), clipped.rfind("? "), clipped.rfind("! "))
    if sentence_break >= max_chars // 2:
        return clipped[: sentence_break + 1].rstrip()
    return clipped


def ensure_native_vector_table(connection) -> None:
    with connection:
        connection.execute(NATIVE_VECTOR_TABLE_SQL)
        connection.execute(NATIVE_VECTOR_INDEX_SQL)


def _selected_kinds(kind: str) -> list[EmbeddingKind]:
    if kind == "all":
        return [EmbeddingKind.FAST, EmbeddingKind.DEEP]
    return [EmbeddingKind(kind)]


if __name__ == "__main__":
    main()
