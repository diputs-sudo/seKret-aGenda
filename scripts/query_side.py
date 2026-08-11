#!/usr/bin/env python3
"""Perspective-aware two-lane retrieval over hybrid candidates."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.debate import (
    DebateSide,
    DebateSideEngine,
    RoundContext,
    build_retrieval_probes,
    parse_debate_query,
)
from backend.embeddings import EmbeddingError, OllamaEmbedder
from backend.models.sqlite_store import connect, search_cards
from backend.rag import HybridRetrievalEngine, HybridSearchRequest
from backend.vector_db.chroma_store import ChromaDependencyError


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run perspective-aware two-lane debate retrieval."
    )
    parser.add_argument("query")
    parser.add_argument("--db", type=Path, default=Path("var/sekret-agenda.sqlite3"))
    parser.add_argument("--chroma", type=Path, default=Path("var/chroma"))
    parser.add_argument("--model", default=None)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--candidate-limit", type=int, default=30)
    parser.add_argument(
        "--no-vector",
        action="store_true",
        help="Use SQLite FTS candidates only, for testing without Ollama/Chroma.",
    )
    parser.add_argument(
        "--debug-candidates",
        action="store_true",
        help="Print retrieval probes, candidate lane decisions, and funnel stats.",
    )
    parser.add_argument(
        "--our-side",
        choices=[side.value for side in DebateSide],
        default=DebateSide.UNKNOWN.value,
    )
    parser.add_argument(
        "--opponent-side",
        choices=[side.value for side in DebateSide],
        default=DebateSide.UNKNOWN.value,
    )
    parser.add_argument("--resolution", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    try:
        debate_query = parse_debate_query(args.query)
        probes = build_retrieval_probes(debate_query)
        if args.no_vector:
            candidate_rows, retrieval_stats = _retrieve_sqlite_probes(
                args.db,
                probes,
                args.candidate_limit,
            )
        else:
            retrieval = HybridRetrievalEngine(
                db_path=args.db,
                chroma_path=args.chroma,
                embedder=OllamaEmbedder(model=args.model),
            )
            candidate_rows, retrieval_stats = _retrieve_hybrid_probes(
                retrieval,
                probes,
                args.limit,
                args.candidate_limit,
            )
    except ChromaDependencyError as exc:
        print(f"Side query failed: {exc}")
        return 1
    except EmbeddingError as exc:
        print(f"Side query failed: {exc}")
        print("Make sure Ollama is running and run: ollama pull nomic-embed-text")
        return 1

    engine = DebateSideEngine()
    context = RoundContext(
        our_side=DebateSide(args.our_side),
        opponent_side=DebateSide(args.opponent_side),
        resolution=args.resolution,
    )
    assessed = engine.assess_candidates(
        debate_query,
        candidate_rows,
        round_context=context,
    )
    side_result = engine.build_from_assessed(
        debate_query,
        assessed,
        round_context=context,
        limit_per_lane=args.limit,
    )

    query = side_result.query
    print("Debate query")
    print("-" * 45)
    print(f"Intent: {query.intent.value}")
    print(f"Perspective: {query.perspective.value}")
    print(f"Semantic query: {query.semantic_query}")
    print(f"Opponent claim: {query.opponent_claim or ''}")
    if query.control_language:
        print(f"Control language: {', '.join(query.control_language)}")
    print()

    if args.debug_candidates:
        _print_probes(probes)

    _print_lane("OUR ANSWERS", side_result.our_lane.candidates)
    _print_lane("OPPONENT EVIDENCE", side_result.opponent_lane.candidates)
    if args.debug_candidates:
        _print_candidate_audit(engine, query.intent, assessed)
        _print_funnel(engine, query.intent, retrieval_stats, assessed, side_result)
    return 0


def _retrieve_sqlite_probes(db_path: Path, probes, limit: int):
    probe_rows = []
    raw_count = 0
    with connect(db_path) as connection:
        for probe in probes:
            rows = search_cards(connection, probe.text, limit)
            raw_count += len(rows)
            probe_rows.append((probe, rows))
    return _union_probe_rows(probe_rows), {"raw_retrieval": raw_count}


def _retrieve_hybrid_probes(
    retrieval: HybridRetrievalEngine,
    probes,
    result_limit: int,
    candidate_limit: int,
):
    probe_rows = []
    raw_count = 0
    for probe in probes:
        trace = retrieval.debug_trace(
            HybridSearchRequest(
                query=probe.text,
                limit=result_limit,
                vector_limit=candidate_limit,
                lexical_limit=candidate_limit,
            )
        )
        rows = trace["reranked"]
        raw_count += sum(len(rows) for rows in trace.get("source_results", {}).values())
        probe_rows.append((probe, rows))
    return _union_probe_rows(probe_rows), {"raw_retrieval": raw_count}


def _union_probe_rows(probe_rows):
    merged_by_id = {}
    for probe, rows in probe_rows:
        for rank, row in enumerate(rows, start=1):
            card_id = str(row.get("card_id") or row.get("id") or "")
            if not card_id:
                continue
            normalized = dict(row)
            normalized["card_id"] = card_id
            normalized["retrieval_score"] = _row_retrieval_score(row)
            metadata = dict(normalized.get("metadata") or {})
            metadata.setdefault("probe_hits", [])
            metadata["probe_hits"].append(
                {
                    "kind": probe.kind,
                    "text": probe.text,
                    "rank": rank,
                    "score": _row_retrieval_score(row),
                }
            )
            normalized["metadata"] = metadata

            existing = merged_by_id.get(card_id)
            if existing is None:
                merged_by_id[card_id] = normalized
                continue
            merged_by_id[card_id] = _merge_candidate(existing, normalized)
    return sorted(
        merged_by_id.values(),
        key=lambda row: float(row.get("retrieval_score") or 0),
        reverse=True,
    )


def _merge_candidate(existing, incoming):
    merged = dict(existing)
    if _row_retrieval_score(incoming) > _row_retrieval_score(existing):
        merged.update({key: value for key, value in incoming.items() if value not in (None, "", [])})
    else:
        for key, value in incoming.items():
            if merged.get(key) in (None, "", []) and value not in (None, "", []):
                merged[key] = value
    metadata = dict(existing.get("metadata") or {})
    incoming_metadata = dict(incoming.get("metadata") or {})
    metadata.update({key: value for key, value in incoming_metadata.items() if key != "probe_hits"})
    metadata["probe_hits"] = (existing.get("metadata") or {}).get("probe_hits", []) + incoming_metadata.get("probe_hits", [])
    merged["metadata"] = metadata
    merged["retrieval_score"] = max(_row_retrieval_score(existing), _row_retrieval_score(incoming))
    return merged


def _row_retrieval_score(row) -> float:
    try:
        return float(row.get("retrieval_score") or row.get("score") or 0)
    except (TypeError, ValueError):
        return 0.0


def _print_probes(probes) -> None:
    print("RETRIEVAL PROBES")
    print("-" * 45)
    for probe in probes:
        print(f"{probe.kind}: {probe.text}")
    print()


def _print_lane(title: str, candidates) -> None:
    print(title)
    print("-" * 45)
    if not candidates:
        print("No cards in this lane.")
        print()
        return
    for index, candidate in enumerate(candidates, start=1):
        card = candidate.card
        label = card.get("card_name") or card.get("author") or candidate.card_id
        print(
            f"{index}. {candidate.final_score:.3f}  "
            f"{label}  [{candidate.owner.value}]"
        )
        print(f"   relationship: {candidate.relationship}")
        print(
            "   scores: "
            f"relationship={candidate.relationship_confidence:.3f}, "
            f"directness={candidate.directness:.3f}, "
            f"topic={candidate.topic_score:.3f}, "
            f"mechanism={candidate.mechanism_score:.3f}, "
            f"utility={candidate.relationship_utility:.3f}"
        )
        print(f"   tag: {card.get('tag') or ''}")
        if candidate.reasons:
            print(f"   reasons: {'; '.join(candidate.reasons[:3])}")
    print()


def _print_candidate_audit(engine: DebateSideEngine, intent, candidates) -> None:
    print("CANDIDATE AUDIT")
    print("-" * 45)
    for index, candidate in enumerate(candidates, start=1):
        card = candidate.card
        label = card.get("card_name") or card.get("author") or candidate.card_id
        print(f"{index}. {label} [{candidate.owner.value}]")
        print(f"   tag: {card.get('tag') or ''}")
        print(
            "   assessment: "
            f"relationship={candidate.relationship} "
            f"{candidate.relationship_confidence:.3f}, "
            f"directness={candidate.directness:.3f}, "
            f"topic={candidate.topic_score:.3f}, "
            f"mechanism={candidate.mechanism_score:.3f}"
        )
        for lane in ("our", "opponent"):
            decision = engine.lane_decision(candidate, intent, lane)
            status = "ACCEPT" if decision["accepted"] else "REJECT"
            print(
                f"   {lane.upper()}: {status} "
                f"reason={decision['reason']} "
                f"utility={decision['relationship_utility']:.3f} "
                f"final={decision['final_score']:.3f}"
            )
        probes = (card.get("metadata") or {}).get("probe_hits") or []
        if probes:
            probe_bits = [
                f"{probe['kind']}#{probe['rank']}"
                for probe in probes[:4]
            ]
            print(f"   probes: {', '.join(probe_bits)}")
    print()


def _print_funnel(engine: DebateSideEngine, intent, retrieval_stats, assessed, side_result) -> None:
    print("CANDIDATE FUNNEL")
    print("-" * 45)
    print(f"Raw retrieval:          {retrieval_stats.get('raw_retrieval', 0)}")
    print(f"After dedup:            {len(assessed)}")
    print(f"Relationship assessed:  {len(assessed)}")
    _print_lane_funnel("OUR ANSWERS", engine, intent, "our", assessed, len(side_result.our_lane.candidates))
    _print_lane_funnel(
        "OPPONENT EVIDENCE",
        engine,
        intent,
        "opponent",
        assessed,
        len(side_result.opponent_lane.candidates),
    )
    print()


def _print_lane_funnel(title: str, engine: DebateSideEngine, intent, lane: str, assessed, returned: int) -> None:
    decisions = [engine.lane_decision(candidate, intent, lane) for candidate in assessed]
    eligible = [decision for decision in decisions if decision["eligible"]]
    accepted = [decision for decision in decisions if decision["accepted"]]
    hard_gated = [
        decision
        for decision in eligible
        if not decision["accepted"] and decision["reason"] != "accepted"
    ]
    print()
    print(title)
    print(f"Eligible:               {len(eligible)}")
    print(f"Hard-gated:             {len(hard_gated)}")
    print(f"Accepted before top-k:  {len(accepted)}")
    print(f"Returned:               {returned}")


if __name__ == "__main__":
    raise SystemExit(main())
