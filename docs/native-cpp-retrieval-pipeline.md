# Native C++ Retrieval Pipeline

`scripts/native_pipeline.sh` is the no-Python version of the DOCX retrieval
workflow. It compiles a small C++17 command-line binary on first use, then
reuses the compiled binary until its native sources change.

It preserves the current pipeline shape:

```text
DOCX → Debate SQLite → Ollama embeddings → high-recall hybrid retrieval → lightweight reranking → original SQLite evidence
```

The C++ implementation uses the project-owned `native_card_vectors` SQLite
table for exact-cosine vector search. It deliberately does not read Chroma's
Python-managed on-disk format, so no Python or Chroma process is needed at
runtime.

The production command is deliberately lightweight:

```text
query → fast/deep vectors + SQLite FTS → reciprocal-rank fusion
      → human-highlight/tag/section relevance → top evidence cards
```

`analyze` is a separate, slower research command that additionally runs the
full-context reranker, relevance gate, argument clustering, and evidence
bundles. It is not part of an ordinary evidence lookup.

## Prerequisites

- C++17 compiler
- SQLite
- minizip and libxml2 (for DOCX ZIP/XML input)
- local Ollama with the embedding model available:

```bash
ollama pull nomic-embed-text
```

## Equivalent native commands

Use a temporary database while testing; DOCX import replaces the database path
you give it.

```bash
time scripts/native_pipeline.sh import-docx \
  data/Training_Data.docx \
  --db /private/tmp/debate-native.sqlite3

time scripts/native_pipeline.sh build-vector \
  --db /private/tmp/debate-native.sqlite3 \
  --kind all --reset

time scripts/native_pipeline.sh query-vector \
  "state regulation reduces illegal betting" \
  --db /private/tmp/debate-native.sqlite3 \
  --limit 15 --rerank --top 3 --timings

# Default production query: high recall, lightweight reranking, original evidence.
time scripts/native_pipeline.sh query \
  "The opposing team argues that banning institutional investors from buying single family homes will make housing more affordable." \
  --db /private/tmp/debate-native.sqlite3 \
  --limit 15 --top 3 --debug --timings

# Explicit research/debugging mode: full reranking, gate, clustering, and bundles.
time scripts/native_pipeline.sh analyze \
  "The opposing team argues that banning institutional investors from buying single family homes will make housing more affordable." \
  --db /private/tmp/debate-native.sqlite3 \
  --limit 15 --top 3 --debug --timings
```

`import-docx` preserves the source document, sections, cards, citations,
highlights, paragraph provenance, and full card text in the existing SQLite
schema. `build-vector` creates both the fast and deep representations used by
the current hybrid engine. The original text remains authoritative; vectors are
only a retrieval index.

## Options

```text
import-docx <file.docx> --db <database.sqlite3> [--schema <sqlite_schema.sql>]
build-vector --db <database.sqlite3> [--kind fast|deep|all] [--reset] [--max-chars N]
query-vector <query> --db <database.sqlite3> [--limit N] [--rerank] [--top N] [--timings]
query <query> --db <database.sqlite3> [--limit N] [--top N] [--debug] [--timings]
analyze <query> --db <database.sqlite3> [--limit N] [--top N] [--debug] [--concept-debug] [--timings]
```

`query-hybrid` remains a compatibility alias for `query`. `--limit` controls each retrieval lane; `--top` controls the final number of evidence cards for `query` and `analyze`. `--timings` prints the C++ stage breakdown.

The default deep-card input limit is 6,000 characters, matching the existing
native-vector script and keeping local embedding requests within typical model
contexts. `SEKRET_EMBED_MODEL` and `OLLAMA_BASE_URL` continue to configure the
C++ Ollama client.
