#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${TMPDIR:-/tmp}/sekret-native-pipeline"
BIN="$BUILD_DIR/sekret-native-pipeline"
SOURCE_DIR="$ROOT/app/backend/hybrid"

sources=(
  "$SOURCE_DIR/native_cli.cpp"
  "$SOURCE_DIR/native_pipeline.cpp"
  "$SOURCE_DIR/hybrid.cpp"
  "$SOURCE_DIR/relevance.cpp"
  "$SOURCE_DIR/mechanism.cpp"
  "$SOURCE_DIR/query_intent.cpp"
  "$SOURCE_DIR/sqlite_store.cpp"
  "$SOURCE_DIR/ollama_embedder.cpp"
  "$SOURCE_DIR/vector_store.cpp"
  "$SOURCE_DIR/fusion.cpp"
  "$SOURCE_DIR/candidate_assessment.cpp"
  "$SOURCE_DIR/reranker.cpp"
  "$SOURCE_DIR/argument_builder.cpp"
)

needs_build=0
if [[ ! -x "$BIN" ]]; then
  needs_build=1
else
  for source in "${sources[@]}"; do
    if [[ "$source" -nt "$BIN" ]]; then
      needs_build=1
      break
    fi
  done
fi

if [[ "$needs_build" == 1 ]]; then
  mkdir -p "$BUILD_DIR"
  c++ \
    -std=c++17 \
    -Wall -Wextra -Werror \
    -I "$SOURCE_DIR" \
    $(pkg-config --cflags minizip libxml-2.0) \
    "${sources[@]}" \
    -lsqlite3 \
    $(pkg-config --libs minizip libxml-2.0) \
    -o "$BIN"
fi

cd "$ROOT"
exec "$BIN" "$@"
