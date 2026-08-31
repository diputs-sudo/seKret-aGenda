# Debate Semantic Argument Prototype

This experiment tests whether messy debate documents can become a useful,
searchable semantic argument map without relying on headings, highlights,
underlining, citation formats, or other author conventions.

The prototype lives in `app/backend/semantic_map/` and is intentionally separate
from the existing evidence-card pipeline.

## Run it

```bash
app/backend/semantic_map/run_tests.sh
c++ -std=c++17 -I app/backend/semantic_map \
  app/backend/semantic_map/semantic_map.cpp \
  app/backend/semantic_map/main.cpp \
  -o /tmp/semantic_map
/tmp/semantic_map path/to/messy-case.txt
/tmp/semantic_map path/to/messy-case.txt --json
# stdin is also supported
cat path/to/messy-case.txt | /tmp/semantic_map - --json
```

There is also a convenience runner:

```bash
scripts/run_semantic_map.sh examples/semantic-map/messy-case.txt
scripts/run_semantic_map.sh examples/semantic-map/messy-case.txt --json
scripts/run_semantic_map.sh examples/semantic-map/messy-case.txt --embedding ollama --json
```

To test the current SQLite corpus at card granularity:

```bash
sqlite3 -noheader var/sekret-agenda.sqlite3 \
  'select replace(body, char(10), " ") || char(10) || char(10) from evidence_cards where trim(body) <> "";' \
  | scripts/run_semantic_map.sh - --json
```

Input can be plain text or DOCX. For DOCX, the small Python boundary extracts
paragraph text from `word/document.xml`; headings, highlights, underlining, and
other formatting are preserved only as input signals in the source document and
are not treated as semantic rules. Blank-line-separated paragraphs become
initial semantic chunks. Each result retains the extracted source span, original
text, summary, citations, topics, and model metadata.

Run the existing cases directly:

```bash
scripts/run_semantic_map.sh data/ex-tech-AFF-APR.docx --json > /tmp/aff-map.json
scripts/run_semantic_map.sh data/ex-tech-NEG-APR.docx --json > /tmp/neg-map.json
scripts/run_semantic_map.sh data/ex-tech-AFF-APR.docx --embedding ollama --json > /tmp/aff-semantic-map.json
```

The current implementation uses deterministic feature-hash vectors so it can be
run offline. `scripts/semantic_ai_worker.py` defines a line-oriented JSON
boundary for replacing summarization, embeddings, and relationship classification
with Python models. Use `--backend ollama` to batch-generate real vectors via
Ollama and feed them back into the same C++ clustering pipeline. The worker does
not silently fall back if Ollama is unavailable.

The output intentionally keeps clusters and graph edges separate:

- clusters describe which arguments are about the same idea;
- edges describe how arguments interact;
- arguments that do not clear the cluster similarity threshold create a new
  cluster rather than being forced into an existing one.

This is an evaluation prototype, not a production parser or ANN index.

## V2 evaluation

Run the deterministic baseline:

```bash
scripts/eval_semantic_map.sh --backend feature-hash --representation raw
```

With Ollama running and models available:

```bash
ollama pull nomic-embed-text
SEMANTIC_EMBEDDING_MODEL=nomic-embed-text \
SEMANTIC_RELATION_MODEL=gemma3:4b \
SEMANTIC_NORMALIZATION_MODEL=gemma3:4b \
  scripts/eval_semantic_map.sh --backend ollama --representation raw
SEMANTIC_EMBEDDING_MODEL=nomic-embed-text \
SEMANTIC_RELATION_MODEL=gemma3:4b \
SEMANTIC_NORMALIZATION_MODEL=gemma3:4b \
  scripts/eval_semantic_map.sh --backend ollama --representation normalized
```

The roles are intentionally separate: the embedding model is sent only to
`/api/embed`; normalization and pairwise relationships are sent only to
`/api/chat` using their respective configured chat models.

Useful investigation modes:

```bash
scripts/eval_semantic_map.sh --backend ollama --representation normalized --errors
# Trust Mode: classify every unordered argument pair as the correctness reference
scripts/eval_semantic_map.sh --backend ollama --representation normalized --candidate-mode exhaustive --errors
scripts/eval_semantic_map.sh --backend ollama --representation normalized --retrieval-details
scripts/eval_semantic_map.sh --backend ollama --representation normalized --show-normalizations
scripts/eval_semantic_map.sh --backend ollama --representation normalized --verbose
scripts/eval_semantic_map.sh --backend ollama --compare-representations
scripts/eval_semantic_map.sh --backend ollama --representation normalized --inspect A23
```

The default output is terminal-readable. Add `--json` only for automation.
The report preserves original text for pairwise relationship classification;
normalized text is only the retrieval representation.

`--inspect ARGUMENT_ID` limits output to one argument's normalization, ranked
candidates, and labeled relationship tests. Use `--top-k-display 3` to further
limit candidate output. The evaluator reports stage timings, AI/cache counts,
and raw model content with a parse status in verbose/failure views. Use
`--no-cache` for a clean run; unchanged successful normalizations, embedding
batches, and relationship calls are cached by model, prompt version, and input.

## V3.1 relationship contract

The relation model must choose exactly one label:

```text
SAME_ARGUMENT, SUPPORTS, ATTACKS, RELATED, UNRELATED
```

`SUPPORTS` and `ATTACKS` are directed through explicit
`source_argument` and `target_argument` IDs. `SAME_ARGUMENT`, `RELATED`, and
`UNRELATED` are undirected. If a model supplies endpoints for an undirected
label, the evaluator discards them while canonicalizing the prediction rather
than counting a correct semantic class as a schema error.

Reports separate class accuracy, directional accuracy, full-edge accuracy,
schema validity, and parse success. The normalizer is instructed to retain
jurisdiction, actors, polarity, directionality, qualifiers, and compound
clauses. Inspection output flags transformations that may need human fidelity
review; original text remains authoritative for relationship inference.
