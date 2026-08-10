#!/usr/bin/env python3
"""Run retrieval quality checks against the vector index."""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.embeddings import EmbeddingError, OllamaEmbedder
from backend.models.sqlite_store import connect, search_cards
from backend.rag import RelevanceReranker, parse_query_intent, SearchMode
from backend.vector_db.chroma_store import ChromaDependencyError, ChromaVectorStore


@dataclass(frozen=True)
class EvalCase:
    name: str
    query: str
    expected_any: tuple[str, ...]
    reject: tuple[str, ...] = ()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--chroma", type=Path, default=Path("var/chroma"))
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument(
        "--eval-file",
        type=Path,
        help="Optional JSON file with labeled retrieval eval cases.",
    )
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
    evals = _load_eval_cases(args.eval_file) if args.eval_file else _smoke_eval_cases(args.db)
    failures = 0
    metric_rows = []

    for case in evals:
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
        metrics = _metrics(names, case)
        metric_rows.append(metrics)

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
        print(
            "Metrics: "
            f"recall@20={metrics['recall_at_20']:.3f} "
            f"precision@5={metrics['precision_at_5']:.3f} "
            f"mrr@5={metrics['mrr_at_5']:.3f} "
            f"ndcg@10={metrics['ndcg_at_10']:.3f} "
            f"hard_negative_rejection={metrics['hard_negative_rejection']:.3f} "
            f"duplicate_rate={metrics['duplicate_rate']:.3f} "
            f"lookup_accuracy={metrics['lookup_accuracy']:.3f}"
        )
        print()

    if metric_rows:
        summary = _average_metrics(metric_rows)
        print("=" * 72)
        print("Summary")
        for name, value in summary.items():
            print(f"{name}: {value:.3f}")

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


def _load_eval_cases(path: Path) -> list[EvalCase]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return [
        EvalCase(
            name=str(item["name"]),
            query=str(item["query"]),
            expected_any=tuple(str(value) for value in item.get("expected_any", [])),
            reject=tuple(str(value) for value in item.get("reject", [])),
        )
        for item in payload
    ]


def _smoke_eval_cases(db_path: Path) -> list[EvalCase]:
    connection = connect(db_path)
    rows = connection.execute(
        """
        SELECT card_name, tag
        FROM evidence_cards
        WHERE card_name IS NOT NULL
          AND card_name != ''
          AND tag IS NOT NULL
          AND tag != ''
        ORDER BY rowid
        LIMIT 5
        """
    ).fetchall()
    connection.close()
    return [
        EvalCase(
            name=f"Corpus smoke: {row['card_name']}",
            query=str(row["tag"]),
            expected_any=(str(row["card_name"]),),
        )
        for row in rows
    ]


def _metrics(names: list[str], case: EvalCase) -> dict[str, float]:
    expected = set(case.expected_any)
    rejected = set(case.reject)
    top5 = names[:5]
    top10 = names[:10]
    recall_denominator = max(len(expected), 1)
    recall_at_20 = len(expected & set(names[:20])) / recall_denominator
    precision_at_5 = len(expected & set(top5)) / max(len(top5), 1)
    mrr_at_5 = 0.0
    for index, name in enumerate(top5, start=1):
        if name in expected:
            mrr_at_5 = 1.0 / index
            break
    ndcg_at_10 = _ndcg(top10, expected)
    hard_negative_rejection = 1.0
    if rejected:
        hard_negative_rejection = len(rejected - set(names[:20])) / len(rejected)
    duplicate_rate = 1.0 - (len(set(names)) / len(names)) if names else 0.0
    intent = parse_query_intent(case.query)
    lookup_accuracy = 0.0
    if intent.search_mode in {SearchMode.AUTHOR, SearchMode.CITATION}:
        lookup_accuracy = 1.0 if expected & set(top5) else 0.0
    else:
        lookup_accuracy = 1.0
    return {
        "recall_at_20": recall_at_20,
        "precision_at_5": precision_at_5,
        "mrr_at_5": mrr_at_5,
        "ndcg_at_10": ndcg_at_10,
        "hard_negative_rejection": hard_negative_rejection,
        "duplicate_rate": duplicate_rate,
        "lookup_accuracy": lookup_accuracy,
    }


def _ndcg(names: list[str], expected: set[str]) -> float:
    dcg = 0.0
    for index, name in enumerate(names, start=1):
        relevance = 1.0 if name in expected else 0.0
        dcg += relevance / math.log2(index + 1)
    ideal_hits = min(len(expected), len(names))
    idcg = sum(1.0 / math.log2(index + 1) for index in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def _average_metrics(rows: list[dict[str, float]]) -> dict[str, float]:
    return {
        key: sum(row[key] for row in rows) / len(rows)
        for key in rows[0]
    }


if __name__ == "__main__":
    main()
