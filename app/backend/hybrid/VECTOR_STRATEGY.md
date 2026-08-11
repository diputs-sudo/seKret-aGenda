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

Candidate vector implementations:

- Local service bridge to the existing Chroma index.
- App-native vector table/index owned by the desktop backend.
- Temporary no-vector mode for deterministic parity work.

Current decision: implement the deterministic SQLite + reranker hybrid path
first, then add vectors through an interface rather than coupling C++ to
Chroma's Python storage details.
