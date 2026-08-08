from backend.models import (
    Citation,
    DebateDocument,
    EmbeddingKind,
    EvidenceCard,
    HighlightSpan,
    Section,
    VectorEntry,
    VectorMetadata,
)


def test_card_content_hash_changes_when_body_changes():
    citation = Citation(raw="Tucker 20, Defense One.")
    card = EvidenceCard(
        document_id="doc-1",
        section_id="section-1",
        tag="AI is risk-averse.",
        citation=citation,
        body="Machines lower confidence with limited data.",
    )
    changed = EvidenceCard(
        document_id="doc-1",
        section_id="section-1",
        tag="AI is risk-averse.",
        citation=citation,
        body="Humans lower confidence with limited data.",
    )

    assert card.content_hash != changed.content_hash


def test_fast_embedding_uses_tag_and_highlights_only():
    card = EvidenceCard(
        document_id="doc-1",
        section_id="section-1",
        tag="AI is risk-averse.",
        citation=Citation(raw="Tucker 20, Defense One."),
        body="This full body should not be in the fast embedding text.",
        highlights=[HighlightSpan(text="Machine confidence is lower than humans.")],
    )

    text = card.embedding_text(EmbeddingKind.FAST)

    assert "AI is risk-averse." in text
    assert "Machine confidence is lower than humans." in text
    assert "This full body" not in text


def test_document_collects_cards_from_sections():
    document = DebateDocument(name="AI K", id="doc-1")
    section = Section(name="AT: Hyperwar", document_id=document.id, id="section-1")
    section.cards.append(
        EvidenceCard(
            document_id=document.id,
            section_id=section.id,
            tag="AI is risk-averse.",
            citation=Citation(raw="Tucker 20, Defense One."),
            body="Evidence body.",
        )
    )
    document.sections.append(section)

    assert len(document.all_cards()) == 1


def test_vector_metadata_serializes_for_chroma():
    metadata = VectorMetadata(
        card_id="card-1",
        section_name="AT: Hyperwar",
        document_name="AI K",
        tag="AI is risk-averse.",
        author="Tucker",
        year=2020,
        topical=True,
    )
    entry = VectorEntry(id="vector-1", embedding=[0.1, 0.2], metadata=metadata)

    serialized = entry.to_dict()

    assert serialized["metadata"]["card_id"] == "card-1"
    assert serialized["metadata"]["year"] == 2020
    assert serialized["embedding_kind"] == "fast"
