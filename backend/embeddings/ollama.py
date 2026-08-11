"""Ollama embedding adapter."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

from .base import Embedder, EmbeddingError


class OllamaEmbedder(Embedder):
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 120,
    ):
        self._model = model or os.environ.get("SEKRET_EMBED_MODEL", "nomic-embed-text")
        self.base_url = (
            base_url or os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
        ).rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._cache: dict[str, list[float]] = {}
        self.last_request_ms: float = 0.0

    @property
    def model(self) -> str:
        return self._model

    def embed(self, text: str) -> list[float]:
        cached = self._cache.get(text)
        if cached is not None:
            self.last_request_ms = 0.0
            return list(cached)

        request_payload = {"model": self.model, "prompt": text}
        options = _ollama_options()
        if options:
            request_payload["options"] = options
        payload = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            started = time.perf_counter()
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            self.last_request_ms = (time.perf_counter() - started) * 1000
        except urllib.error.URLError as exc:
            raise EmbeddingError(
                f"Could not reach Ollama at {self.base_url}. Is Ollama running?"
            ) from exc
        except json.JSONDecodeError as exc:
            raise EmbeddingError("Ollama returned invalid embedding JSON.") from exc

        embedding = data.get("embedding")
        if not isinstance(embedding, list) or not all(
            isinstance(value, int | float) for value in embedding
        ):
            raise EmbeddingError("Ollama response did not include an embedding.")
        vector = [float(value) for value in embedding]
        self._cache[text] = vector
        return list(vector)

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        results: list[list[float] | None] = []
        missing_texts: list[str] = []
        missing_indexes: list[int] = []
        for index, text in enumerate(texts):
            cached = self._cache.get(text)
            if cached is None:
                results.append(None)
                missing_texts.append(text)
                missing_indexes.append(index)
            else:
                results.append(list(cached))

        if not missing_texts:
            self.last_request_ms = 0.0
            return [list(result or []) for result in results]

        request_payload = {"model": self.model, "input": missing_texts}
        options = _ollama_options()
        if options:
            request_payload["options"] = options
        payload = json.dumps(request_payload).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embed",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            started = time.perf_counter()
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
            self.last_request_ms = (time.perf_counter() - started) * 1000
        except urllib.error.URLError:
            vectors = [self.embed(text) for text in missing_texts]
        except json.JSONDecodeError as exc:
            raise EmbeddingError("Ollama returned invalid embedding JSON.") from exc
        else:
            raw_embeddings = data.get("embeddings")
            if not isinstance(raw_embeddings, list):
                vectors = [self.embed(text) for text in missing_texts]
            else:
                vectors = [_validate_embedding(embedding) for embedding in raw_embeddings]

        if len(vectors) != len(missing_texts):
            raise EmbeddingError("Ollama returned the wrong number of embeddings.")

        for index, text, vector in zip(missing_indexes, missing_texts, vectors):
            self._cache[text] = vector
            results[index] = list(vector)

        return [list(result or []) for result in results]


def _validate_embedding(embedding) -> list[float]:
    if not isinstance(embedding, list) or not all(
        isinstance(value, int | float) for value in embedding
    ):
        raise EmbeddingError("Ollama response did not include a valid embedding.")
    return [float(value) for value in embedding]


def _ollama_options() -> dict[str, int]:
    options = {}
    num_gpu = os.environ.get("SEKRET_OLLAMA_NUM_GPU") or os.environ.get("OLLAMA_NUM_GPU")
    if num_gpu:
        try:
            options["num_gpu"] = int(num_gpu)
        except ValueError:
            pass
    main_gpu = os.environ.get("SEKRET_OLLAMA_MAIN_GPU")
    if main_gpu:
        try:
            options["main_gpu"] = int(main_gpu)
        except ValueError:
            pass
    return options
