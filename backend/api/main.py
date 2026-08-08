"""FastAPI backend for seKret aGenda."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from backend.generation import GenerationService
from backend.llm import LLMError, OllamaLLM
from backend.prompt import GenerationMode
from backend.rag import RetrievalEngine, SearchRequest

DEFAULT_DB_PATH = Path(os.environ.get("SEKRET_DB_PATH", "var/sekret-agenda.sqlite3"))

app = FastAPI(title="seKret aGenda")


class SearchBody(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(default=10, ge=1, le=50)


class GenerateBody(BaseModel):
    query: str = Field(min_length=1)
    mode: GenerationMode = GenerationMode.DRAFT
    limit: int = Field(default=5, ge=1, le=20)
    include_prompt: bool = False


@app.get("/status")
def status() -> dict[str, Any]:
    return {
        "ok": True,
        "db_path": str(DEFAULT_DB_PATH),
        "db_exists": DEFAULT_DB_PATH.exists(),
    }


@app.post("/search")
def search(body: SearchBody) -> list[dict[str, Any]]:
    engine = RetrievalEngine(DEFAULT_DB_PATH)
    return engine.search(SearchRequest(query=body.query, limit=body.limit))


@app.post("/generate")
def generate(body: GenerateBody) -> dict[str, Any]:
    service = GenerationService(DEFAULT_DB_PATH, OllamaLLM())
    try:
        return service.generate(
            query=body.query,
            mode=body.mode,
            limit=body.limit,
            include_prompt=body.include_prompt,
        )
    except LLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
