#!/usr/bin/env python3
"""Persistent JSONL AI boundary for Semantic Map evaluation.

Embedding, normalization, and relationship inference intentionally use separate
models. Chat failures are returned as structured statuses so evaluation never
mistakes infrastructure failures for semantic predictions.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

NORMALIZATION_PROMPT_VERSION = "normalization-v3.1-fidelity"
RELATIONSHIP_PROMPT_VERSION = "relationship-v3.1-source-target"
DIRECTIONAL_RELATIONSHIPS = {"SUPPORTS", "ATTACKS"}
UNDIRECTED_RELATIONSHIPS = {"SAME_ARGUMENT", "RELATED", "UNRELATED"}
RELATIONSHIPS = DIRECTIONAL_RELATIONSHIPS | UNDIRECTED_RELATIONSHIPS


class WorkerError(RuntimeError):
    """A transport or embedding error that prevents the requested operation."""


def feature_hash_embedding(text: str, dimensions: int = 256) -> list[float]:
    values = [0.0] * dimensions
    for word in text.lower().split():
        token = "".join(character for character in word if character.isalnum())
        if len(token) < 3:
            continue
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        values[int.from_bytes(digest[:4], "big") % dimensions] += 1.0
    norm = math.sqrt(sum(value * value for value in values))
    return [value / norm for value in values] if norm else values


def _safe_confidence(value: Any) -> float:
    try:
        return min(1.0, max(0.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


class Worker:
    def __init__(
        self,
        backend: str,
        embedding_model: str,
        relation_model: str,
        normalization_model: str,
        base_url: str,
        cache_path: Path,
        no_cache: bool,
    ):
        self.backend = backend
        self.embedding_model = embedding_model
        self.relation_model = relation_model
        self.normalization_model = normalization_model
        self.base_url = base_url.rstrip("/")
        self.cache_path = cache_path
        self.no_cache = no_cache
        self.cache = self._load_cache()
        self.cache_stats: dict[str, dict[str, int]] = {}

    def _load_cache(self) -> dict[str, Any]:
        if self.no_cache:
            return {}
        try:
            value = json.loads(self.cache_path.read_text()) if self.cache_path.exists() else {}
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save_cache(self) -> None:
        if self.no_cache:
            return
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.cache_path.with_suffix(self.cache_path.suffix + ".tmp")
        temporary.write_text(json.dumps(self.cache))
        temporary.replace(self.cache_path)

    def _record_cache(self, operation: str, hit: bool, item_count: int) -> None:
        stats = self.cache_stats.setdefault(
            operation,
            {"requests": 0, "hits": 0, "misses": 0, "items_hit": 0, "items_generated": 0},
        )
        stats["requests"] += 1
        if hit:
            stats["hits"] += 1
            stats["items_hit"] += item_count
        else:
            stats["misses"] += 1
            stats["items_generated"] += item_count

    def cached(
        self,
        operation: str,
        payload: dict[str, Any],
        item_count: int,
        producer: Callable[[], dict[str, Any] | list[list[float]]],
    ):
        key_payload: dict[str, Any] = {
            "backend": self.backend,
            "operation": operation,
            "payload": payload,
        }
        if operation == "embed_batch":
            key_payload["embedding_model"] = self.embedding_model
        elif operation == "normalize":
            key_payload.update({
                "normalization_model": self.normalization_model,
                "prompt_version": NORMALIZATION_PROMPT_VERSION,
                "generation": {"temperature": 0},
            })
        elif operation == "relationship":
            key_payload.update({
                "relationship_model": self.relation_model,
                "prompt_version": RELATIONSHIP_PROMPT_VERSION,
                "generation": {"temperature": 0},
            })
        key = hashlib.sha256(
            json.dumps(key_payload, sort_keys=True).encode("utf-8")
        ).hexdigest()
        cached = self.cache.get(key)
        if cached is not None:
            self._record_cache(operation, True, item_count)
            return cached
        self._record_cache(operation, False, item_count)
        value = producer()
        # Only successful model output is stable enough to cache.
        if not isinstance(value, dict) or value.get("status", "OK") == "OK":
            self.cache[key] = value
            self._save_cache()
        return value

    def embed_many(self, texts: list[str], dimensions: int) -> list[list[float]]:
        payload = {"texts": texts, "dimensions": dimensions}

        def produce() -> list[list[float]]:
            if self.backend == "feature-hash":
                return [feature_hash_embedding(text, dimensions) for text in texts]
            response, _ = self.ollama_json(
                "/api/embed", {"model": self.embedding_model, "input": texts}
            )
            embeddings = response.get("embeddings")
            if not isinstance(embeddings, list) or len(embeddings) != len(texts):
                raise WorkerError("Ollama returned the wrong number of embeddings")
            vectors = []
            for embedding in embeddings:
                if (
                    not isinstance(embedding, list)
                    or not embedding
                    or not all(isinstance(value, (int, float)) for value in embedding)
                ):
                    raise WorkerError("Ollama returned an invalid embedding")
                vectors.append([float(value) for value in embedding])
            return vectors

        return self.cached("embed_batch", payload, len(texts), produce)

    def normalize(self, text: str) -> dict[str, Any]:
        if self.backend == "feature-hash":
            return {
                "status": "OK",
                "semanticSummary": " ".join(text.split())[:180],
                "confidence": 0.0,
                "model": "preview-baseline",
                "rawResponse": None,
            }
        payload = {"text": text}

        def produce() -> dict[str, Any]:
            chat = self.chat_json(
                self._normalization_instruction(), text, self.normalization_model
            )
            if chat["status"] != "OK":
                return {**chat, "model": self.normalization_model}
            data = chat["data"]
            summary = data.get("semanticSummary")
            if not isinstance(summary, str) or not summary.strip():
                return {
                    "status": "INVALID_SCHEMA",
                    "error": "missing field: semanticSummary",
                    "rawResponse": chat["rawResponse"],
                    "model": self.normalization_model,
                }
            return {
                "status": "OK",
                "semanticSummary": summary.strip(),
                "confidence": _safe_confidence(data.get("confidence")),
                "model": self.normalization_model,
                "rawResponse": chat["rawResponse"],
            }

        return self.cached("normalize", payload, 1, produce)

    def relationship(self, left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
        if self.backend == "feature-hash":
            return {
                "status": "OK",
                "relationship": "RELATED",
                "source_argument": None,
                "target_argument": None,
                "confidence": 0.0,
                "reason": "Feature-hash baseline does not perform relation inference.",
                "model": "heuristic-baseline",
                "rawResponse": None,
            }
        payload = {"left": left, "right": right}

        def produce() -> dict[str, Any]:
            chat = self.chat_json(
                self._relationship_instruction(left["id"], right["id"]),
                json.dumps({"left": left, "right": right}),
                self.relation_model,
            )
            if chat["status"] != "OK":
                return {**chat, "model": self.relation_model}
            data = chat["data"]
            relationship = data.get("relationship")
            if not isinstance(relationship, str):
                relationship = ""
            else:
                relationship = relationship.strip()
            if relationship not in RELATIONSHIPS:
                return self.invalid_schema(
                    f"invalid relationship: {relationship or 'missing'}",
                    chat["rawResponse"],
                )
            source = data.get("source_argument")
            target = data.get("target_argument")
            valid_ids = {left["id"], right["id"]}
            if relationship in DIRECTIONAL_RELATIONSHIPS:
                if source not in valid_ids:
                    return self.invalid_schema("invalid or missing field: source_argument", chat["rawResponse"])
                if target not in valid_ids:
                    return self.invalid_schema("invalid or missing field: target_argument", chat["rawResponse"])
                if source == target:
                    return self.invalid_schema(
                        "source_argument and target_argument must identify different arguments",
                        chat["rawResponse"],
                    )
            else:
                # Endpoints on an undirected label do not carry semantic meaning.
                # Canonicalize rather than converting a correct class into a fake
                # schema failure.
                source = None
                target = None
            reason = data.get("reason", "")
            return {
                "status": "OK",
                "relationship": relationship,
                "source_argument": source,
                "target_argument": target,
                "confidence": _safe_confidence(data.get("confidence")),
                "reason": reason.strip() if isinstance(reason, str) else "",
                "model": self.relation_model,
                "rawResponse": chat["rawResponse"],
            }

        return self.cached("relationship", payload, 1, produce)

    def invalid_schema(self, error: str, raw_response: str | None) -> dict[str, Any]:
        return {
            "status": "INVALID_SCHEMA",
            "error": error,
            "rawResponse": raw_response,
            "model": self.relation_model,
        }

    def ollama_json(self, path: str, payload: dict[str, Any]) -> tuple[dict[str, Any], str]:
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="replace")
            raise WorkerError(
                f"Ollama rejected request: HTTP {error.code}: {body}"
            ) from error
        except urllib.error.URLError as error:
            raise WorkerError(f"Could not reach Ollama at {self.base_url}: {error}") from error
        try:
            result = json.loads(body)
        except json.JSONDecodeError as error:
            raise WorkerError(f"Ollama returned invalid JSON: {body}") from error
        if not isinstance(result, dict):
            raise WorkerError(f"Ollama returned a non-object response: {body}")
        if result.get("error"):
            raise WorkerError(f"Ollama model error: {result['error']}")
        return result, body

    def chat_json(self, instruction: str, content: str, model: str) -> dict[str, Any]:
        try:
            response, raw_response = self.ollama_json(
                "/api/chat",
                {
                    "model": model,
                    "stream": False,
                    "format": "json",
                    "options": {"temperature": 0},
                    "messages": [
                        {"role": "system", "content": instruction},
                        {"role": "user", "content": content},
                    ],
                },
            )
        except WorkerError as error:
            return {
                "status": "MODEL_ERROR",
                "error": str(error),
                "rawResponse": str(error),
            }
        message = response.get("message", {})
        content_text = message.get("content") if isinstance(message, dict) else None
        if not isinstance(content_text, str) or not content_text.strip():
            return {
                "status": "EMPTY_RESPONSE",
                "error": "Ollama chat response did not include message content",
                "rawResponse": raw_response,
            }
        try:
            parsed = json.loads(content_text)
        except json.JSONDecodeError as error:
            return {
                "status": "PARSE_ERROR",
                "error": f"model content was not valid JSON: {error.msg}",
                "rawResponse": content_text,
            }
        if not isinstance(parsed, dict):
            return {
                "status": "INVALID_SCHEMA",
                "error": "model content was not a JSON object",
                "rawResponse": content_text,
            }
        return {"status": "OK", "data": parsed, "rawResponse": content_text}

    @staticmethod
    def _normalization_instruction() -> str:
        return """Rewrite the input into a canonical proposition for semantic retrieval.

Your goal is not maximum brevity. Remove only unnecessary surface variation
while preserving the exact semantic proposition.

STRICT PRESERVATION RULES:
1. Preserve every actor and jurisdiction (for example: state, federal, local, national).
2. Preserve subject, object, negation, modality, certainty, quantities, and important entities.
3. Preserve causal, dependency, and comparison direction.
4. Preserve conditions, qualifiers, and every independently meaningful clause in a compound claim.
5. Do not add mechanisms, causes, evidence, examples, impacts, actors, or certainty.
6. Do not strengthen, weaken, or reverse a relationship.
7. If the source is already concise and canonical, return it unchanged or nearly unchanged.

Return exactly one JSON object:
{"semanticSummary":"...", "confidence":0.0}"""

    @staticmethod
    def _relationship_instruction(left_id: str, right_id: str) -> str:
        return f"""Classify the relationship between two debate arguments. ORIGINAL TEXT IS AUTHORITATIVE; normalized text is retrieval context only. The arguments have IDs {left_id} and {right_id}. Embeddings are candidate retrieval only.

SAME_ARGUMENT: both independently assert substantially the same central proposition. Evidence for a proposition is not automatically the same argument as the proposition.
SUPPORTS: accepting one provides evidence, a reason, mechanism, warrant, example, causal link, or subsidiary proposition that increases support for the other.
ATTACKS: accepting one provides a reason to reject, weaken, qualify, reverse, reduce confidence in, or reduce the argumentative force of the other. A policy benefit and a separate policy cost can both be true and are usually RELATED, not ATTACKS.
RELATED: meaningful shared argumentative issue, mechanism, actor, policy component, tradeoff, or dependency, without clear support, attack, or equivalence.
UNRELATED: no meaningful argumentative proximity.

Choose EXACTLY ONE relationship from SAME_ARGUMENT, SUPPORTS, ATTACKS, RELATED, or UNRELATED. Never combine labels. Never invent aliases or labels such as OPPOSITES.

For SUPPORTS and ATTACKS, source_argument is the argument doing the supporting or attacking and target_argument is the argument being supported or attacked. For SAME_ARGUMENT, RELATED, and UNRELATED, source_argument and target_argument are ignored and may be null.

Examples:
Argument A: Regulation reduces illegal betting.
Argument B: Illegal betting fell 20 percent after regulation.
Correct: {{"relationship":"SUPPORTS","source_argument":"B","target_argument":"A","reason":"B is evidence for A."}}

Argument A: Illegal betting fell 20 percent after regulation.
Argument B: Regulation reduces illegal betting.
Correct: {{"relationship":"SUPPORTS","source_argument":"A","target_argument":"B","reason":"A is evidence for B."}}

Argument A: Legalization reduces illegal betting.
Argument B: Studies find no reduction in illegal betting after legalization.
Correct: {{"relationship":"ATTACKS","source_argument":"B","target_argument":"A","reason":"B challenges A."}}

Argument A: Studies find no reduction in illegal betting after legalization.
Argument B: Legalization reduces illegal betting.
Correct: {{"relationship":"ATTACKS","source_argument":"A","target_argument":"B","reason":"A challenges B."}}

For directional labels, source_argument and target_argument must each be
exactly "{left_id}" or "{right_id}", and they must be different. For
undirected labels, use null for both fields.

Return exactly one JSON object in this shape (substitute one exact allowed
label and the applicable IDs; do not copy these example values blindly):
{{"relationship":"SUPPORTS","source_argument":"{left_id}","target_argument":"{right_id}","confidence":0.0,"reason":"one concise sentence"}}"""

    def stats(self) -> dict[str, Any]:
        return {
            "cache": self.cache_stats,
            "models": {
                "embedding": self.embedding_model,
                "normalization": self.normalization_model,
                "relationship": self.relation_model,
            },
            "cacheDisabled": self.no_cache,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--backend", choices=["feature-hash", "ollama"], default=os.environ.get("SEMANTIC_AI_BACKEND", "feature-hash"))
    parser.add_argument("--embedding-model", "--model", dest="embedding_model", default=os.environ.get("SEMANTIC_EMBEDDING_MODEL", "nomic-embed-text"))
    parser.add_argument("--relation-model", default=os.environ.get("SEMANTIC_RELATION_MODEL", "gemma3:4b"))
    parser.add_argument("--normalization-model")
    parser.add_argument("--base-url", default=os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434"))
    parser.add_argument("--cache", type=Path, default=Path(os.environ.get("SEMANTIC_AI_CACHE", "var/semantic-map-ai-cache.json")))
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args()
    normalization_model = args.normalization_model or os.environ.get(
        "SEMANTIC_NORMALIZATION_MODEL", args.relation_model
    )
    worker = Worker(
        args.backend, args.embedding_model, args.relation_model,
        normalization_model, args.base_url, args.cache, args.no_cache,
    )
    for line in sys.stdin:
        if not line.strip():
            continue
        request: Any = {}
        try:
            request = json.loads(line)
            operation = request.get("op")
            if operation in {"embed", "embed_batch"}:
                texts = request.get("texts") if operation == "embed_batch" else [str(request.get("text", ""))]
                vectors = worker.embed_many([str(text) for text in texts], int(request.get("dimensions", 256)))
                response = {
                    "id": request.get("id"),
                    "embeddings": vectors,
                    "model": worker.embedding_model if worker.backend == "ollama" else "feature-hash-baseline",
                } if operation == "embed_batch" else {
                    "id": request.get("id"),
                    "embedding": vectors[0],
                    "model": worker.embedding_model if worker.backend == "ollama" else "feature-hash-baseline",
                }
            elif operation == "normalize":
                response = {"id": request.get("id"), **worker.normalize(str(request.get("text", "")))}
            elif operation in {"relationship", "classify_relationship"}:
                response = {"id": request.get("id"), **worker.relationship(request.get("left", {}), request.get("right", {}))}
            elif operation == "stats":
                response = {"id": request.get("id"), **worker.stats()}
            else:
                raise WorkerError(f"unsupported operation: {operation}")
            print(json.dumps(response), flush=True)
        except (WorkerError, KeyError, TypeError, ValueError) as error:
            print(json.dumps({"id": request.get("id") if isinstance(request, dict) else None, "workerError": str(error)}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
