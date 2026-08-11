import sqlite3
from pathlib import Path

from backend.models import Citation, DebateDocument, EvidenceCard, HighlightSpan, Section
from backend.models.sqlite_store import connect, init_db, save_document
from scripts.build_native_vector_cache import (
    build_native_vector_cache,
    ensure_native_vector_table,
    _clip_embedding_text,
)


class FakeEmbedder:
    model = "fake-native"

    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]


def test_build_native_vector_cache_writes_fast_and_deep_vectors(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)

    totals = build_native_vector_cache(
        db_path,
        FakeEmbedder(),
        kinds=[],
        reset=True,
    )
    assert totals == {}

    from backend.models import EmbeddingKind

    totals = build_native_vector_cache(
        db_path,
        FakeEmbedder(),
        kinds=[EmbeddingKind.FAST, EmbeddingKind.DEEP],
        reset=True,
    )

    assert totals == {"fast": 1, "deep": 1}
    connection = sqlite3.connect(db_path)
    rows = connection.execute(
        """
        SELECT embedding_kind, embedding_model, vector_json
        FROM native_card_vectors
        ORDER BY embedding_kind
        """
    ).fetchall()
    connection.close()

    assert [row[0] for row in rows] == ["deep", "fast"]
    assert all(row[1] == "fake-native" for row in rows)
    assert all(row[2].startswith("[") for row in rows)


def test_ensure_native_vector_table_is_idempotent(tmp_path):
    connection = sqlite3.connect(tmp_path / "cache.sqlite3")
    ensure_native_vector_table(connection)
    ensure_native_vector_table(connection)
    assert connection.execute(
        "SELECT name FROM sqlite_master WHERE name = 'native_card_vectors'"
    ).fetchone()
    connection.close()


def test_clip_embedding_text_prefers_paragraph_boundary():
    text = "a" * 20 + "\n\n" + "b" * 100
    assert _clip_embedding_text(text, 50) == text[:50].rstrip()


def _write_cards(db_path: Path) -> None:
    connection = connect(db_path)
    init_db(connection)
    document = DebateDocument(name="AI K", id="doc-1")
    section = Section(name="AT: Hyperwar", document_id=document.id, id="section-1")
    section.cards.append(
        EvidenceCard(
            id="cox",
            document_id=document.id,
            section_id=section.id,
            tag="AI defuses escalation.",
            card_name="Cox 21",
            citation=Citation(raw="Cox 21, War on the Rocks.", author="Cox", year=2021),
            body="AI improves warning accuracy and reduces unintended escalation.",
            highlights=[HighlightSpan(text="reduces unintended escalation")],
        )
    )
    document.sections.append(section)
    save_document(connection, document)
    connection.close()
