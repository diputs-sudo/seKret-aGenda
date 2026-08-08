from backend.models import Citation, DebateDocument, EvidenceCard, Section
from backend.models.sqlite_store import connect, init_db, save_document
from backend.rag import VectorRetrievalEngine


class FakeEmbedder:
    model = "fake"

    def embed(self, text):
        return [1.0]


class FakeVectorStore:
    def search(self, query, embedder, limit):
        assert query == "AI cautious"
        assert embedder.model == "fake"
        assert limit == 3
        return [{"card_id": "card-1", "score": 0.91, "distance": 0.1}]


def test_vector_retrieval_engine_fetches_full_card_metadata(tmp_path):
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
            body="AI can be more cautious than humans.",
        )
    )
    document.sections.append(section)
    save_document(connection, document)
    connection.close()

    engine = VectorRetrievalEngine(db_path, FakeVectorStore(), FakeEmbedder())
    results = engine.search("AI cautious", limit=3)

    assert results[0]["card_id"] == "card-1"
    assert results[0]["score"] == 0.91
    assert results[0]["section"] == "AT: Hyperwar"
    assert results[0]["card_name"] == "Tucker 20"
