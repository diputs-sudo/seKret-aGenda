from backend.vector_db.chroma_store import ChromaVectorStore
from backend.vector_db.schema import CARD_FAST_COLLECTION


class FakeEmbedder:
    model = "fake-embedder"

    def embed(self, text: str) -> list[float]:
        return [float(len(text)), 1.0]

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


class FakeCollection:
    name = CARD_FAST_COLLECTION

    def __init__(self):
        self.rows = {}

    def upsert(self, ids, documents, embeddings, metadatas):
        for index, card_id in enumerate(ids):
            self.rows[card_id] = {
                "document": documents[index],
                "embedding": embeddings[index],
                "metadata": metadatas[index],
            }

    def query(self, query_embeddings, n_results, include):
        del query_embeddings, include
        ids = list(self.rows)[:n_results]
        return {
            "ids": [ids],
            "metadatas": [[self.rows[card_id]["metadata"] for card_id in ids]],
            "distances": [[0.25 for _ in ids]],
            "documents": [[self.rows[card_id]["document"] for card_id in ids]],
        }


class FakeClient:
    def __init__(self):
        self.collection = FakeCollection()

    def get_or_create_collection(self, name, metadata=None):
        del metadata
        self.collection.name = name
        return self.collection

    def delete_collection(self, name):
        assert name == self.collection.name
        self.collection = FakeCollection()


def test_chroma_vector_store_adds_and_searches_cards():
    store = ChromaVectorStore(client=FakeClient())
    records = [
        {
            "card_id": "card-1",
            "section": "AT: Hyperwar",
            "tag": "AI is risk-averse.",
            "card_name": "Tucker 20",
            "author": "Tucker",
            "year": 2020,
            "citation": "Tucker 20, Defense One.",
            "content_hash": "content-hash",
            "source_text_hash": "source-text-hash",
            "embedding_kind": "fast",
            "parser_version": "docx-v2",
            "document_name": "AI K",
            "embedding_text": "AT: Hyperwar\n\nAI is risk-averse.",
        }
    ]

    total = store.add_cards(records, FakeEmbedder())
    rows = store.search("AI cautious", FakeEmbedder(), limit=1)

    assert total == 1
    assert rows[0]["card_id"] == "card-1"
    assert rows[0]["metadata"]["card_name"] == "Tucker 20"
    assert rows[0]["metadata"]["embedding_kind"] == "fast"
    assert rows[0]["metadata"]["embedding_version"]
    assert rows[0]["metadata"]["parser_version"] == "docx-v2"
    assert rows[0]["metadata"]["content_hash"] == "content-hash"
    assert rows[0]["metadata"]["citation"] == "Tucker 20, Defense One."
    assert rows[0]["score"] == 0.75
