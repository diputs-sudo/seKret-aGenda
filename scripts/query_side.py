#!/usr/bin/env python3
"""Perspective-aware two-lane retrieval over hybrid candidates."""

from __future__ import annotations

import argparse
import sys
import time
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
        "--target-novel",
        type=int,
        default=8,
        help="In vector mode, deepen a probe until it adds this many novel evidence items.",
    )
    parser.add_argument(
        "--max-depth",
        type=int,
        default=120,
        help="Maximum per-probe candidate depth for adaptive vector retrieval.",
    )
    parser.add_argument(
        "--max-active-probes",
        type=int,
        default=3,
        help="Maximum probes allowed to receive deeper retrieval rounds.",
    )
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
    overall_started = time.perf_counter()
    args = parse_args(argv or sys.argv[1:])
    timings: dict[str, float] = {}
    try:
        started = time.perf_counter()
        debate_query = parse_debate_query(args.query)
        probes = build_retrieval_probes(debate_query)
        timings["query_parse"] = _elapsed_ms(started)
        if args.no_vector:
            started = time.perf_counter()
            candidate_rows, retrieval_stats = _retrieve_sqlite_probes(
                args.db,
                probes,
                args.candidate_limit,
            )
            timings["retrieval"] = _elapsed_ms(started)
        else:
            retrieval = HybridRetrievalEngine(
                db_path=args.db,
                chroma_path=args.chroma,
                embedder=OllamaEmbedder(model=args.model),
            )
            started = time.perf_counter()
            candidate_rows, retrieval_stats = _retrieve_hybrid_probes(
                retrieval,
                probes,
                args.limit,
                args.candidate_limit,
                args.target_novel,
                args.max_depth,
                args.max_active_probes,
            )
            timings["retrieval"] = _elapsed_ms(started)
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
    started = time.perf_counter()
    assessed = engine.assess_candidates(
        debate_query,
        candidate_rows,
        round_context=context,
    )
    timings["relationship_classify"] = _elapsed_ms(started)
    started = time.perf_counter()
    side_result = engine.build_from_assessed(
        debate_query,
        assessed,
        round_context=context,
        limit_per_lane=args.limit,
    )
    timings["lane_projection"] = _elapsed_ms(started)
    timings["total"] = _elapsed_ms(overall_started)

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
        _print_probe_contribution(engine, query.intent, retrieval_stats, assessed)
        _print_funnel(engine, query.intent, retrieval_stats, assessed, side_result)
        _print_timing(timings, retrieval_stats, assessed)
    return 0


def _retrieve_sqlite_probes(db_path: Path, probes, limit: int):
    probe_rows = []
    raw_count = 0
    retrieval_calls = 0
    sqlite_probes = [
        probe for probe in probes if probe.channel in {"both", "lexical"}
    ]
    with connect(db_path) as connection:
        for probe in sqlite_probes:
            started = time.perf_counter()
            rows = search_cards(connection, probe.text, limit)
            elapsed_ms = _elapsed_ms(started)
            retrieval_calls += 1
            raw_count += len(rows)
            probe_rows.append(
                (
                    probe,
                    rows,
                    {
                        "elapsed_ms": elapsed_ms,
                        "retrieval_rounds": 1,
                        "depth_reached": limit,
                        "stopped_reason": "fts-only",
                    },
                )
            )
    candidates, probe_stats = _union_probe_rows(probe_rows)
    return candidates, {
        "raw_retrieval": raw_count,
        "probes_used": len(sqlite_probes),
        "probes_skipped": len(probes) - len(sqlite_probes),
        "retrieval_calls": retrieval_calls,
        "embedding_calls_estimate": 0,
        "probe_stats": probe_stats,
    }


def _retrieve_hybrid_probes(
    retrieval: HybridRetrievalEngine,
    probes,
    result_limit: int,
    candidate_limit: int,
    target_novel: int,
    max_depth: int,
    max_active_probes: int,
):
    max_active_probes = max(1, max_active_probes)
    initial_depth = max(1, candidate_limit)
    max_depth = max(initial_depth, max_depth)
    probe_states = []
    raw_count = 0
    seen_evidence: set[str] = set()
    unique_probe_texts = list(dict.fromkeys(probe.text for probe in probes))
    embedding_started = time.perf_counter()
    probe_embeddings = dict(
        zip(unique_probe_texts, retrieval.embedder.embed_many(unique_probe_texts))
    )
    embedding_batch_ms = _elapsed_ms(embedding_started)
    consecutive_zero_semantic = 0

    for probe in probes:
        state = _new_probe_state(probe, target_novel)
        if probe.channel == "semantic" and consecutive_zero_semantic >= 2:
            state["stopped_reason"] = "global pool saturation"
            probe_states.append(state)
            continue
        _run_hybrid_probe_round(
            retrieval,
            state,
            initial_depth,
            result_limit,
            seen_evidence,
            probe_embeddings[probe.text],
        )
        raw_count += state["raw_count"]
        probe_states.append(state)
        if probe.channel == "semantic":
            if int(state["novel_at_depth"]) == 0:
                consecutive_zero_semantic += 1
            else:
                consecutive_zero_semantic = 0

    active = _select_expandable_probe_states(
        probe_states,
        target_novel,
        max_depth,
        max_active_probes,
    )
    while active:
        next_active = []
        for state in active:
            depth = int(state["depth_reached"] or initial_depth)
            next_depth = min(max_depth, max(depth + 1, depth * 2))
            if next_depth <= depth:
                state["stopped_reason"] = "max depth"
                continue
            previous_raw_count = int(state["raw_count"])
            _run_hybrid_probe_round(
                retrieval,
                state,
                next_depth,
                result_limit,
                seen_evidence,
                probe_embeddings[probe.text],
            )
            raw_count += int(state["raw_count"]) - previous_raw_count
            reason = _probe_stop_reason(state, target_novel, max_depth)
            if reason is None:
                next_active.append(state)
            else:
                state["stopped_reason"] = reason

        active = _select_expandable_probe_states(
            next_active,
            target_novel,
            max_depth,
            max_active_probes,
        )

    probe_rows = [
        (
            state["probe"],
            state["rows"],
            {
                "depth_reached": state["depth_reached"],
                "retrieval_rounds": state["retrieval_rounds"],
                "target_novel": target_novel,
                "novel_at_depth": state["novel_at_depth"],
                "total_novel": state["total_novel"],
                "target_reached": state["target_reached"],
                "elapsed_ms": state["elapsed_ms"],
                "internal_timings": state["internal_timings"],
                "stopped_reason": state.get("stopped_reason") or "not expanded",
            },
        )
        for state in probe_states
    ]
    candidates, probe_stats = _union_probe_rows(probe_rows)
    return candidates, {
        "raw_retrieval": raw_count,
        "probes_used": sum(
            1 for state in probe_states if int(state["retrieval_rounds"]) > 0
        ),
        "probes_skipped": sum(
            1 for state in probe_states if int(state["retrieval_rounds"]) == 0
        ),
        "retrieval_calls": sum(
            int(state["retrieval_rounds"]) for state in probe_states
        ),
        "embedding_batches": 1 if unique_probe_texts else 0,
        "embedding_texts": len(unique_probe_texts),
        "embedding_batch_ms": embedding_batch_ms,
        "embedding_calls_estimate": len(unique_probe_texts),
        "probe_stats": probe_stats,
    }


def _new_probe_state(probe, target_novel: int) -> dict[str, object]:
    return {
        "probe": probe,
        "rows": [],
        "raw_count": 0,
        "elapsed_ms": 0.0,
        "internal_timings": {},
        "depth_reached": None,
        "retrieval_rounds": 0,
        "target_novel": target_novel,
        "novel_at_depth": 0,
        "total_novel": 0,
        "target_reached": False,
        "unique_hits": 0,
        "stopped_reason": "",
    }


def _run_hybrid_probe_round(
    retrieval: HybridRetrievalEngine,
    state: dict[str, object],
    depth: int,
    result_limit: int,
    seen_evidence: set[str],
    query_embedding: list[float],
) -> None:
    probe = state["probe"]
    started = time.perf_counter()
    trace = retrieval.debug_trace(
        HybridSearchRequest(
            query=probe.text,
            limit=max(result_limit, depth),
            vector_limit=depth,
            lexical_limit=depth,
            query_embedding=query_embedding,
        )
    )
    elapsed_ms = _elapsed_ms(started)
    trace_timings = trace.get("timings") or {}
    rows = trace["reranked"]
    unique_keys = {_evidence_key(row) for row in rows}
    novel_keys = unique_keys - seen_evidence
    seen_evidence.update(novel_keys)

    state["rows"] = rows
    state["raw_count"] = int(state["raw_count"]) + sum(
        len(rows) for rows in trace.get("source_results", {}).values()
    )
    state["elapsed_ms"] = float(state["elapsed_ms"]) + elapsed_ms
    internal_timings = dict(state.get("internal_timings") or {})
    for key, value in trace_timings.items():
        internal_timings[key] = internal_timings.get(key, 0.0) + float(value or 0.0)
    trace_total = float(trace_timings.get("total") or 0.0)
    internal_timings["scheduler_wrapper"] = internal_timings.get(
        "scheduler_wrapper", 0.0
    ) + max(0.0, elapsed_ms - trace_total)
    state["internal_timings"] = internal_timings
    state["depth_reached"] = depth
    state["retrieval_rounds"] = int(state["retrieval_rounds"]) + 1
    state["novel_at_depth"] = len(novel_keys)
    state["total_novel"] = int(state["total_novel"]) + len(novel_keys)
    state["target_reached"] = int(state["total_novel"]) >= int(state["target_novel"])
    state["unique_hits"] = len(unique_keys)


def _select_expandable_probe_states(
    states: list[dict[str, object]],
    target_novel: int,
    max_depth: int,
    max_active_probes: int,
) -> list[dict[str, object]]:
    expandable = []
    for state in states:
        if int(state.get("retrieval_rounds") or 0) == 0:
            continue
        reason = _probe_stop_reason(state, target_novel, max_depth)
        if reason is None:
            expandable.append(state)
        else:
            state["stopped_reason"] = reason

    expandable.sort(
        key=lambda state: (
            int(state["total_novel"]),
            _probe_novelty_rate(state),
            -float(state["elapsed_ms"]),
        ),
        reverse=True,
    )
    selected = expandable[:max_active_probes]
    for state in expandable[max_active_probes:]:
        state["stopped_reason"] = "not expanded by scheduler budget"
    return selected


def _probe_stop_reason(
    state: dict[str, object],
    target_novel: int,
    max_depth: int,
) -> str | None:
    if bool(state["target_reached"]) or int(state["total_novel"]) >= target_novel:
        return "target reached"
    if int(state["depth_reached"] or 0) >= max_depth:
        return "max depth"
    if int(state["novel_at_depth"]) == 0:
        return "no marginal novel evidence"
    if _probe_novelty_rate(state) < 0.10:
        return "low novelty rate"
    return None


def _probe_novelty_rate(state: dict[str, object]) -> float:
    unique_hits = int(state.get("unique_hits") or 0)
    if unique_hits <= 0:
        return 0.0
    return int(state.get("novel_at_depth") or 0) / unique_hits


def _union_probe_rows(probe_rows):
    merged_by_id = {}
    seen_pool_evidence: set[str] = set()
    probe_stats = {
        probe.kind: {
            "kind": probe.kind,
            "channel": probe.channel,
            "raw_hits": 0,
            "unique_hits": 0,
            "unique_added": 0,
            "depth_reached": metadata.get("depth_reached"),
            "retrieval_rounds": metadata.get("retrieval_rounds"),
            "target_novel": metadata.get("target_novel"),
            "novel_at_depth": metadata.get("novel_at_depth"),
            "total_novel": metadata.get("total_novel"),
            "target_reached": metadata.get("target_reached"),
            "elapsed_ms": metadata.get("elapsed_ms"),
            "internal_timings": metadata.get("internal_timings"),
            "stopped_reason": metadata.get("stopped_reason"),
        }
        for probe, _, metadata in _normalize_probe_rows(probe_rows)
    }
    for probe, rows, _ in _normalize_probe_rows(probe_rows):
        probe_stats[probe.kind]["raw_hits"] += len(rows)
        probe_stats[probe.kind]["unique_hits"] = len(
            {_evidence_key(row) for row in rows}
        )
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
                evidence_key = _evidence_key(normalized)
                normalized["metadata"]["added_by_probe"] = probe.kind
                if evidence_key not in seen_pool_evidence:
                    seen_pool_evidence.add(evidence_key)
                    probe_stats[probe.kind]["unique_added"] += 1
                merged_by_id[card_id] = normalized
                continue
            merged_by_id[card_id] = _merge_candidate(existing, normalized)
    candidates = sorted(
        merged_by_id.values(),
        key=lambda row: float(row.get("retrieval_score") or 0),
        reverse=True,
    )
    return candidates, list(probe_stats.values())


def _normalize_probe_rows(probe_rows):
    normalized = []
    for item in probe_rows:
        if len(item) == 2:
            probe, rows = item
            metadata = {}
        else:
            probe, rows, metadata = item
        normalized.append((probe, rows, metadata))
    return normalized


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
    first_added_by = metadata.get("added_by_probe")
    metadata.update({key: value for key, value in incoming_metadata.items() if key not in {"probe_hits", "added_by_probe"}})
    if first_added_by:
        metadata["added_by_probe"] = first_added_by
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
        print(f"{probe.kind} [{probe.channel}]: {probe.text}")
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
            f"warrant={candidate.warrant_score:.3f}, "
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
            f"   relationship: {candidate.relationship} "
            f"confidence={candidate.relationship_confidence:.3f}"
        )
        print(
            "   match: "
            f"directness={candidate.directness:.3f}, "
            f"topic={candidate.topic_score:.3f}, "
            f"mechanism={candidate.mechanism_score:.3f}, "
            f"warrant={candidate.warrant_score:.3f}"
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


def _print_probe_contribution(engine: DebateSideEngine, intent, retrieval_stats, assessed) -> None:
    stats = {
        row["kind"]: dict(
            row,
            our_candidates_added=0,
            accepted_answers_added=0,
        )
        for row in retrieval_stats.get("probe_stats", [])
    }
    for candidate in assessed:
        metadata = candidate.card.get("metadata") or {}
        added_by = metadata.get("added_by_probe")
        if not added_by or added_by not in stats:
            continue
        decision = engine.lane_decision(candidate, intent, "our")
        if decision["eligible"]:
            stats[added_by]["our_candidates_added"] += 1
        if decision["accepted"]:
            stats[added_by]["accepted_answers_added"] += 1

    print("PROBE CONTRIBUTION")
    print("-" * 45)
    if not stats:
        print("No probe contribution data.")
        print()
        return
    for row in stats.values():
        print(row["kind"])
        print(f"  channel:                {row['channel']}")
        print(f"  raw hits:               {row['raw_hits']}")
        print(f"  unique hits:            {row['unique_hits']}")
        print(f"  new to pool:            {row['unique_added']}")
        if row.get("depth_reached") is not None:
            print(f"  depth reached:          {row['depth_reached']}")
            print(f"  retrieval rounds:       {row['retrieval_rounds']}")
            if row.get("target_novel") is not None:
                print(f"  target novel:           {row['target_novel']}")
            if row.get("novel_at_depth") is not None:
                print(f"  novel at depth:         {row['novel_at_depth']}")
            if row.get("total_novel") is not None:
                print(f"  total novel:            {row['total_novel']}")
            if row.get("target_reached") is not None:
                print(f"  target reached:         {_yes_no(row['target_reached'])}")
            if row.get("stopped_reason"):
                print(f"  stopped reason:         {row['stopped_reason']}")
            if row.get("elapsed_ms") is not None:
                print(f"  elapsed:                {row['elapsed_ms']:.1f} ms")
            if row.get("internal_timings"):
                print("  internal timing:")
                for key, value in row["internal_timings"].items():
                    print(f"    {key}: {value:.1f} ms")
        print(f"  our candidates added:   {row['our_candidates_added']}")
        print(f"  accepted answers added: {row['accepted_answers_added']}")
    print()


def _print_funnel(engine: DebateSideEngine, intent, retrieval_stats, assessed, side_result) -> None:
    print("CANDIDATE FUNNEL")
    print("-" * 45)
    unique_evidence = {_evidence_key(candidate.card) for candidate in assessed}
    print(f"Raw probe hits:          {retrieval_stats.get('raw_retrieval', 0)}")
    print(f"Probes used:             {retrieval_stats.get('probes_used', 0)}")
    print(f"Probes skipped:          {retrieval_stats.get('probes_skipped', 0)}")
    print(f"Unique card instances:   {len(assessed)}")
    print(f"Unique evidence:         {len(unique_evidence)}")
    print(f"Relationship assessed:   {len(unique_evidence)}")
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
    rejection_counts = {}
    for decision in decisions:
        if decision["accepted"]:
            continue
        reason = str(decision["reason"])
        rejection_counts[reason] = rejection_counts.get(reason, 0) + 1
    if rejection_counts:
        print("Rejected:")
        for reason, count in sorted(
            rejection_counts.items(),
            key=lambda item: (-item[1], item[0]),
        ):
            print(f"  {reason}: {count}")


def _print_timing(timings, retrieval_stats, assessed) -> None:
    print("TIMING")
    print("-" * 45)
    for key, label in (
        ("query_parse", "query parse"),
        ("retrieval", "retrieval"),
        ("relationship_classify", "relationship classify"),
        ("lane_projection", "lane projection"),
        ("total", "total"),
    ):
        if key in timings:
            print(f"{label}: {timings[key]:.1f} ms")

    probe_stats = retrieval_stats.get("probe_stats", [])
    if probe_stats:
        print()
        print("retrieval by probe:")
        for row in probe_stats:
            elapsed = row.get("elapsed_ms")
            if elapsed is None:
                continue
            print(f"  {row['kind']}: {elapsed:.1f} ms")

    print()
    print("MODEL CALLS")
    print("-" * 45)
    print(f"retrieval calls:          {retrieval_stats.get('retrieval_calls', 0)}")
    if "embedding_batches" in retrieval_stats:
        print(f"embedding batches:        {retrieval_stats.get('embedding_batches', 0)}")
        print(f"embedding texts:          {retrieval_stats.get('embedding_texts', 0)}")
        print(
            "embedding batch time:     "
            f"{retrieval_stats.get('embedding_batch_ms', 0.0):.1f} ms"
        )
    print(
        "embedding calls estimate: "
        f"{retrieval_stats.get('embedding_calls_estimate', 0)}"
    )
    unique_evidence = {_evidence_key(candidate.card) for candidate in assessed}
    print(f"relationship assessments: {len(unique_evidence)}")
    print("reranker model calls:     0")
    print()


def _evidence_key(card) -> str:
    metadata = card.get("metadata") or {}
    for key in ("content_hash", "evidence_id"):
        value = card.get(key) or metadata.get(key)
        if value:
            return f"{key}:{value}"
    return "|".join(
        str(card.get(key) or "")
        for key in ("card_name", "citation", "tag")
    ).lower()


def _yes_no(value) -> str:
    return "yes" if value else "no"


def _elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


if __name__ == "__main__":
    raise SystemExit(main())
