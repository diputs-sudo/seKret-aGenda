#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${TMPDIR:-/tmp}/sekret-hybrid-tests"
mkdir -p "$BUILD_DIR"

sources=(
  "$ROOT/hybrid.cpp"
)

for optional_source in \
  "$ROOT/relevance.cpp" \
  "$ROOT/mechanism.cpp" \
  "$ROOT/query_intent.cpp" \
  "$ROOT/sqlite_store.cpp" \
  "$ROOT/ollama_embedder.cpp" \
  "$ROOT/fusion.cpp" \
  "$ROOT/candidate_assessment.cpp" \
  "$ROOT/reranker.cpp" \
  "$ROOT/argument_builder.cpp"
do
  if [[ -f "$optional_source" ]]; then
    sources+=("$optional_source")
  fi
done

c++ \
  -std=c++17 \
  -Wall \
  -Wextra \
  -Werror \
  -I "$ROOT" \
  "${sources[@]}" \
  "$ROOT/tests/hybrid_backend_smoke.cpp" \
  -lsqlite3 \
  -o "$BUILD_DIR/hybrid_backend_smoke"

"$BUILD_DIR/hybrid_backend_smoke"
