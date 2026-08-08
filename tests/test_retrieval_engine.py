from backend.models import Citation, DebateDocument, EvidenceCard, HighlightSpan, Section
from backend.models.sqlite_store import connect, init_db, save_document
from backend.rag import RetrievalEngine, SearchRequest


def test_retrieval_engine_returns_api_shaped_results(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    connection = connect(db_path)
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
            highlights=[
                HighlightSpan(
                    text="AI can be more cautious than humans",
                    color="green",
                )
            ],
            metadata={"section_name": section.name},
        )
    )
    document.sections.append(section)
    save_document(connection, document)
    connection.close()

    engine = RetrievalEngine(db_path)
    results = engine.search(SearchRequest(query="AI cautious", limit=3))

    assert results[0]["card_id"] == "card-1"
    assert results[0]["section"] == "AT: Hyperwar"
    assert results[0]["tag"] == "AI is risk-averse."
    assert results[0]["score"] > 0
    assert results[0]["highlights"][0]["text"] == "AI can be more cautious than humans"
