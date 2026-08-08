# Roadmap

This is the canonical build order for seKret aGenda / ARGUS-DEBATE.

The rule: do not polish later layers until earlier layers are trustworthy. In a RAG debate assistant, retrieval quality is the foundation.

## Status Key

- `done`: Working implementation exists and has tests.
- `in progress`: Working slice exists, but quality or integration is not final.
- `next`: Current focus.
- `later`: Not started yet.

## 1. Parser / DebateIR

Status: `done`

Goal:

```text
DOCX -> DebateIR
```

Current implementation:

- DOCX parser reads debate evidence structure.
- Heading styles identify sections and card tags.
- Citations, bodies, and highlights are preserved.
- Highlight colors are extracted from Word XML.

Next quality work:

- Improve parser tolerance across more uploaded fixtures.
- Preserve font size and richer formatting if it becomes useful for parsing.

## 2. SQLite Ground Truth

Status: `done`

Goal:

```text
DebateIR -> SQLite
```

SQLite is the source of truth for:

- documents
- sections
- evidence cards
- citations
- highlights
- metadata

The vector DB is disposable. SQLite is not.

## 3. Embeddings + Chroma

Status: `in progress`

Goal:

```text
SQLite cards -> embedding text -> nomic-embed-text -> Chroma
```

Current implementation:

- Uses `nomic-embed-text` through Ollama.
- Uses Chroma collection `card_fast_index`.
- Embeds:

```text
section
tag
highlights
```

Current commands:

```bash
python3 scripts/build_vector_index.py --reset
python3 scripts/query_vector.py "automation escalation" --limit 15 --rerank --top 3
```

Acceptance tests:

- `AI cautious` finds `Tucker 20 / AI is risk-averse`.
- `automation escalation` finds `Cox 21`, `Goldfarb 22`, and `Tucker 20`.
- `quantum encryption` finds `Hunt 26`.

## 4. Retrieval Quality Tests

Status: `next`

Goal:

Create a repeatable retrieval eval set before plugging vector search deeper into generation.

Test queries:

```text
AI cautious
automation escalation
quantum encryption
capitalism
housing supply
Tucker
Cox 21
```

Each test should define expected cards and unacceptable cards.

Example:

```text
Query: automation escalation
Expected: Cox 21, Goldfarb 22, Tucker 20
Reject: Shapiro 26
```

## 5. Response Modes

Status: `in progress`

Modes:

- Search
- Explain
- Draft Rebuttal
- Summary
- Final Focus

Current implementation:

- Search mode exists in the CLI.
- Explain, draft, and summarize prompt modes exist.

Next work:

- Add Final Focus mode.
- Make modes produce structured response objects before prose.

## 6. Prompt Builder

Status: `in progress`

Goal:

```text
query + selected evidence + mode -> prompt
```

Current implementation:

- Prompt builder supports explain, draft, and summarize.
- Draft mode uses debate voice.

Next work:

- Build prompts from a structured argument object, not raw card lists.
- Add PF-specific templates for rebuttal, summary, and final focus.

## 7. Local LLM Generation

Status: `in progress`

Goal:

```text
retrieval -> prompt -> local model -> answer
```

Current implementation:

- Ollama adapter exists.
- Default generation model is `gemma3:4b`.
- CLI streams generation output.

Next work:

- Use vector retrieval + relevance reranking before generation.
- Keep `[BACKFILE-SOURCED]` and `[ANALYSIS ONLY]` distinct.

## 8. Interactive CLI / TUI

Status: `in progress`

Goal:

Fast testing loop before browser UI.

Current implementation:

```bash
python3 scripts/sekret.py
```

Supported commands:

```text
/mode search
/mode explain
/mode draft
/mode summarize
/help
```

Next work:

- Add `/mode final-focus`.
- Add a TUI card viewer if plain CLI becomes too cramped.

## 9. FastAPI Endpoints

Status: `in progress`

Current endpoints:

- `GET /status`
- `POST /search`
- `POST /generate`

Next work:

- Switch `/search` to vector retrieval once retrieval evals are stable.
- Add source-status fields.
- Add mode-aware `/generate`.

## 10. Extension Flow Pane

Status: `later`

Goal:

Browser extension pane for live flow input.

Default input mode:

```text
Flow directly in extension pane.
```

Google Docs watching should be optional because it adds latency and auth complexity.

## 11. Insertion Into Docs

Status: `later`

Goal:

One-click formatted insertion at cursor.

Formatting target:

- Heading 1: contention / hat
- Heading 2: opponent block
- Heading 3 or bold: tag / numbered response
- Body: citation and warrant text

## 12. Judge Mode Polish

Status: `later`

Goal:

Manual lay/tech toggle.

Lay mode:

- conversational
- numbered
- zero jargon

Tech mode:

- line-by-line
- card precise
- flow shorthand

## 13. Minimal Round UI

Status: `later`

Goal:

Compact, low-distraction round interface.

Use this framing instead of camouflage or hiding:

- focus mode
- compact sidebar
- low-glare theme
- clean clipboard
- quick collapse

Do not build deceptive camouflage as a core product feature.

