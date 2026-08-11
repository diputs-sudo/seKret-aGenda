# Vector Strategy

The Python prototype uses Chroma collections (`cards_fast`, `cards_deep`) for
vector retrieval. The native app backend will not read Chroma internals
directly from C++.

The transition order is:

1. Port deterministic hybrid behavior first: query intent, SQLite retrieval,
   reciprocal-rank fusion, mechanism parsing, reranking, gating, and argument
   selection.
2. Keep vector search behind a narrow C++ interface so the orchestration code
   does not depend on a specific vector database.
3. Add the vector implementation after SQLite/reranker parity tests pass.

Candidate vector implementations considered:

- Local service bridge to the existing Chroma index.
- App-native vector table/index owned by the desktop backend.
- Temporary no-vector mode for deterministic parity work.

Current decision: use an app-native SQLite vector cache owned by the desktop
backend. The hybrid engine checks this cache before calling Ollama, so installs
without native vectors still fall back to deterministic SQLite retrieval without
network/model work.

The cache table contract is:

```sql
CREATE TABLE native_card_vectors (
    card_id TEXT NOT NULL,
    embedding_kind TEXT NOT NULL,
    embedding_model TEXT NOT NULL,
    vector_json TEXT NOT NULL,
    updated_at TEXT,
    PRIMARY KEY (card_id, embedding_kind, embedding_model)
);
```

`embedding_kind` is `fast` or `deep`. `vector_json` is a JSON array of numbers.
The first implementation does exact cosine search over cached vectors; an ANN
index can replace the internals later without changing the hybrid orchestration
interface.

Runtime notes:

- The hybrid engine checks whether fast/deep vectors exist before calling
  Ollama, so databases without `native_card_vectors` do not pay embedding
  latency.
- When either vector lane is available, the query is embedded once and reused
  for both fast and deep exact-cosine searches.
