"""LLM abstraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterator


class LLMError(RuntimeError):
    """Raised when an LLM backend cannot generate a response."""


class LLM(ABC):
    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate text from a prompt."""

    def stream(self, prompt: str) -> Iterator[str]:
        """Stream generated text chunks from a prompt."""
        yield self.generate(prompt)
