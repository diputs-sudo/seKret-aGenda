"""Direction and response-schema tests independent of an LLM."""

from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, relative_path: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


EVAL = load_module("semantic_map_eval", "scripts/eval_semantic_map.py")
WORKER = load_module("semantic_ai_worker", "scripts/semantic_ai_worker.py")


def test_direction_renders_explicit_graph_endpoints() -> None:
    assert EVAL.direction_from_ids("A", "B", "A", "B") == "left_to_right"
    assert EVAL.direction_from_ids("A", "B", "B", "A") == "right_to_left"
    assert EVAL.direction_from_ids("A", "B", None, None) == "undirected"
    assert EVAL.direction_from_ids("A", "B", "C", "A") == "invalid"


def test_expected_direction_maps_to_explicit_endpoints() -> None:
    assert EVAL.expected_endpoints(
        {"left": "A", "right": "B", "expected": "SUPPORTS", "direction": "left_to_right"}
    ) == ("A", "B")
    assert EVAL.expected_endpoints(
        {"left": "A", "right": "B", "expected": "ATTACKS", "direction": "right_to_left"}
    ) == ("B", "A")
    assert EVAL.expected_endpoints(
        {"left": "A", "right": "B", "expected": "SAME_ARGUMENT"}
    ) == (None, None)
    assert EVAL.expected_endpoints(
        {"left": "A", "right": "B", "expected": "RELATED"}
    ) == (None, None)
    assert EVAL.expected_endpoints(
        {"left": "A", "right": "B", "expected": "UNRELATED"}
    ) == (None, None)


def test_worker_preserves_right_to_left_support_edge() -> None:
    worker = WORKER.Worker(
        "ollama", "embed", "relation", "normalization", "http://example.invalid", Path("/tmp/unused-semantic-cache.json"), True
    )
    worker.chat_json = lambda *_: {
        "status": "OK",
        "data": {
            "relationship": "SUPPORTS",
            "source_argument": "B",
            "target_argument": "A",
            "confidence": 0.9,
            "reason": "B is evidence for A.",
        },
        "rawResponse": '{"relationship":"SUPPORTS","source_argument":"B","target_argument":"A"}',
    }
    result = worker.relationship({"id": "A", "text": "claim"}, {"id": "B", "text": "evidence"})
    assert result["status"] == "OK"
    assert result["source_argument"] == "B"
    assert result["target_argument"] == "A"


def test_worker_rejects_directed_relation_without_endpoints() -> None:
    worker = WORKER.Worker(
        "ollama", "embed", "relation", "normalization", "http://example.invalid", Path("/tmp/unused-semantic-cache.json"), True
    )
    worker.chat_json = lambda *_: {
        "status": "OK",
        "data": {"relationship": "ATTACKS", "confidence": 0.9},
        "rawResponse": '{"relationship":"ATTACKS"}',
    }
    result = worker.relationship({"id": "A", "text": "claim"}, {"id": "B", "text": "response"})
    assert result["status"] == "INVALID_SCHEMA"
    assert "source_argument" in result["error"]


def test_worker_canonicalizes_undirected_endpoints() -> None:
    worker = WORKER.Worker(
        "ollama", "embed", "relation", "normalization", "http://example.invalid", Path("/tmp/unused-semantic-cache.json"), True
    )
    worker.chat_json = lambda *_: {
        "status": "OK",
        "data": {
            "relationship": "SAME_ARGUMENT",
            "source_argument": "A",
            "target_argument": "B",
        },
        "rawResponse": '{"relationship":"SAME_ARGUMENT","source_argument":"A","target_argument":"B"}',
    }
    result = worker.relationship({"id": "A", "text": "claim"}, {"id": "B", "text": "paraphrase"})
    assert result["status"] == "OK"
    assert result["source_argument"] is None
    assert result["target_argument"] is None


def test_worker_rejects_combined_or_invented_relationship_labels() -> None:
    worker = WORKER.Worker(
        "ollama", "embed", "relation", "normalization", "http://example.invalid", Path("/tmp/unused-semantic-cache.json"), True
    )
    worker.chat_json = lambda *_: {
        "status": "OK",
        "data": {"relationship": "SAME_ARGUMENT|RELATED"},
        "rawResponse": '{"relationship":"SAME_ARGUMENT|RELATED"}',
    }
    result = worker.relationship({"id": "A", "text": "claim"}, {"id": "B", "text": "paraphrase"})
    assert result["status"] == "INVALID_SCHEMA"
    assert "invalid relationship" in result["error"]


def test_worker_rejects_relationship_aliases_and_noncanonical_case() -> None:
    worker = WORKER.Worker(
        "ollama", "embed", "relation", "normalization", "http://example.invalid", Path("/tmp/unused-semantic-cache.json"), True
    )
    for label in ("NONE", "supports", "OPPOSITES"):
        worker.chat_json = lambda *_args, chosen_label=label: {
            "status": "OK",
            "data": {"relationship": chosen_label},
            "rawResponse": json.dumps({"relationship": chosen_label}),
        }
        result = worker.relationship({"id": "A", "text": "claim"}, {"id": "B", "text": "response"})
        assert result["status"] == "INVALID_SCHEMA"
        assert "invalid relationship" in result["error"]


def test_chat_parse_error_preserves_raw_model_content() -> None:
    worker = WORKER.Worker(
        "ollama", "embed", "relation", "normalization", "http://example.invalid", Path("/tmp/unused-semantic-cache.json"), True
    )
    worker.ollama_json = lambda *_: ({"message": {"content": "not json"}}, '{"message":{"content":"not json"}}')
    result = worker.chat_json("instruction", "content", "relation")
    assert result["status"] == "PARSE_ERROR"
    assert result["rawResponse"] == "not json"


def test_chat_model_error_is_not_converted_to_unrelated() -> None:
    worker = WORKER.Worker(
        "ollama", "embed", "relation", "normalization", "http://example.invalid", Path("/tmp/unused-semantic-cache.json"), True
    )
    worker.ollama_json = lambda *_: (_ for _ in ()).throw(WORKER.WorkerError("HTTP 400: bad model"))
    result = worker.chat_json("instruction", "content", "relation")
    assert result["status"] == "MODEL_ERROR"
    assert result["rawResponse"] == "HTTP 400: bad model"


def test_cache_invalidation_is_scoped_to_the_operation(tmp_path: Path) -> None:
    worker = WORKER.Worker(
        "ollama", "embed-v1", "relation-v1", "normalization-v1",
        "http://example.invalid", tmp_path / "cache.json", False,
    )
    calls = 0

    def embed_result():
        nonlocal calls
        calls += 1
        return [[0.1, 0.2]]

    worker.cached("embed_batch", {"texts": ["text"], "dimensions": 2}, 1, embed_result)
    worker.relation_model = "relation-v2"
    worker.cached("embed_batch", {"texts": ["text"], "dimensions": 2}, 1, embed_result)
    assert calls == 1

    def relationship_result():
        nonlocal calls
        calls += 1
        return {"status": "OK", "relationship": "RELATED"}

    worker.cached("relationship", {"left": "a", "right": "b"}, 1, relationship_result)
    worker.relation_model = "relation-v3"
    worker.cached("relationship", {"left": "a", "right": "b"}, 1, relationship_result)
    assert calls == 3


class _FakeInput:
    def write(self, _value: str) -> int:
        return 0

    def flush(self) -> None:
        return None


class _FakeProcess:
    def __init__(self, response: dict):
        self.stdin = _FakeInput()
        self.stdout = io.StringIO(json.dumps(response) + "\n")


def test_evaluator_keeps_structured_schema_errors_as_predictions() -> None:
    client = EVAL.WorkerClient.__new__(EVAL.WorkerClient)
    client.process = _FakeProcess({"status": "INVALID_SCHEMA", "error": "missing field: from"})
    response = client.request({"op": "relationship"})
    assert response["status"] == "INVALID_SCHEMA"
    assert response["error"] == "missing field: from"


def test_evaluator_still_raises_worker_transport_errors() -> None:
    client = EVAL.WorkerClient.__new__(EVAL.WorkerClient)
    client.process = _FakeProcess({"workerError": "Ollama rejected request"})
    try:
        client.request({"op": "embed_batch"})
    except RuntimeError as error:
        assert str(error) == "Ollama rejected request"
    else:
        raise AssertionError("expected worker error to remain fatal")


def test_normalization_fidelity_warnings_flag_obvious_information_loss() -> None:
    assert "JURISDICTION_DROPPED_OR_CHANGED" in EVAL.normalization_risks(
        "State regulation reduces illegal betting.", "Regulation reduces illegal betting."
    )
    assert "NEGATION_MAY_BE_DROPPED" in EVAL.normalization_risks(
        "Legalization does not increase addiction.", "Legalization increases addiction."
    )
    assert "NEGATION_MAY_BE_DROPPED" not in EVAL.normalization_risks(
        "Federal agencies cannot enforce betting rules.", "Federal agencies are unable to enforce betting rules."
    )
    assert "QUALIFIER_OR_CONDITION_REVIEW" in EVAL.normalization_risks(
        "Operators can block minors when identity is verified before accepting wagers.",
        "Operators may block minors if identity is verified and wagers are accepted.",
    )
    assert "QUALIFIER_OR_CONDITION_REVIEW" not in EVAL.normalization_risks(
        "Illegal market share fell after regulation.", "Following regulation, illegal market share fell."
    )
    assert "DEPENDENCY_DIRECTION_REVIEW" in EVAL.normalization_risks(
        "Consumer protection depends on age verification.",
        "Age verification is dependent on consumer protection.",
    )
    assert "COMPOUND_CLAUSE_REVIEW" in EVAL.normalization_risks(
        "National rules create safeguards while limiting state experimentation.",
        "National rules limit state experimentation.",
    )
