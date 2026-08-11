from backend.models import Citation, DebateDocument, EvidenceCard, HighlightSpan, Section
from backend.models.sqlite_store import connect, init_db, save_document
from backend.rag import HybridRetrievalEngine, HybridSearchRequest


class FakeEmbedder:
    model = "fake"

    def embed(self, text):
        return [1.0]


class CountingEmbedder(FakeEmbedder):
    def __init__(self):
        self.calls = []

    def embed(self, text):
        self.calls.append(text)
        return [float(len(text))]


class FakeStore:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def search(self, query, embedder, limit):
        self.calls.append((query, embedder.model, limit))
        return self.rows[:limit]


class EmbeddingStore:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def search_by_embedding(self, query_embedding, limit):
        self.calls.append((query_embedding, limit))
        return self.rows[:limit]


def test_hybrid_retrieval_broadly_retrieves_and_fuses_sources(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)
    fast_store = FakeStore(
        [{"card_id": "tucker", "score": 0.82, "metadata": {"tag": "AI is risk-averse."}}]
    )
    deep_store = FakeStore(
        [{"card_id": "cox", "score": 0.79, "metadata": {"tag": "AI defuses escalation."}}]
    )

    engine = HybridRetrievalEngine(
        db_path,
        FakeEmbedder(),
        fast_store=fast_store,
        deep_store=deep_store,
    )
    results = engine.search(
        HybridSearchRequest(
            query="Opponent says AI escalates because of automation.",
            limit=5,
            vector_limit=50,
            lexical_limit=50,
        )
    )

    ids = [row["card_id"] for row in results]
    assert "cox" in ids
    assert fast_store.calls[0][0] == "AI escalates because of automation"
    assert results[0]["retrieval_score"] > 0
    assert results[0]["source_ranks"]
    assert results[0]["highlights"]

    trace = engine.debug_trace(
        HybridSearchRequest(
            query="Opponent says AI escalates because of automation.",
            limit=5,
        )
    )
    assert trace["retrieval_text"] == "AI escalates because of automation"
    assert trace["source_results"]["author_citation"] == []


def test_hybrid_retrieval_applies_author_filter_as_direct_lookup(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)
    fast_store = FakeStore(
        [
            {"card_id": "cox", "score": 0.9, "metadata": {"tag": "AI defuses escalation."}},
            {"card_id": "tucker", "score": 0.5, "metadata": {"tag": "AI is risk-averse."}},
        ]
    )
    deep_store = FakeStore([])
    engine = HybridRetrievalEngine(
        db_path,
        FakeEmbedder(),
        fast_store=fast_store,
        deep_store=deep_store,
    )

    results = engine.search("author:Tucker AI cautious", limit=5)

    assert [row["card_id"] for row in results] == ["tucker"]
    assert results[0]["author"] == "Tucker"
    assert results[0]["source_ranks"] == {"author_lookup": 1}
    assert fast_store.calls == []
    assert deep_store.calls == []


def test_hybrid_retrieval_citation_lookup_skips_vectors(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)
    fast_store = FakeStore(
        [{"card_id": "cox", "score": 0.99, "metadata": {"tag": "AI defuses escalation."}}]
    )
    deep_store = FakeStore(
        [{"card_id": "goldfarb", "score": 0.99, "metadata": {"tag": "Human control."}}]
    )
    engine = HybridRetrievalEngine(
        db_path,
        FakeEmbedder(),
        fast_store=fast_store,
        deep_store=deep_store,
    )

    results = engine.search("Tucker 20", limit=5)
    trace = engine.debug_trace("Tucker 20")

    assert [row["card_id"] for row in results] == ["tucker"]
    assert results[0]["source_ranks"] == {"citation_lookup": 1}
    assert trace["source_results"].keys() == {"citation_lookup"}
    assert fast_store.calls == []
    assert deep_store.calls == []


def test_hybrid_retrieval_author_lookup_skips_vectors(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)
    fast_store = FakeStore([])
    deep_store = FakeStore([])
    engine = HybridRetrievalEngine(
        db_path,
        FakeEmbedder(),
        fast_store=fast_store,
        deep_store=deep_store,
    )

    results = engine.search("Tucker", limit=5)

    assert [row["card_id"] for row in results] == ["tucker"]
    assert results[0]["source_ranks"] == {"author_lookup": 1}
    assert fast_store.calls == []
    assert deep_store.calls == []


def test_hybrid_retrieval_general_search_does_not_apply_argument_gate(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)
    fast_store = FakeStore(
        [{"card_id": "goldfarb", "score": 0.8, "metadata": {"tag": "Human control."}}]
    )
    deep_store = FakeStore([])
    engine = HybridRetrievalEngine(
        db_path,
        FakeEmbedder(),
        fast_store=fast_store,
        deep_store=deep_store,
    )

    trace = engine.debug_trace("Human oversight prevents AI mistakes.")

    assert trace["selected"]
    assert "goldfarb" in [row["card_id"] for row in trace["selected"]]
    assert fast_store.calls


def test_hybrid_retrieval_general_search_returns_no_evidence_for_weak_matches(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)
    fast_store = FakeStore(
        [{"card_id": "revenue", "score": 0.2, "metadata": {"tag": "AI revenue."}}]
    )
    deep_store = FakeStore([])
    engine = HybridRetrievalEngine(
        db_path,
        FakeEmbedder(),
        fast_store=fast_store,
        deep_store=deep_store,
    )

    trace = engine.debug_trace("Penguins on Mars")

    assert trace["selected"] == []
    assert trace["accepted"] == []


def test_hybrid_retrieval_reuses_one_query_embedding_for_fast_and_deep(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)
    embedder = CountingEmbedder()
    fast_store = EmbeddingStore(
        [{"card_id": "goldfarb", "score": 0.8, "metadata": {"tag": "Human control."}}]
    )
    deep_store = EmbeddingStore(
        [{"card_id": "cox", "score": 0.7, "metadata": {"tag": "AI defuses escalation."}}]
    )
    engine = HybridRetrievalEngine(
        db_path,
        embedder,
        fast_store=fast_store,
        deep_store=deep_store,
    )

    engine.debug_trace("Human oversight prevents AI mistakes.")

    assert len(embedder.calls) == 1
    assert fast_store.calls[0][0] == deep_store.calls[0][0]


def test_hybrid_retrieval_rejects_wrong_mechanism_after_reranking(tmp_path):
    db_path = tmp_path / "test.sqlite3"
    _write_cards(db_path)
    fast_store = FakeStore(
        [
            {
                "card_id": "revenue",
                "score": 0.99,
                "metadata": {"tag": "AI increases betting revenue."},
            },
            {
                "card_id": "cox",
                "score": 0.5,
                "metadata": {"tag": "AI defuses escalation."},
            },
        ]
    )
    deep_store = FakeStore([])
    engine = HybridRetrievalEngine(
        db_path,
        FakeEmbedder(),
        fast_store=fast_store,
        deep_store=deep_store,
    )

    trace = engine.debug_trace(
        HybridSearchRequest(
            query="Opponent says AI escalates because of automation.",
            limit=5,
        )
    )

    assert "cox" in [row["card_id"] for row in trace["selected"]]
    assert "revenue" not in [row["card_id"] for row in trace["selected"]]
    assert "revenue" in [row["card_id"] for row in trace["rejected"]]


def _write_cards(db_path):
    connection = connect(db_path)
    init_db(connection)
    document = DebateDocument(name="AI K", id="doc-1")
    section = Section(name="AT: Hyperwar", document_id=document.id, id="section-1")
    section.cards.extend(
        [
            EvidenceCard(
                id="tucker",
                document_id=document.id,
                section_id=section.id,
                tag="AI is risk-averse.",
                card_name="Tucker 20",
                citation=Citation(raw="Tucker 20, Defense One.", author="Tucker", year=2020),
                body="AI can be more cautious than humans when automation faces limited data.",
                highlights=[HighlightSpan(text="AI can be more cautious than humans")],
                metadata={"section_name": section.name},
            ),
            EvidenceCard(
                id="cox",
                document_id=document.id,
                section_id=section.id,
                tag="AI defuses escalation.",
                card_name="Cox 21",
                citation=Citation(raw="Cox 21, War on the Rocks.", author="Cox", year=2021),
                body="AI improves warning accuracy and reduces unintended escalation.",
                highlights=[HighlightSpan(text="reduces unintended escalation")],
                metadata={"section_name": section.name},
            ),
            EvidenceCard(
                id="goldfarb",
                document_id=document.id,
                section_id=section.id,
                tag="Humans maintain control and stabilize dynamics.",
                card_name="Goldfarb 22",
                citation=Citation(raw="Goldfarb 22, Brookings.", author="Goldfarb", year=2022),
                body="Human control over military AI decision-making stabilizes conflict.",
                highlights=[HighlightSpan(text="Human control over military AI")],
                metadata={"section_name": section.name},
            ),
            EvidenceCard(
                id="revenue",
                document_id=document.id,
                section_id=section.id,
                tag="AI increases betting revenue.",
                card_name="Market 25",
                citation=Citation(raw="Market 25, Sportsbook News.", author="Market", year=2025),
                body="AI behavior manipulation increases sportsbook revenue.",
                highlights=[
                    HighlightSpan(
                        text="AI behavior manipulation increases sportsbook revenue"
                    )
                ],
                metadata={"section_name": section.name},
            ),
        ]
    )
    document.sections.append(section)
    save_document(connection, document)
    connection.close()
