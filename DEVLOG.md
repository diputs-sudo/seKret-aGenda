# DEVLOG

---

## 2026-08-06

### Project Created

Created the initial repository for **seKret aGenda**.

Goal:

Create an offline-first AI reading assistant capable of indexing large document collections into a local vector database for semantic retrieval and Google Docs integration.

### Planned Architecture

```text
Google Docs
    |
    v
Parser
    |
    v
Evidence Cards
    |
    v
Embeddings
    |
    v
Vector Database
    |
    v
LLM
    |
    v
Chrome Extension
```

### Initial Decisions

Backend:
- FastAPI

Embedding:
- nomic-embed-text (tentative)

Vector DB:
- ChromaDB (tentative)

LLM:
- Qwen3 8B (tentative)

Extension:
- Plasmo + React

### Parser Direction

Start with exported fixtures instead of the Google Docs API.

Phase 1:

```text
.docx or HTML
    |
    v
Parser
    |
    v
JSON
```

No authentication, no Chrome extension, and no Google APIs during the first parser milestone.

The parser should not care where the document came from. Later inputs can feed the same parser path:

```text
Google Docs API
        |
.docx export
        |
HTML export
        |
--------v--------
     Parser
--------v--------
      JSON
```

### Evidence Card Assumptions

Documents mostly follow a consistent evidence-card structure:

- Tag or claim
- Citation
- Highlighted evidence
- Remaining article text

The highlighted section is usually the most important evidence, while the remaining article text provides supporting context. The parser should preserve both.

Card boundaries are generally identifiable, but different documents may have small formatting inconsistencies. The parser should be tolerant rather than assuming perfect formatting.

Highlight colors may carry meaning and should be preserved if possible.

### Milestone 1

Read a document.

Convert it into structured evidence cards.

Export JSON.

### Open Questions

- How should highlight colors be represented in the JSON schema?
- What is the best strategy for detecting card boundaries across slightly inconsistent documents?
- Should `.docx` or HTML be the first parser fixture format?
- How should incremental indexing detect changed cards?
