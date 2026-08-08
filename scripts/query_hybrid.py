#!/usr/bin/env python3
"""Query hybrid retrieval across fast vectors, deep vectors, and SQLite."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.embeddings import EmbeddingError, OllamaEmbedder
from backend.rag import HybridRetrievalEngine, HybridSearchRequest
from backend.vector_db.chroma_store import ChromaDependencyError


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("query")
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--chroma", type=Path, default=Path("var/chroma"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument(
        "--concept-debug",
        action="store_true",
        help="Print stopword, phrase-concept, and match-location diagnostics.",
    )
    args = parser.parse_args()

    try:
        engine = HybridRetrievalEngine(
            db_path=args.db,
            chroma_path=args.chroma,
            embedder=OllamaEmbedder(model=args.model),
        )
        request = HybridSearchRequest(query=args.query, limit=args.limit)
        trace = engine.debug_trace(request) if args.debug else None
        results = trace["selected"] if trace else engine.search(request)
    except ChromaDependencyError as exc:
        print(f"Hybrid query failed: {exc}")
        raise SystemExit(1) from exc
    except EmbeddingError as exc:
        print(f"Hybrid query failed: {exc}")
        print("Make sure Ollama is running and run: ollama pull nomic-embed-text")
        raise SystemExit(1) from exc

    if trace:
        intent = trace["intent"]
        print("Query intent")
        print("-" * 45)
        print(f"Mode: {intent.search_mode.value}")
        print(f"Search text: {intent.search_text}")
        print(f"Retrieval text: {trace['retrieval_text']}")
        print(f"Opponent claim: {intent.opponent_claim or ''}")
        if args.concept_debug:
            print(f"Ignored stopwords: {', '.join(intent.ignored_stopwords)}")
            print(f"Phrase concepts: {', '.join(intent.phrase_concepts)}")
            print(f"Expanded concepts: {', '.join(intent.concepts)}")
        else:
            print(f"Concepts: {', '.join(intent.phrase_concepts or intent.concepts)}")
        print()
        for source, rows in trace["source_results"].items():
            print(f"{source}: {len(rows)} candidates")
        has_vector_sources = (
            "fast_vector" in trace["source_results"]
            or "deep_vector" in trace["source_results"]
        )
        if (
            has_vector_sources
            and not trace["source_results"].get("fast_vector")
            and not trace["source_results"].get("deep_vector")
        ):
            print("Warning: vector collections returned 0 candidates.")
            print("Run ./run.sh build-vector after building the SQLite DB.")
        print(f"Reranked candidates: {len(trace['reranked'])}")
        print(f"Accepted candidates: {len(trace['accepted'])}")
        print(f"Rejected candidates: {len(trace['rejected'])}")
        print()

    print("Hybrid results")
    print("-" * 45)
    if not results:
        print("No evidence matched.")
        if trace and trace["rejected"]:
            print("Reason: candidates were retrieved but rejected by the gate.")
        elif trace:
            print("Reason: no candidates found for this intent.")
            return
        if not trace:
            return
    for row in results:
        source = row.get("card_name") or row.get("author") or "Unknown"
        print(
            f"{row.get('reranker_score', 0):.3f} rerank  "
            f"{row['retrieval_score']:.6f} retrieval  {source:<18} "
            f"{row.get('section')}  |  {row.get('tag')}"
        )
        print(f"Ranks: {row.get('source_ranks')}")
        assessment = row.get("candidate_assessment") or row.get("reranker_assessment") or {}
        if assessment:
            print(
                "Assessment: "
                f"relationship={assessment.get('relationship')} "
                f"confidence={assessment.get('confidence')} "
                f"topic={assessment.get('topic_match')} "
                f"mechanism={assessment.get('mechanism_match')} "
                f"warrant={assessment.get('warrant_match')} "
                f"strength={assessment.get('evidence_strength')}"
            )
            matched = assessment.get("matched_concepts") or []
            missing = assessment.get("missing_concepts") or []
            if matched:
                print(f"Matched: {', '.join(matched)}")
            if missing:
                print(f"Missing: {', '.join(missing)}")
            if args.concept_debug and assessment.get("match_locations"):
                print("Match locations:")
                for field_name, matches in assessment["match_locations"].items():
                    print(f"- {field_name}: {', '.join(matches)}")
            for reason in assessment.get("reasons", [])[:4]:
                print(f"Reason: {reason}")
        if row.get("highlights"):
            print("Highlights:")
            for highlight in row["highlights"]:
                print(f"- {highlight.get('text')}")
        print()

    if trace and trace["rejected"]:
        print("Rejected")
        print("-" * 45)
        for row in trace["rejected"][:10]:
            source = row.get("card_name") or row.get("author") or "Unknown"
            assessment = row.get("candidate_assessment") or {}
            print(
                f"{source:<18} {assessment.get('relationship')}  "
                f"{assessment.get('rejection_reason')}"
            )
            matched = assessment.get("matched_concepts") or []
            missing = assessment.get("missing_concepts") or []
            if matched:
                print(f"  Matched: {', '.join(matched)}")
            if missing:
                print(f"  Missing: {', '.join(missing)}")
            if args.concept_debug and assessment.get("match_locations"):
                for field_name, matches in assessment["match_locations"].items():
                    print(f"  {field_name}: {', '.join(matches)}")


if __name__ == "__main__":
    main()
