import sqlite3

from backend.models import Citation, DebateDocument, EvidenceCard, HighlightSpan, Section
from backend.models.sqlite_store import (
    card_highlights,
    delete_embedding_records_by_vector_ids,
    filter_changed_embedding_records,
    count_rows,
    embedding_records,
    init_db,
    record_embedding_upserts,
    save_document,
    search_cards,
    stale_embedding_vector_ids,
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
            highlights=[
                HighlightSpan(
                    text="break encryption keys",
                    color="green",
                    run_index=2,
                    style="Emphasis",
                    font_size=11.0,
                    bold=True,
                    underline=False,
                )
            ],
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
    assert result["highlights"][0]["highlight_color"] == "green"
    assert result["highlights"][0]["run_index"] == 2
    assert result["highlights"][0]["style"] == "Emphasis"
    assert result["highlights"][0]["font_size"] == 11.0
    assert result["highlights"][0]["bold"] is True
    assert result["highlights"][0]["underline"] is False


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
    assert record["embedding_kind"] == "fast"
    assert record["content_hash"]
    assert record["source_text_hash"]


def test_deep_embedding_records_include_citation_and_body():
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
            body="This body should be embedded in the deep index.",
            highlights=[HighlightSpan(text="AI can be more cautious than humans")],
            metadata={"section_name": section.name},
        )
    )
    document.sections.append(section)
    save_document(connection, document)

    record = embedding_records(connection, kind="deep")[0]

    assert record["embedding_kind"] == "deep"
    assert "Tucker 20, Defense One." in record["embedding_text"]
    assert "This body should be embedded in the deep index." in record["embedding_text"]


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


def test_embedding_index_metadata_tracks_changed_and_stale_records():
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    init_db(connection)

    document = DebateDocument(name="Generic Backfile", id="doc-1")
    section = Section(name="AT: Harm", document_id=document.id, id="section-1")
    section.cards.append(
        EvidenceCard(
            id="card-1",
            document_id=document.id,
            section_id=section.id,
            tag="Harm is overstated.",
            card_name="Smith 24",
            citation=Citation(raw="Smith 24, Journal.", author="Smith", year=2024),
            body="The harm is smaller than opponents claim.",
            highlights=[HighlightSpan(text="harm is smaller")],
        )
    )
    document.sections.append(section)
    save_document(connection, document)
    records = embedding_records(connection)

    changed, skipped = filter_changed_embedding_records(
        connection,
        records,
        kind="fast",
        embedding_model="fake-model",
    )
    assert changed == records
    assert skipped == 0

    record_embedding_upserts(
        connection,
        records,
        kind="fast",
        embedding_model="fake-model",
        vector_collection="cards_fast",
    )
    changed, skipped = filter_changed_embedding_records(
        connection,
        records,
        kind="fast",
        embedding_model="fake-model",
    )
    assert changed == []
    assert skipped == 1

    stale = stale_embedding_vector_ids(
        connection,
        kind="fast",
        embedding_model="fake-model",
        live_card_ids=set(),
    )
    assert stale == ["card-1"]
    delete_embedding_records_by_vector_ids(
        connection,
        kind="fast",
        embedding_model="fake-model",
        vector_ids=stale,
    )
    assert (
        connection.execute("SELECT COUNT(*) FROM card_embeddings").fetchone()[0]
        == 0
    )
