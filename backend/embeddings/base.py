"""Embedding abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod


class EmbeddingError(RuntimeError):
    """Raised when an embedding backend cannot produce vectors."""


class Embedder(ABC):
    @property
    @abstractmethod
    def model(self) -> str:
        """Embedding model name."""

    @abstractmethod
    def embed(self, text: str) -> list[float]:
        """Embed one text string."""

