#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DOCX_PATH="${DOCX_PATH:-data/Training Data.docx}"
DB_PATH="${DB_PATH:-var/sekret-agenda.sqlite3}"
CHROMA_PATH="${CHROMA_PATH:-var/chroma}"

usage() {
  cat <<EOF
seKret aGenda run commands

Usage:
  ./run.sh <command> [args...]

Commands:
  setup-ollama              Pull local models used by the app
  build-db                  Build SQLite from DOCX
  build-vector              Build Chroma vector index from SQLite
  rebuild                   Build SQLite, then rebuild Chroma
  search <query>            Keyword search through SQLite
  vector <query>            Vector search through Chroma with reranking
  evals                     Run retrieval evals
  cli                       Start interactive CLI
  api                       Start FastAPI backend
  test                      Run tests
  debug                     Run fixed debug pipeline

Environment:
  DOCX_PATH=$DOCX_PATH
  DB_PATH=$DB_PATH
  CHROMA_PATH=$CHROMA_PATH

Examples:
  ./run.sh rebuild
  ./run.sh vector "automation escalation"
  ./run.sh cli
EOF
}

require_query() {
  if [[ $# -eq 0 ]]; then
    echo "Missing query."
    echo
    usage
    exit 1
  fi
}

command="${1:-help}"
if [[ $# -gt 0 ]]; then
  shift
fi

case "$command" in
  setup-ollama)
    ollama pull gemma3:4b
    ollama pull nomic-embed-text
    ;;

  build-db)
    python3 scripts/build_sqlite_from_docx.py "$DOCX_PATH" --db "$DB_PATH"
    ;;

  build-vector)
    python3 scripts/build_vector_index.py --db "$DB_PATH" --chroma "$CHROMA_PATH" --reset
    ;;

  rebuild)
    "$0" build-db
    "$0" build-vector
    ;;

  search)
    require_query "$@"
    python3 scripts/query_sqlite.py "$*" --db "$DB_PATH"
    ;;

  vector)
    require_query "$@"
    python3 scripts/query_vector.py "$*" --db "$DB_PATH" --chroma "$CHROMA_PATH" --limit 15 --rerank --top 3 --compare-sqlite
    ;;

  evals)
    python3 scripts/run_retrieval_evals.py --db "$DB_PATH" --chroma "$CHROMA_PATH"
    ;;

  cli)
    python3 scripts/sekret.py --db "$DB_PATH"
    ;;

  api)
    SEKRET_DB_PATH="$DB_PATH" uvicorn backend.api.main:app --reload
    ;;

  test)
    python3 -m pytest tests
    ;;

  debug)
    python3 scripts/debug_pipeline.py --db "$DB_PATH"
    ;;

  help|-h|--help)
    usage
    ;;

  *)
    echo "Unknown command: $command"
    echo
    usage
    exit 1
    ;;
esac
