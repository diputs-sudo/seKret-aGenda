"""Grounded answer generation service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from backend.llm import LLM
from backend.prompt import GenerationMode, PromptBuilder
from backend.rag import RetrievalEngine, SearchRequest


@dataclass(frozen=True)
class GenerationResult:
    query: str
    mode: str
    answer: str
    cards: list[dict[str, Any]]
    prompt: str

    def to_dict(self, include_prompt: bool = False) -> dict[str, Any]:
        data = asdict(self)
        if not include_prompt:
            data.pop("prompt", None)
        return data


class GenerationService:
    def __init__(
        self,
        db_path: str | Path,
        llm: LLM,
        prompt_builder: type[PromptBuilder] = PromptBuilder,
    ):
        self.retrieval = RetrievalEngine(db_path)
        self.llm = llm
        self.prompt_builder = prompt_builder

    def generate(
        self,
        query: str,
        limit: int = 5,
        mode: GenerationMode | str = GenerationMode.DRAFT,
        include_prompt: bool = False,
    ) -> dict[str, Any]:
        mode = GenerationMode(mode)
        cards = self.retrieval.search(SearchRequest(query=query, limit=limit))
        prompt = self.prompt_builder.build(query, cards, mode=mode)
        answer = self.llm.generate(prompt)
        result = GenerationResult(
            query=query,
            mode=mode.value,
            answer=answer,
            cards=cards,
            prompt=prompt,
        )
        return result.to_dict(include_prompt=include_prompt)

    def stream_answer(
        self,
        query: str,
        limit: int = 5,
        mode: GenerationMode | str = GenerationMode.DRAFT,
    ) -> tuple[list[dict[str, Any]], Iterator[str]]:
        mode = GenerationMode(mode)
        cards = self.retrieval.search(SearchRequest(query=query, limit=limit))
        prompt = self.prompt_builder.build(query, cards, mode=mode)
        return cards, self.llm.stream(prompt)
