#!/usr/bin/env python3
"""Run retrieval quality checks against the vector index."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.embeddings import EmbeddingError, OllamaEmbedder
from backend.models.sqlite_store import connect, search_cards
from backend.rag import RelevanceReranker
from backend.vector_db.chroma_store import ChromaDependencyError, ChromaVectorStore


@dataclass(frozen=True)
class EvalCase:
    name: str
    query: str
    expected_any: tuple[str, ...]
    reject: tuple[str, ...] = ()


EVALS = [
    EvalCase("AI cautious", "AI cautious", ("Tucker 20",), ("Shapiro 26", "Javed 25")),
    EvalCase(
        "Automation escalation",
        "automation escalation",
        ("Cox 21", "Goldfarb 22", "Tucker 20"),
        ("Shapiro 26", "Swift 25"),
    ),
    EvalCase(
        "Quantum encryption",
        "quantum encryption",
        ("Hunt 26",),
        ("Tucker 20",),
    ),
    EvalCase("Author lookup", "Tucker", ("Tucker 20",), ()),
]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma", type=Path, default=Path("var/chroma"))
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--limit", type=int, default=15)
    parser.add_argument("--top", type=int, default=3)
    parser.add_argument("--model", default=None)
    args = parser.parse_args()

    try:
        store = ChromaVectorStore(args.chroma)
        embedder = OllamaEmbedder(model=args.model)
    except ChromaDependencyError as exc:
        print(f"Eval setup failed: {exc}")
        raise SystemExit(1) from exc

    reranker = RelevanceReranker()
    available_names = _available_card_names(args.db)
    failures = 0

    for case in EVALS:
        print("=" * 72)
        print(case.name)
        print(f"Query: {case.query}")
        if not any(name in available_names for name in case.expected_any):
            print("Status: SKIP")
            print("Reason: expected cards are not present in the current SQLite corpus.")
            print()
            continue

        try:
            vector_rows = store.search(case.query, embedder, args.limit)
        except EmbeddingError as exc:
            print(f"Eval failed: {exc}")
            raise SystemExit(1) from exc

        reranked = reranker.rerank(
            case.query,
            [_normalize(row) for row in vector_rows],
            args.top,
        )
        if not reranked:
            reranked = _sqlite_fallback(args.db, case.query, args.top)
        names = [str(row.get("card_name") or "") for row in reranked]

        print("Results:")
        for row in reranked:
            print(
                f"- {row.get('card_name')} "
                f"score={float(row.get('score', 0)):.3f} "
                f"rel={float(row.get('relevance_score', 0)):.3f} "
                f"| {row.get('tag')}"
            )

        missing = [name for name in case.expected_any if name not in names]
        rejected = [name for name in case.reject if name in names]
        if missing:
            print(f"Missing expected: {', '.join(missing)}")
        if rejected:
            print(f"Included rejected: {', '.join(rejected)}")

        if missing or rejected:
            print("Status: FAIL")
            failures += 1
        else:
            print("Status: PASS")
        print()

    if failures:
        raise SystemExit(1)


def _normalize(row):
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


def _sqlite_fallback(db_path: Path, query: str, limit: int):
    connection = connect(db_path)
    rows = search_cards(connection, query, limit)
    connection.close()
    return [
        {
            "card_id": row["id"],
            "score": row["score"],
            "relevance_score": 0.0,
            "section": row["section_name"],
            "tag": row["tag"],
            "card_name": row["card_name"],
            "author": row["author"],
            "year": row["year"],
            "metadata": {},
        }
        for row in rows
    ]


def _available_card_names(db_path: Path) -> set[str]:
    connection = connect(db_path)
    rows = connection.execute(
        """
        SELECT card_name
        FROM evidence_cards
        WHERE card_name IS NOT NULL AND card_name != ''
        """
    ).fetchall()
    connection.close()
    return {str(row["card_name"]) for row in rows}


if __name__ == "__main__":
    main()
