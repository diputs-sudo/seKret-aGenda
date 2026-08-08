"""Embedding adapters."""

from .base import Embedder, EmbeddingError
from .ollama import OllamaEmbedder

__all__ = ["Embedder", "EmbeddingError", "OllamaEmbedder"]

