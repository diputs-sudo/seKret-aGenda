# Architecture

seKret aGenda uses two databases with separate responsibilities.

SQLite is the source of truth. It stores documents, sections, evidence cards, citations, highlights, parser metadata, and relationships.

ChromaDB is the semantic search index. It stores embeddings plus enough metadata to find the matching card in SQLite.

The vector database is disposable. If the embedding model changes, or if the vector index becomes stale, it can be deleted and rebuilt from SQLite.

## Pipeline

```text
                   DOCX
                     |
                     v
                 Parser
                     |
                     v
                DebateIR
                     |
        +------------+------------+
        v                         v
     SQLite                 Embeddings
   Ground Truth                  |
        ^                        v
        |                    ChromaDB
        |                        |
        +------------+-----------+
                     v
              Search Results IDs
                     |
                     v
              Fetch Full Cards
                     |
                     v
                   LLM
```

## DebateIR

`DebateIR` is the parser boundary.

The parser should convert source documents into a clean intermediate representation before anything touches SQLite, ChromaDB, FastAPI, or Ollama.

This keeps parsing testable offline:

```text
DOCX -> DebateIR -> JSON fixture
```

The first DOCX fixture suggests a useful starting heuristic:

- `Heading3` often marks a section or `AT:` header.
- `Heading4` often marks a card tag.
- The next paragraph after a tag is usually the citation.
- Following paragraphs are card body until the next `Heading4` or `Heading3`.
- Word highlights are stored as real OOXML `w:highlight` values and should be preserved.

## SQLite

SQLite stores the full card and all structured details.

Expected core tables:

- `debate_documents`
- `sections`
- `evidence_cards`
- `citations`
- `highlights`
- `parse_runs`

SQLite answers questions like:

- What document did this card come from?
- Which section is this card under?
- What is the full body text?
- Which exact spans were highlighted?
- What parser version produced this card?
- Has this card changed since the last index run?

## ChromaDB

ChromaDB stores only semantic search entries.

One vector should represent one evidence card, not a full document and not a section.

Vector entries should contain:

- `id`
- `embedding`
- `metadata.card_id`
- `metadata.section_name`
- `metadata.document_name`
- `metadata.tag`
- `metadata.author`
- `metadata.year`
- `metadata.category`
- `metadata.topical`
- `metadata.timestamp`

The vector DB should not store full body text or long paragraphs. It should return IDs and scores.

## Search Flow

```text
User Prompt
    |
    v
Embedding
    |
    v
ChromaDB
    |
    v
Top Card IDs
    |
    v
SQLite
    |
    v
Full Evidence Cards
    |
    v
LLM
```

## Embedding Strategy

The MVP should start with one embedding per card.

Fast embedding text:

```text
section name
tag
highlighted evidence
```

This avoids embedding entire articles when only the tag and read-round evidence are usually relevant for retrieval.

Later, the system can add a second embedding:

Fast collection:

```text
tag + highlights
```

Deep collection:

```text
section + tag + citation + full card body
```

Then retrieval can use:

```text
query -> fast top 50 -> deep rerank -> top 8 IDs -> SQLite fetch
```

## Keyword Search

SQLite FTS5 should eventually be used alongside vector search.

This helps with exact debate searches:

- `Tucker 20`
- `AT: Hyperwar`
- `cap good`
- `post-quantum cryptography`

The retrieval engine can later combine semantic score, keyword score, and metadata filters.

