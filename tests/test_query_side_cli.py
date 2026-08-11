from scripts.query_side import parse_args
from scripts.query_side import _retrieve_hybrid_probes
from backend.debate import parse_debate_query


class FakeProbe:
    def __init__(self, kind: str):
        self.kind = kind
        self.text = kind
        self.channel = "semantic"


class FakeHybridRetrieval:
    def __init__(self):
        self.calls = []
        self.embedder = FakeBatchEmbedder()

    def candidate_trace(self, request):
        self.calls.append((request.query, request.vector_limit))
        rows_by_query = {
            "productive": [
                _row("1", "A"),
                _row("2", "B"),
                _row("3", "C"),
            ],
            "redundant": [
                _row("1", "A"),
                _row("2", "B"),
                _row("3", "C"),
            ],
            "zero1": [
                _row("1", "A"),
                _row("2", "B"),
                _row("3", "C"),
            ],
            "zero2": [
                _row("1", "A"),
                _row("2", "B"),
                _row("3", "C"),
            ],
        }
        rows = rows_by_query[request.query]
        return {
            "candidates": rows,
            "source_results": {"fake": rows},
            "timings": {
                "query_embedding": 0.0,
                "fast_vector": 1.0,
                "deep_vector": 1.0,
            },
        }

    def rerank_candidates(self, query, rows, limit=None):
        del query
        selected = rows[:limit] if limit is not None else rows
        return selected, {
            "parse_intent": 0.0,
            "sqlite_hydration": 0.0,
            "filter": 0.0,
            "rerank": 0.0,
            "total": 0.0,
            "accounted": 0.0,
            "unaccounted": 0.0,
        }


class FakeBatchEmbedder:
    model = "fake"

    def embed_many(self, texts):
        return [[float(index)] for index, _ in enumerate(texts)]


def _row(card_id: str, evidence_id: str) -> dict[str, object]:
    return {
        "card_id": card_id,
        "metadata": {"content_hash": evidence_id},
        "retrieval_score": 1.0,
    }


def test_side_cli_options_before_query_do_not_enter_debate_query():
    args = parse_args(
        [
            "--target-novel",
            "8",
            "--max-depth",
            "120",
            "--debug-candidates",
            "opponent says Trump nuclear posture deletes diplomacy",
        ]
    )
    query = parse_debate_query(args.query)

    assert args.target_novel == 8
    assert args.max_depth == 120
    assert query.opponent_claim == "Trump nuclear posture deletes diplomacy"
    assert "--target-novel" not in query.semantic_query
    assert "--max-depth" not in query.semantic_query


def test_side_cli_options_after_query_do_not_enter_debate_query():
    args = parse_args(
        [
            "opponent says Trump nuclear posture deletes diplomacy",
            "--debug-candidates",
            "--target-novel",
            "8",
            "--max-depth",
            "120",
        ]
    )
    query = parse_debate_query(args.query)

    assert args.target_novel == 8
    assert args.max_depth == 120
    assert query.opponent_claim == "Trump nuclear posture deletes diplomacy"
    assert "--target-novel" not in query.semantic_query
    assert "--max-depth" not in query.semantic_query


def test_hybrid_probe_scheduler_stops_redundant_probe_after_first_round():
    retrieval = FakeHybridRetrieval()
    probes = [FakeProbe("productive"), FakeProbe("redundant")]

    _, stats = _retrieve_hybrid_probes(
        retrieval,
        probes,
        "productive",
        result_limit=5,
        candidate_limit=10,
        target_novel=3,
        max_depth=40,
        max_active_probes=2,
    )

    by_kind = {row["kind"]: row for row in stats["probe_stats"]}
    assert by_kind["productive"]["retrieval_rounds"] == 1
    assert by_kind["productive"]["stopped_reason"] == "target reached"
    assert by_kind["redundant"]["retrieval_rounds"] == 1
    assert by_kind["redundant"]["stopped_reason"] == "no marginal novel evidence"


def test_hybrid_probe_scheduler_skips_after_global_pool_saturation():
    retrieval = FakeHybridRetrieval()
    probes = [
        FakeProbe("productive"),
        FakeProbe("zero1"),
        FakeProbe("zero2"),
        FakeProbe("skipped"),
    ]

    _, stats = _retrieve_hybrid_probes(
        retrieval,
        probes,
        "productive",
        result_limit=5,
        candidate_limit=10,
        target_novel=3,
        max_depth=40,
        max_active_probes=2,
    )

    by_kind = {row["kind"]: row for row in stats["probe_stats"]}
    assert by_kind["zero1"]["retrieval_rounds"] == 1
    assert by_kind["zero2"]["retrieval_rounds"] == 1
    assert by_kind["skipped"]["retrieval_rounds"] == 0
    assert by_kind["skipped"]["stopped_reason"] == "global pool saturation"
    assert "skipped" not in [query for query, _ in retrieval.calls]
