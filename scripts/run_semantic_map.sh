#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${TMPDIR:-/tmp}/sekret-semantic-map"
mkdir -p "$BUILD_DIR"

c++ -std=c++17 -Wall -Wextra -Werror \
  -I "$ROOT/app/backend/semantic_map" \
  "$ROOT/app/backend/semantic_map/semantic_map.cpp" \
  "$ROOT/app/backend/semantic_map/main.cpp" \
  -o "$BUILD_DIR/semantic_map"

if [[ $# -lt 1 ]]; then
  echo "usage: scripts/run_semantic_map.sh <text-file|docx-file|-> [--json]" >&2
  exit 2
fi

INPUT="$1"
shift
BACKEND="feature-hash"
if [[ "${1:-}" == "--embedding" ]]; then
  BACKEND="${2:-}"
  if [[ "$BACKEND" != "feature-hash" && "$BACKEND" != "ollama" ]]; then
    echo "embedding backend must be feature-hash or ollama" >&2
    exit 2
  fi
  shift 2
fi

if [[ "$BACKEND" == "ollama" ]]; then
  if [[ "$INPUT" == "-" ]]; then
    echo "--embedding ollama requires a text or DOCX path, not stdin" >&2
    exit 2
  fi
  TEXT_FILE="$(mktemp)"
  EMBEDDING_FILE="$(mktemp)"
  trap 'rm -f "$TEXT_FILE" "$EMBEDDING_FILE"' EXIT
  if [[ "$INPUT" == *.docx ]]; then
    python3 "$ROOT/scripts/extract_docx_text.py" "$INPUT" > "$TEXT_FILE"
  else
    cp "$INPUT" "$TEXT_FILE"
  fi
  python3 "$ROOT/scripts/semantic_embed_file.py" "$TEXT_FILE" "$EMBEDDING_FILE" --backend ollama
  exec "$BUILD_DIR/semantic_map" "$TEXT_FILE" --embeddings-file "$EMBEDDING_FILE" "$@"
fi

if [[ "$INPUT" == *.docx ]]; then
  python3 "$ROOT/scripts/extract_docx_text.py" "$INPUT" \
    | "$BUILD_DIR/semantic_map" - "$@"
else
  exec "$BUILD_DIR/semantic_map" "$INPUT" "$@"
fi
