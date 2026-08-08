import sqlite3

from backend.models import Citation, DebateDocument, EvidenceCard, HighlightSpan, Section
from backend.models.sqlite_store import (
    card_highlights,
    count_rows,
    embedding_records,
    init_db,
    save_document,
    search_cards,
)


def test_save_document_and_search_cards():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)

    document = DebateDocument(name="Training Data", id="doc-1")
    section = Section(name="AT: Quantum", document_id=document.id, id="section-1")
    section.cards.append(
        EvidenceCard(
            id="card-1",
            document_id=document.id,
            section_id=section.id,
            tag="Quantum breaks encryption.",
            card_name="Hunt 26",
            citation=Citation(raw="Hunt 26, CNN.", author="Hunt", year=2026),
            body="Quantum computing can break encryption keys.",
            highlights=[HighlightSpan(text="break encryption keys", color="green")],
            metadata={"section_name": section.name},
        )
    )
    document.sections.append(section)

    save_document(connection, document)

    assert count_rows(connection)["evidence_cards"] == 1
    assert count_rows(connection)["highlights"] == 1
    result = search_cards(connection, "quantum encryption", limit=5)[0]
    assert result["id"] == "card-1"
    assert result["score"] > 0
    assert result["highlights"][0]["text"] == "break encryption keys"


def test_embedding_records_use_section_tag_and_highlights():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)

    document = DebateDocument(name="AI K", id="doc-1")
    section = Section(name="AT: Hyperwar", document_id=document.id, id="section-1")
    section.cards.append(
        EvidenceCard(
            id="card-1",
            document_id=document.id,
            section_id=section.id,
            tag="AI is risk-averse.",
            card_name="Tucker 20",
            citation=Citation(raw="Tucker 20, Defense One.", author="Tucker", year=2020),
            body="This body should not be embedded in the fast index.",
            highlights=[HighlightSpan(text="AI can be more cautious than humans")],
            metadata={"section_name": section.name},
        )
    )
    document.sections.append(section)
    save_document(connection, document)

    record = embedding_records(connection)[0]

    assert "AT: Hyperwar" in record["embedding_text"]
    assert "AI is risk-averse." in record["embedding_text"]
    assert "AI can be more cautious than humans" in record["embedding_text"]
    assert "This body should not be embedded" not in record["embedding_text"]
    assert record["citation"] == "Tucker 20, Defense One."


def test_card_highlights_returns_all_highlighted_content_by_default():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)

    document = DebateDocument(name="AI K", id="doc-1")
    section = Section(name="AT: Hyperwar", document_id=document.id, id="section-1")
    section.cards.append(
        EvidenceCard(
            id="card-1",
            document_id=document.id,
            section_id=section.id,
            tag="AI is risk-averse.",
            card_name="Tucker 20",
            citation=Citation(raw="Tucker 20, Defense One.", author="Tucker", year=2020),
            body="AI can be more cautious than humans.\n\nMachines lower confidence.",
            highlights=[
                HighlightSpan(text="AI can be more cautious than humans", paragraph_index=1),
                HighlightSpan(text="Machines lower confidence", paragraph_index=2),
                HighlightSpan(text="Humans overestimate limited data", paragraph_index=3),
                HighlightSpan(text="Machine judgment checks human pride", paragraph_index=4),
                HighlightSpan(text="AI support improves security analysis", paragraph_index=5),
                HighlightSpan(text="Confidence drops when sources disappear", paragraph_index=6),
            ],
            metadata={"section_name": section.name},
        )
    )
    document.sections.append(section)
    save_document(connection, document)

    highlights = card_highlights(connection, "card-1")

    assert len(highlights) == 6
    assert highlights[-1]["text"] == "Confidence drops when sources disappear"


def test_search_accepts_natural_language_punctuation():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)

    document = DebateDocument(name="AI K", id="doc-1")
    section = Section(name="AT: Hyperwar", document_id=document.id, id="section-1")
    section.cards.append(
        EvidenceCard(
            id="card-1",
            document_id=document.id,
            section_id=section.id,
            tag="AI is risk-averse.",
            card_name="Tucker 20",
            citation=Citation(raw="Tucker 20, Defense One.", author="Tucker", year=2020),
            body="AI can be more cautious than humans when data is limited.",
            highlights=[HighlightSpan(text="AI can be more cautious than humans")],
            metadata={"section_name": section.name},
        )
    )
    document.sections.append(section)
    save_document(connection, document)

    result = search_cards(connection, "Why is AI risk-averse?", limit=5)[0]

    assert result["id"] == "card-1"
