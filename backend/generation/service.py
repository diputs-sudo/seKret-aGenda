"""Grounded answer generation service."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from backend.llm import LLM
from backend.prompt import GenerationMode, PromptBuilder
from backend.rag import ArgumentBuilder, RetrievalEngine, SearchRequest, validate_sources


@dataclass(frozen=True)
class GenerationResult:
    query: str
    mode: str
    answer: str
    cards: list[dict[str, Any]]
    argument_bundle: dict[str, Any]
    source_integrity: dict[str, Any]
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
        self.argument_builder = ArgumentBuilder()

    def generate(
        self,
        query: str,
        limit: int = 5,
        mode: GenerationMode | str = GenerationMode.DRAFT,
        include_prompt: bool = False,
    ) -> dict[str, Any]:
        mode = GenerationMode(mode)
        cards = self.retrieval.search(SearchRequest(query=query, limit=limit))
        bundle = self.argument_builder.build(query, cards, limit=limit)
        prompt = self.prompt_builder.build_from_bundle(bundle, mode=mode)
        answer = self.llm.generate(prompt)
        source_integrity = validate_sources(answer, bundle)
        answer = _enforce_source_label(answer, source_integrity.source_status)
        result = GenerationResult(
            query=query,
            mode=mode.value,
            answer=answer,
            cards=bundle.cards,
            argument_bundle=bundle.to_dict(),
            source_integrity=source_integrity.to_dict(),
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
        bundle = self.argument_builder.build(query, cards, limit=limit)
        prompt = self.prompt_builder.build_from_bundle(bundle, mode=mode)
        return bundle.cards, self.llm.stream(prompt)


def _enforce_source_label(answer: str, source_status: str) -> str:
    label = f"[{source_status}]"
    stripped = answer.lstrip()
    if stripped.startswith("[BACKFILE-SOURCED]") or stripped.startswith("[ANALYSIS ONLY]"):
        return answer
    return f"{label}\n{answer}"
