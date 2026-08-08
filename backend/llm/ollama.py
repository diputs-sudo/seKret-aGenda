"""Ollama LLM adapter."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from collections.abc import Iterator

from .base import LLM, LLMError


class OllamaLLM(LLM):
    def __init__(
        self,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: int = 120,
    ):
        self.model = model or os.environ.get("SEKRET_OLLAMA_MODEL", "gemma3:4b")
        self.base_url = (base_url or os.environ.get("OLLAMA_BASE_URL", "http://127.0.0.1:11434")).rstrip("/")
        self.timeout_seconds = timeout_seconds

    def generate(self, prompt: str) -> str:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": False,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                data = json.loads(response.read().decode("utf-8"))
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Could not reach Ollama at {self.base_url}. Is Ollama running?"
            ) from exc
        except json.JSONDecodeError as exc:
            raise LLMError("Ollama returned invalid JSON.") from exc

        text = data.get("response")
        if not isinstance(text, str):
            raise LLMError("Ollama response did not include generated text.")
        return text.strip()

    def stream(self, prompt: str) -> Iterator[str]:
        payload = json.dumps(
            {
                "model": self.model,
                "prompt": prompt,
                "stream": True,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                for raw_line in response:
                    if not raw_line.strip():
                        continue
                    try:
                        data = json.loads(raw_line.decode("utf-8"))
                    except json.JSONDecodeError as exc:
                        raise LLMError("Ollama returned invalid streaming JSON.") from exc

                    if "error" in data:
                        raise LLMError(str(data["error"]))

                    chunk = data.get("response")
                    if isinstance(chunk, str) and chunk:
                        yield chunk

                    if data.get("done"):
                        break
        except urllib.error.URLError as exc:
            raise LLMError(
                f"Could not reach Ollama at {self.base_url}. Is Ollama running?"
            ) from exc
