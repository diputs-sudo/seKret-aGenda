"""Ollama embedding adapter."""

from __future__ import annotations

import json
import os
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

    @property
    def model(self) -> str:
        return self._model

    def embed(self, text: str) -> list[float]:
        payload = json.dumps({"model": self.model, "prompt": text}).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/embeddings",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
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
        return [float(value) for value in embedding]

