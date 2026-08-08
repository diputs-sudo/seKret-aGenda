from backend.generation import GenerationService
from backend.llm import LLM
from backend.models import Citation, DebateDocument, EvidenceCard, HighlightSpan, Section
from backend.models.sqlite_store import connect, init_db, save_document
from backend.prompt import GenerationMode


class FakeLLM(LLM):
    def generate(self, prompt: str) -> str:
        assert "AI is risk-averse." in prompt
        return "AI is cautious because Tucker 20 says machines lower confidence when data is limited.\n\nSources:\n- Tucker 20"

    def stream(self, prompt: str):
        assert "AI is risk-averse." in prompt
        yield "AI is cautious "
        yield "because Tucker 20 says so."


def test_generation_service_searches_builds_prompt_and_generates(tmp_path):
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
            highlights=[HighlightSpan(text="AI can be more cautious than humans")],
            metadata={"section_name": section.name},
        )
    )
    document.sections.append(section)
    save_document(connection, document)
    connection.close()

    service = GenerationService(db_path, FakeLLM())
    result = service.generate(
        "AI cautious",
        mode=GenerationMode.DRAFT,
        include_prompt=True,
    )

    assert "Tucker 20" in result["answer"]
    assert result["mode"] == "draft"
    assert result["cards"][0]["card_id"] == "card-1"
    assert "prompt" in result


def test_generation_service_streams_answer(tmp_path):
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
            highlights=[HighlightSpan(text="AI can be more cautious than humans")],
            metadata={"section_name": section.name},
        )
    )
    document.sections.append(section)
    save_document(connection, document)
    connection.close()

    service = GenerationService(db_path, FakeLLM())
    cards, chunks = service.stream_answer("AI cautious")

    assert cards[0]["card_id"] == "card-1"
    assert "".join(chunks) == "AI is cautious because Tucker 20 says so."
