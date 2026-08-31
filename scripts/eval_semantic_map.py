#!/usr/bin/env python3
"""Terminal-first evaluation, diagnostics, and failure analysis for Semantic Map."""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
RULE = "=" * 60
SUBRULE = "-" * 60
DIRECTIONAL = {"SUPPORTS", "ATTACKS"}


def cosine(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0


def direction_from_ids(left_id: str, right_id: str, source: Any, target: Any) -> str:
    """Render explicit graph endpoints as a human-readable local direction."""
    if source is None and target is None:
        return "undirected"
    if source == left_id and target == right_id:
        return "left_to_right"
    if source == right_id and target == left_id:
        return "right_to_left"
    return "invalid"


def expected_endpoints(relation: dict[str, Any]) -> tuple[Any, Any]:
    if relation["expected"] not in DIRECTIONAL:
        return None, None
    direction = relation.get("direction")
    if direction == "left_to_right":
        return relation["left"], relation["right"]
    if direction == "right_to_left":
        return relation["right"], relation["left"]
    raise ValueError(f"missing or invalid expected direction for {relation}")


class WorkerClient:
    def __init__(
        self,
        backend: str,
        embedding_model: str,
        relation_model: str,
        normalization_model: str,
        no_cache: bool,
    ):
        command = [
            sys.executable, str(ROOT / "scripts/semantic_ai_worker.py"),
            "--backend", backend,
            "--embedding-model", embedding_model,
            "--relation-model", relation_model,
            "--normalization-model", normalization_model,
        ]
        if no_cache:
            command.append("--no-cache")
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)

    def request(self, payload: dict[str, Any]) -> dict[str, Any]:
        assert self.process.stdin and self.process.stdout
        self.process.stdin.write(json.dumps(payload) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            raise RuntimeError("semantic AI worker exited without a response")
        response = json.loads(line)
        if response.get("workerError"):
            raise RuntimeError(response["workerError"])
        return response

    def close(self) -> None:
        if self.process.stdin:
            self.process.stdin.close()
        self.process.terminate()
        self.process.wait(timeout=5)


def rank_arguments(arguments: list[dict[str, Any]], embeddings: dict[str, list[float]]) -> dict[str, list[dict[str, Any]]]:
    rankings: dict[str, list[dict[str, Any]]] = {}
    for argument in arguments:
        argument_id = argument["id"]
        candidates = [
            {"id": candidate_id, "similarity": cosine(embeddings[argument_id], vector)}
            for candidate_id, vector in embeddings.items()
            if candidate_id != argument_id
        ]
        rankings[argument_id] = sorted(candidates, key=lambda item: item["similarity"], reverse=True)
    return rankings


def elapsed_ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000


def normalization_risks(original: str, normalized: str) -> list[str]:
    """Flag obvious fidelity risks for human review; never rewrite model output."""
    def tokens(text: str) -> set[str]:
        values = {""}
        for raw in text.lower().split():
            token = "".join(character for character in raw if character.isalpha())
            if token.endswith("ing") and len(token) > 5:
                token = token[:-3]
            elif token.endswith("s") and len(token) > 4:
                token = token[:-1]
            if token:
                values.add(token)
        values.discard("")
        return values

    original_lower = original.lower()
    normalized_lower = normalized.lower()
    original_tokens = tokens(original)
    normalized_tokens = tokens(normalized)
    risks: list[str] = []
    jurisdictions = {"state", "federal", "local", "national"}
    original_jurisdictions = jurisdictions & original_tokens
    normalized_jurisdictions = jurisdictions & normalized_tokens
    if original_jurisdictions - normalized_jurisdictions:
        risks.append("JURISDICTION_DROPPED_OR_CHANGED")
    # This is a polarity-risk warning, not a semantic rewriter. Treat common
    # equivalent negative forms (for example, "cannot" and "unable") alike.
    negations = {"not", "no", "never", "cannot", "doesnt", "unable", "lack", "without", "fail"}
    if negations & original_tokens and not negations & normalized_tokens:
        risks.append("NEGATION_MAY_BE_DROPPED")
    if " depends on " in f" {original_lower} " and " depends on " not in f" {normalized_lower} ":
        risks.append("DEPENDENCY_DIRECTION_REVIEW")
    condition_equivalents = {
        "only": {"only"},
        "unless": {"unless"},
        "before": {"before"},
        "after": {"after", "follow"},
        "when": {"when", "if"},
        "if": {"if", "when"},
        "can": {"can", "may", "able"},
        "may": {"may", "can"},
        "likely": {"likely", "probably"},
    }
    if any(
        marker in original_tokens and not alternatives & normalized_tokens
        for marker, alternatives in condition_equivalents.items()
    ):
        risks.append("QUALIFIER_OR_CONDITION_REVIEW")
    # A connective may legitimately be rewritten (for example, "while" to
    # "and"). Flag a compound claim only when one side loses most of its
    # substantive tokens, not merely because the connective changed.
    for connector in (" but ", " while "):
        if connector not in f" {original_lower} ":
            continue
        left_clause, right_clause = f" {original_lower} ".split(connector, 1)
        for clause in (left_clause, right_clause):
            substantive = {
                token for token in tokens(clause)
                if len(token) >= 4 and token not in {"that", "with", "from", "than", "into"}
            }
            if substantive and len(substantive & normalized_tokens) / len(substantive) <= 0.5:
                risks.append("COMPOUND_CLAUSE_REVIEW")
                break
        break
    return risks


def evaluate(
    dataset: dict[str, Any],
    backend: str,
    embedding_model: str,
    relation_model: str,
    normalization_model: str,
    representation: str,
    no_cache: bool,
    document_loading_ms: float,
) -> dict[str, Any]:
    total_started = time.perf_counter()
    arguments = dataset["arguments"]
    by_id = {argument["id"]: argument for argument in arguments}
    worker = WorkerClient(backend, embedding_model, relation_model, normalization_model, no_cache)
    try:
        views: dict[str, dict[str, Any]] = {
            argument["id"]: {
                "id": argument["id"],
                "original": argument["text"],
                "normalized": argument["text"],
                "normalizationStatus": "NOT_REQUESTED",
                "normalizationError": "",
                "normalizationRawResponse": None,
                "normalizationModel": "not-used",
                "normalizationRisks": [],
                "normalizationReview": argument.get("normalizationReview", {"label": "UNREVIEWED"}),
            }
            for argument in arguments
        }

        normalization_started = time.perf_counter()
        if representation == "normalized":
            for argument in arguments:
                response = worker.request({"op": "normalize", "id": argument["id"], "text": argument["text"]})
                view = views[argument["id"]]
                view["normalizationStatus"] = response.get("status", "INVALID_SCHEMA")
                view["normalizationError"] = response.get("error", "")
                view["normalizationRawResponse"] = response.get("rawResponse")
                view["normalizationModel"] = response.get("model", normalization_model)
                if response.get("status") == "OK":
                    view["normalized"] = response["semanticSummary"]
                view["normalizationRisks"] = normalization_risks(
                    view["original"], view["normalized"]
                )
        normalization_ms = elapsed_ms(normalization_started)

        embedding_started = time.perf_counter()
        embedding_texts = [
            views[argument["id"]]["normalized"] if representation == "normalized" else argument["text"]
            for argument in arguments
        ]
        embedding_response = worker.request({"op": "embed_batch", "texts": embedding_texts, "dimensions": 256})
        embeddings = dict(zip((argument["id"] for argument in arguments), embedding_response["embeddings"]))
        embedding_ms = elapsed_ms(embedding_started)

        retrieval_started = time.perf_counter()
        rankings = rank_arguments(arguments, embeddings)
        retrieval_details = []
        for argument in arguments:
            expected = set(argument.get("retrievalTargets", []))
            if not expected:
                continue
            rank_by_id = {candidate["id"]: index + 1 for index, candidate in enumerate(rankings[argument["id"]])}
            retrieval_details.append({
                "query": argument["id"],
                "expected": sorted(expected),
                "expectedRanks": {target: rank_by_id.get(target) for target in expected},
                "candidates": rankings[argument["id"]],
            })
        retrieval_metrics = {}
        for k in [1, 3, 5, 10]:
            hits = sum(
                any(rank is not None and rank <= k for rank in detail["expectedRanks"].values())
                for detail in retrieval_details
            )
            retrieval_metrics[f"recall_at_{k}"] = hits / len(retrieval_details) if retrieval_details else 0.0
        retrieval_ms = elapsed_ms(retrieval_started)

        relationship_started = time.perf_counter()
        predictions = []
        for relation in dataset["relationships"]:
            left, right = relation["left"], relation["right"]
            response = worker.request({
                "op": "relationship",
                "left": {
                    "id": left,
                    "original_text": by_id[left]["text"],
                    "normalized_text": views[left]["normalized"],
                },
                "right": {
                    "id": right,
                    "original_text": by_id[right]["text"],
                    "normalized_text": views[right]["normalized"],
                },
            })
            expected_source, expected_target = expected_endpoints(relation)
            status = response.get("status", "INVALID_SCHEMA")
            source = response.get("source_argument")
            target = response.get("target_argument")
            valid = status == "OK"
            class_correct = response.get("relationship") == relation["expected"] if valid else None
            direction_correct = (
                source == expected_source and target == expected_target
            ) if valid and relation["expected"] in DIRECTIONAL and class_correct else None
            full_edge_correct = (
                class_correct and (
                    relation["expected"] not in DIRECTIONAL or direction_correct
                )
            ) if valid else None
            predictions.append({
                **relation,
                "expectedFrom": expected_source,
                "expectedTo": expected_target,
                "status": status,
                "error": response.get("error", ""),
                "predicted": response.get("relationship"),
                "sourceArgument": source,
                "targetArgument": target,
                "predictedDirection": direction_from_ids(left, right, source, target),
                "confidence": response.get("confidence", 0.0),
                "reason": response.get("reason", ""),
                "model": response.get("model", relation_model),
                "rawResponse": response.get("rawResponse"),
                "classCorrect": class_correct,
                "directionCorrect": direction_correct,
                "fullEdgeCorrect": full_edge_correct,
            })

        known_ids = set(dataset.get("knownArguments", []))
        novelty_results = []
        for novel_id in dataset.get("novelArguments", []):
            inspected = []
            represented = False
            had_pipeline_error = False
            for candidate in [item for item in rankings[novel_id] if item["id"] in known_ids][:5]:
                candidate_id = candidate["id"]
                response = worker.request({
                    "op": "relationship",
                    "left": {
                        "id": novel_id,
                        "original_text": by_id[novel_id]["text"],
                        "normalized_text": views[novel_id]["normalized"],
                    },
                    "right": {
                        "id": candidate_id,
                        "original_text": by_id[candidate_id]["text"],
                        "normalized_text": views[candidate_id]["normalized"],
                    },
                })
                status = response.get("status", "INVALID_SCHEMA")
                had_pipeline_error |= status != "OK"
                relationship = response.get("relationship")
                represented |= relationship in {"SAME_ARGUMENT", "SUPPORTS", "ATTACKS"} if status == "OK" else False
                inspected.append({
                    **candidate, "status": status, "relationship": relationship,
                    "sourceArgument": response.get("source_argument"),
                    "targetArgument": response.get("target_argument"),
                    "error": response.get("error", ""), "rawResponse": response.get("rawResponse"),
                    "reason": response.get("reason", ""),
                })
            predicted_new = None if had_pipeline_error else not represented
            novelty_results.append({
                "id": novel_id, "predictedNew": predicted_new,
                "expectedNew": True, "candidates": inspected,
            })
        relationship_ms = elapsed_ms(relationship_started)

        stats = worker.request({"op": "stats"})
        valid_predictions = [prediction for prediction in predictions if prediction["status"] == "OK"]
        pipeline_statuses = Counter(
            prediction["status"] for prediction in predictions if prediction["status"] != "OK"
        )
        parse_successes = [
            prediction for prediction in predictions
            if prediction["status"] not in {"PARSE_ERROR", "EMPTY_RESPONSE", "MODEL_ERROR"}
        ]
        directional_predictions = [
            prediction for prediction in valid_predictions
            if prediction["expected"] in DIRECTIONAL and prediction["classCorrect"]
        ]
        per_class = {}
        for label in sorted({prediction["expected"] for prediction in predictions}):
            actual = [p for p in valid_predictions if p["expected"] == label]
            predicted = [p for p in valid_predictions if p["predicted"] == label]
            true_positive = sum(p["expected"] == label and p["classCorrect"] for p in valid_predictions)
            per_class[label] = {
                "precision": true_positive / len(predicted) if predicted else 0.0,
                "recall": true_positive / len(actual) if actual else 0.0,
            }
        novelty_valid = [item for item in novelty_results if item["predictedNew"] is not None]
        normalization_risk_counts = Counter(
            risk for view in views.values() for risk in view["normalizationRisks"]
        )
        normalization_review_counts = Counter(
            view["normalizationReview"].get("label", "UNREVIEWED") for view in views.values()
        )
        report = {
            "dataset": dataset["dataset"],
            "backend": backend,
            "embeddingModel": embedding_model,
            "normalizationModel": normalization_model,
            "relationshipModel": relation_model,
            "representation": representation,
            "arguments": len(arguments),
            "argumentViews": list(views.values()),
            "normalization": {
                "reviewFlags": sum(bool(view["normalizationRisks"]) for view in views.values()),
                "riskCounts": dict(normalization_risk_counts),
                "manualReviewLabels": dict(normalization_review_counts),
            },
            "retrieval": {"metrics": retrieval_metrics, "details": retrieval_details},
            "relationship": {
                "classAccuracy": sum(bool(p["classCorrect"]) for p in valid_predictions) / len(valid_predictions) if valid_predictions else 0.0,
                "directionalAccuracy": sum(bool(p["directionCorrect"]) for p in directional_predictions) / len(directional_predictions) if directional_predictions else 0.0,
                "fullEdgeAccuracy": sum(bool(p["fullEdgeCorrect"]) for p in valid_predictions) / len(valid_predictions) if valid_predictions else 0.0,
                "schemaValidRate": len(valid_predictions) / len(predictions) if predictions else 0.0,
                "parseSuccessRate": len(parse_successes) / len(predictions) if predictions else 0.0,
                "validPredictions": len(valid_predictions),
                "pipelineFailures": dict(pipeline_statuses),
                "perClass": per_class,
                "predictions": predictions,
            },
            "novelty": {
                "accuracy": sum(item["predictedNew"] == item["expectedNew"] for item in novelty_valid) / len(novelty_valid) if novelty_valid else 0.0,
                "pipelineFailures": len(novelty_results) - len(novelty_valid),
                "results": novelty_results,
            },
            "performance": {
                "documentLoadingMs": document_loading_ms,
                "normalizationMs": normalization_ms,
                "embeddingMs": embedding_ms,
                "retrievalMs": retrieval_ms,
                "relationshipMs": relationship_ms,
                "evaluationMs": 0.0,
                "totalMs": 0.0,
                "cache": stats.get("cache", {}),
                "cacheDisabled": stats.get("cacheDisabled", no_cache),
            },
        }
        report["performance"]["evaluationMs"] = elapsed_ms(total_started) - normalization_ms - embedding_ms - retrieval_ms - relationship_ms
        report["performance"]["totalMs"] = elapsed_ms(total_started)
        return report
    finally:
        worker.close()


def argument_view(report: dict[str, Any], argument_id: str) -> dict[str, Any]:
    return next(view for view in report["argumentViews"] if view["id"] == argument_id)


def print_summary(report: dict[str, Any]) -> None:
    print(RULE + "\nSEMANTIC MAP EVALUATION\n" + RULE + "\n")
    print(f"Dataset:              {report['dataset']}")
    print(f"Arguments:            {report['arguments']}")
    print(f"Embedding backend:    {report['backend']}")
    print(f"Embedding model:      {report['embeddingModel']}")
    print(f"Representation:       {report['representation']}")
    print(f"Normalization model:  {report['normalizationModel']}")
    print(f"Relationship model:   {report['relationshipModel']}\n")
    print(SUBRULE + "\nRETRIEVAL\n" + SUBRULE + "\n")
    for key, value in report["retrieval"]["metrics"].items():
        print(f"Recall@{key.rsplit('_', 1)[-1]:<2}    {value * 100:5.1f}%")
    normalization = report["normalization"]
    print("\n" + SUBRULE + "\nNORMALIZATION FIDELITY\n" + SUBRULE + "\n")
    print(f"Potential fidelity review flags: {normalization['reviewFlags']}")
    for label in [
        "JURISDICTION_DROPPED_OR_CHANGED",
        "NEGATION_MAY_BE_DROPPED",
       "DEPENDENCY_DIRECTION_REVIEW",
        "QUALIFIER_OR_CONDITION_REVIEW",
       "COMPOUND_CLAUSE_REVIEW",
    ]:
        print(f"{label + ':':<36} {normalization['riskCounts'].get(label, 0)}")
    reviewed = sum(count for label, count in normalization["manualReviewLabels"].items() if label != "UNREVIEWED")
    print(f"Human-labeled normalizations:            {reviewed}")
    relationship = report["relationship"]
    print("\n" + SUBRULE + "\nRELATIONSHIP CLASSIFICATION\n" + SUBRULE + "\n")
    print(f"Class accuracy:       {relationship['classAccuracy'] * 100:.1f}%")
    print(f"Directional accuracy: {relationship['directionalAccuracy'] * 100:.1f}%")
    print(f"Full edge accuracy:   {relationship['fullEdgeAccuracy'] * 100:.1f}%")
    print(f"Schema-valid rate:    {relationship['schemaValidRate'] * 100:.1f}%")
    print(f"Parse-success rate:   {relationship['parseSuccessRate'] * 100:.1f}%")
    print(f"Valid predictions:    {relationship['validPredictions']}")
    if relationship["pipelineFailures"]:
        failures = ", ".join(f"{key}: {value}" for key, value in relationship["pipelineFailures"].items())
        print(f"Pipeline failures: {failures}")
    print(f"\n{'Class':<18} {'Precision':>10} {'Recall':>10}\n{SUBRULE}")
    for label, scores in relationship["perClass"].items():
        print(f"{label:<18} {scores['precision'] * 100:9.1f}% {scores['recall'] * 100:9.1f}%")
    print("\n" + SUBRULE + "\nNOVELTY\n" + SUBRULE + "\n")
    novelty = report["novelty"]
    print(f"Accuracy: {novelty['accuracy'] * 100:.1f}%")
    if novelty["pipelineFailures"]:
        print(f"Pipeline failures: {novelty['pipelineFailures']}")
    print("\n" + RULE)
    print_performance(report)


def print_performance(report: dict[str, Any]) -> None:
    performance = report["performance"]
    print("\n" + RULE + "\nPERFORMANCE\n" + RULE + "\n")
    for label, key in [
        ("Document loading", "documentLoadingMs"),
        ("Normalization", "normalizationMs"),
        ("Embedding", "embeddingMs"),
        ("Retrieval", "retrievalMs"),
        ("Relationship inference", "relationshipMs"),
        ("Evaluation", "evaluationMs"),
        ("Total", "totalMs"),
    ]:
        print(f"{label + ':':<26} {performance[key]:8.2f} ms")
    print("\nAI calls / cache\n" + SUBRULE)
    cache = performance["cache"]
    for operation, label in [
        ("normalize", "Normalization"),
        ("embed_batch", "Embeddings"),
        ("relationship", "Relationships"),
    ]:
        stats = cache.get(operation, {})
        print(
            f"{label + ':':<16} {stats.get('requests', 0):>3} requests | "
            f"{stats.get('items_hit', 0):>3} cached | {stats.get('items_generated', 0):>3} generated"
        )
    if performance["cacheDisabled"]:
        print("\nCache: disabled (--no-cache)")
    print(RULE)


def print_normalizations(report: dict[str, Any], only_id: str | None = None) -> None:
    print("\n" + RULE + "\nNORMALIZATION INSPECTION\n" + RULE)
    for view in report["argumentViews"]:
        if only_id and view["id"] != only_id:
            continue
        print(f"\n[{view['id']}]  review: {view['normalizationReview'].get('label', 'UNREVIEWED')}")
        print("\nORIGINAL\n" + SUBRULE + f"\n{view['original']}")
        print("\nNORMALIZED\n" + SUBRULE + f"\n{view['normalized']}")
        print(f"\nStatus: {view['normalizationStatus']}  Model: {view['normalizationModel']}")
        if view["normalizationError"]:
            print(f"Error: {view['normalizationError']}")
        if view["normalizationRisks"]:
            print("Fidelity review: " + ", ".join(view["normalizationRisks"]))
        if view["normalizationRawResponse"] is not None:
            print("\nRAW MODEL RESPONSE\n" + SUBRULE + f"\n{view['normalizationRawResponse']}")


def print_retrieval_detail(report: dict[str, Any], detail: dict[str, Any], limit: int) -> None:
    query = argument_view(report, detail["query"])
    print(f"\nQuery [{query['id']}]\n" + SUBRULE + f"\n{query['original']}")
    if report["representation"] == "normalized":
        print("\nNormalized\n" + SUBRULE + f"\n{query['normalized']}")
    print("\nExpected matches: " + ", ".join(detail["expected"]))
    expected_ranks = ", ".join(f"{target}: {rank or 'not in corpus'}" for target, rank in detail["expectedRanks"].items())
    print("Expected rank: " + expected_ranks)
    print("\nTOP RETRIEVED CANDIDATES\n" + SUBRULE)
    expected = set(detail["expected"])
    for index, candidate in enumerate(detail["candidates"][:limit], start=1):
        candidate_view = argument_view(report, candidate["id"])
        marker = "  <-- EXPECTED" if candidate["id"] in expected else ""
        print(f"\n#{index}  {candidate['id']}  similarity: {candidate['similarity']:.3f}{marker}")
        print(candidate_view["original"])
        if report["representation"] == "normalized":
            print(f"Normalized: {candidate_view['normalized']}")


def print_retrieval_issues(report: dict[str, Any], all_details: bool, limit: int, only_id: str | None = None) -> None:
    details = report["retrieval"]["details"]
    if only_id:
        selected = [detail for detail in details if detail["query"] == only_id]
    elif all_details:
        selected = details
    else:
        selected = [
            detail for detail in details
            if min((rank or 999999) for rank in detail["expectedRanks"].values()) > 1
        ]
    if not selected:
        return
    heading = "RETRIEVAL DETAILS" if all_details else "RETRIEVAL FAILURES AND NEAR-MISSES"
    print("\n" + RULE + f"\n{heading}\n" + RULE)
    for detail in selected:
        print_retrieval_detail(report, detail, limit)


def print_relationship_prediction(report: dict[str, Any], prediction: dict[str, Any]) -> None:
    left = argument_view(report, prediction["left"])
    right = argument_view(report, prediction["right"])
    print(f"\nArgument A [{left['id']}]\n" + SUBRULE + f"\n{left['original']}")
    if report["representation"] == "normalized":
        print(f"\nNormalized:\n{left['normalized']}")
    print(f"\nArgument B [{right['id']}]\n" + SUBRULE + f"\n{right['original']}")
    if report["representation"] == "normalized":
        print(f"\nNormalized:\n{right['normalized']}")
    expected_direction = direction_from_ids(
        prediction["left"], prediction["right"], prediction["expectedFrom"], prediction["expectedTo"]
    )
    print(f"\nExpected:   {prediction['expected']} ({expected_direction})")
    if prediction["status"] == "OK":
        print(f"Predicted:  {prediction['predicted']} ({prediction['predictedDirection']})")
        print(f"Edge:       {prediction['sourceArgument']} -> {prediction['targetArgument']}")
        print(f"Confidence: {float(prediction['confidence']):.2f}")
        print(f"Reason:     {prediction['reason'] or '(none)'}")
    else:
        print(f"Prediction status: {prediction['status']}")
        print(f"Error:             {prediction['error'] or '(none)'}")
    print(f"Model:      {prediction['model']}")
    print("\nRAW MODEL RESPONSE\n" + SUBRULE)
    print(prediction["rawResponse"] if prediction["rawResponse"] is not None else "(none)")
    print("\nPARSE STATUS\n" + SUBRULE + f"\n{prediction['status']}")
    print(SUBRULE)


def print_relationships(report: dict[str, Any], failures_only: bool, only_id: str | None = None) -> None:
    predictions = report["relationship"]["predictions"]
    if only_id:
        selected = [p for p in predictions if only_id in {p["left"], p["right"]}]
    elif failures_only:
        selected = [p for p in predictions if p["fullEdgeCorrect"] is not True]
    else:
        selected = predictions
    if not selected:
        return
    heading = "FAILURE ANALYSIS" if failures_only else "RELATIONSHIP PREDICTIONS"
    print("\n" + RULE + f"\n{heading}\n" + RULE)
    for index, prediction in enumerate(selected, start=1):
        label = "FAILURE" if prediction["fullEdgeCorrect"] is not True else "PREDICTION"
        print(f"\n[{label} {index} / {len(selected)}]\n\nType:\n{SUBRULE}\nRELATIONSHIP CLASSIFICATION")
        print_relationship_prediction(report, prediction)


def print_inspect(report: dict[str, Any], argument_id: str, limit: int) -> None:
    try:
        view = argument_view(report, argument_id)
    except StopIteration:
        raise ValueError(f"unknown argument ID: {argument_id}")
    print(RULE + f"\nINSPECT {argument_id}\n" + RULE)
    print("\nORIGINAL\n" + SUBRULE + f"\n{view['original']}")
    print("\nNORMALIZED\n" + SUBRULE + f"\n{view['normalized']}")
    print(f"\nNormalization status: {view['normalizationStatus']}")
    if view["normalizationError"]:
        print(f"Normalization error: {view['normalizationError']}")
    if view["normalizationRisks"]:
        print("Normalization fidelity review: " + ", ".join(view["normalizationRisks"]))
    print(f"Embedding model: {report['embeddingModel']}")
    print_retrieval_issues(report, all_details=True, limit=limit, only_id=argument_id)
    print_relationships(report, failures_only=False, only_id=argument_id)


def print_comparison(raw: dict[str, Any], normalized: dict[str, Any]) -> None:
    print(RULE + "\nREPRESENTATION COMPARISON\n" + RULE)
    print(f"Dataset: {raw['dataset']}\n")
    print(f"{'':<20} {'RAW':>10} {'NORMALIZED':>14} {'CHANGE':>10}")
    print(SUBRULE)
    for key in ["recall_at_1", "recall_at_3", "recall_at_5", "recall_at_10"]:
        left = raw["retrieval"]["metrics"][key]
        right = normalized["retrieval"]["metrics"][key]
        print(f"Recall@{key.rsplit('_', 1)[-1]:<12} {left * 100:9.1f}% {right * 100:13.1f}% {(right - left) * 100:+9.1f}")
    for label, getter in [
        ("Full edge", lambda report: report["relationship"]["fullEdgeAccuracy"]),
        ("Novelty", lambda report: report["novelty"]["accuracy"]),
    ]:
        left, right = getter(raw), getter(normalized)
        print(f"{label:<20} {left * 100:9.1f}% {right * 100:13.1f}% {(right - left) * 100:+9.1f}")
    print(RULE)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, default=ROOT / "benchmarks/semantic-map/adversarial-v1.json")
    parser.add_argument("--backend", choices=["feature-hash", "ollama"], default="feature-hash")
    parser.add_argument("--embedding-model", "--model", dest="embedding_model", default=os.environ.get("SEMANTIC_EMBEDDING_MODEL", "nomic-embed-text"))
    parser.add_argument("--relation-model", default=os.environ.get("SEMANTIC_RELATION_MODEL", "gemma3:4b"))
    parser.add_argument("--normalization-model")
    parser.add_argument("--representation", choices=["raw", "normalized"], default="raw")
    parser.add_argument("--errors", action="store_true", help="show relationship failures and retrieval near-misses")
    parser.add_argument("--retrieval-details", action="store_true", help="show ranked candidates for every retrieval query")
    parser.add_argument("--show-normalizations", action="store_true")
    parser.add_argument("--relationships-only", action="store_true")
    parser.add_argument("--failures-only", action="store_true")
    parser.add_argument("--inspect", metavar="ARGUMENT_ID")
    parser.add_argument("--top-k-display", type=int, default=5)
    parser.add_argument("--verbose", action="store_true", help="show normalizations, all rankings, and all relation predictions")
    parser.add_argument("--compare-representations", action="store_true")
    parser.add_argument("--no-cache", action="store_true")
    parser.add_argument("--json", action="store_true", help="print the machine-readable report only")
    parser.add_argument("--json-out", type=Path, help="optional compatibility output path")
    args = parser.parse_args()
    if args.top_k_display < 1:
        parser.error("--top-k-display must be positive")
    normalization_model = args.normalization_model or os.environ.get("SEMANTIC_NORMALIZATION_MODEL", args.relation_model)
    loading_started = time.perf_counter()
    try:
        dataset = json.loads(args.dataset.read_text())
        document_loading_ms = elapsed_ms(loading_started)
        if args.compare_representations:
            raw = evaluate(dataset, args.backend, args.embedding_model, args.relation_model, normalization_model, "raw", args.no_cache, document_loading_ms)
            normalized = evaluate(dataset, args.backend, args.embedding_model, args.relation_model, normalization_model, "normalized", args.no_cache, document_loading_ms)
            combined = {"raw": raw, "normalized": normalized}
            if args.json:
                print(json.dumps(combined, indent=2))
            else:
                print_comparison(raw, normalized)
            if args.json_out:
                args.json_out.write_text(json.dumps(combined, indent=2) + "\n")
            return 0
        report = evaluate(dataset, args.backend, args.embedding_model, args.relation_model, normalization_model, args.representation, args.no_cache, document_loading_ms)
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as error:
        print(f"semantic map evaluation failed: {error}", file=sys.stderr)
        return 1
    if args.json_out:
        args.json_out.write_text(json.dumps(report, indent=2) + "\n")
    if args.json:
        print(json.dumps(report, indent=2))
        return 0
    if args.inspect:
        print_inspect(report, args.inspect, args.top_k_display)
        return 0
    if not args.relationships_only:
        print_summary(report)
    if args.verbose or args.show_normalizations:
        print_normalizations(report)
    if args.verbose:
        if not args.relationships_only:
            print_retrieval_issues(report, all_details=True, limit=args.top_k_display)
        print_relationships(report, failures_only=False)
    elif args.relationships_only:
        print_relationships(report, failures_only=args.failures_only or args.errors)
    else:
        if args.errors or args.failures_only:
            print_retrieval_issues(report, all_details=False, limit=args.top_k_display)
            print_relationships(report, failures_only=True)
        if args.retrieval_details:
            print_retrieval_issues(report, all_details=True, limit=args.top_k_display)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
