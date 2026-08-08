"""Debate intermediate representation.

These models describe parsed debate evidence before it is written to SQLite or
embedded into a vector database.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from hashlib import sha256
from typing import Any
from uuid import uuid4


class ArgumentType(str, Enum):
    ANSWER_TO = "answer_to"
    OVERVIEW = "overview"
    ARGUMENT = "argument"
    UNKNOWN = "unknown"


class EmbeddingKind(str, Enum):
    FAST = "fast"
    DEEP = "deep"


@dataclass(frozen=True)
class HighlightSpan:
    text: str
    color: str | None = None
    paragraph_index: int | None = None
    run_index: int | None = None
    start_char: int | None = None
    end_char: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class Citation:
    raw: str
    author: str | None = None
    year: int | None = None
    source_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class EvidenceCard:
    tag: str
    citation: Citation
    body: str
    section_id: str
    document_id: str
    id: str = field(default_factory=lambda: str(uuid4()))
    card_name: str | None = None
    highlights: list[HighlightSpan] = field(default_factory=list)
    category: str | None = None
    topical: bool | None = None
    paragraph_start: int | None = None
    paragraph_end: int | None = None
    source_format: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def content_hash(self) -> str:
        parts = [
            self.document_id,
            self.section_id,
            self.tag,
            self.citation.raw,
            self.body,
            "|".join(highlight.text for highlight in self.highlights),
        ]
        return sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def embedding_text(self, kind: EmbeddingKind = EmbeddingKind.FAST) -> str:
        section_name = str(self.metadata.get("section_name", ""))
        highlighted = "\n".join(highlight.text for highlight in self.highlights)
        if kind == EmbeddingKind.FAST:
            return "\n\n".join(part for part in [section_name, self.tag, highlighted] if part)

        return "\n\n".join(
            part
            for part in [section_name, self.tag, self.citation.raw, highlighted, self.body]
            if part
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        data["content_hash"] = self.content_hash
        return data


@dataclass
class Section:
    name: str
    document_id: str
    id: str = field(default_factory=lambda: str(uuid4()))
    argument_type: ArgumentType = ArgumentType.UNKNOWN
    parent_id: str | None = None
    order_index: int | None = None
    cards: list[EvidenceCard] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["argument_type"] = self.argument_type.value
        return data


@dataclass
class DebateDocument:
    name: str
    id: str = field(default_factory=lambda: str(uuid4()))
    source_path: str | None = None
    source_format: str | None = None
    sections: list[Section] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def all_cards(self) -> list[EvidenceCard]:
        return [card for section in self.sections for card in section.cards]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = self.created_at.isoformat()
        return data


@dataclass(frozen=True)
class ParseRun:
    document_id: str
    parser_version: str
    id: str = field(default_factory=lambda: str(uuid4()))
    source_format: str | None = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: datetime | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["started_at"] = self.started_at.isoformat()
        data["completed_at"] = (
            self.completed_at.isoformat() if self.completed_at else None
        )
        return data


@dataclass(frozen=True)
class VectorMetadata:
    card_id: str
    section_name: str
    document_name: str
    tag: str
    author: str | None = None
    year: int | None = None
    category: str | None = None
    topical: bool | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_chroma_metadata(self) -> dict[str, str | int | float | bool | None]:
        return {
            "card_id": self.card_id,
            "section_name": self.section_name,
            "document_name": self.document_name,
            "tag": self.tag,
            "author": self.author,
            "year": self.year,
            "category": self.category,
            "topical": self.topical,
            "timestamp": self.timestamp.isoformat(),
        }


@dataclass(frozen=True)
class VectorEntry:
    id: str
    embedding: list[float]
    metadata: VectorMetadata
    embedding_kind: EmbeddingKind = EmbeddingKind.FAST

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "embedding": self.embedding,
            "embedding_kind": self.embedding_kind.value,
            "metadata": self.metadata.to_chroma_metadata(),
        }
