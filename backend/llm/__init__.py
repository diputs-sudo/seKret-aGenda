"""LLM adapters."""

from .base import LLM, LLMError
from .ollama import OllamaLLM

__all__ = ["LLM", "LLMError", "OllamaLLM"]

