#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT"

DOCX_PATH="${DOCX_PATH:-data/Training Data.docx}"
DB_PATH="${DB_PATH:-var/sekret-agenda.sqlite3}"
CHROMA_PATH="${CHROMA_PATH:-var/chroma}"
OUR_SIDE="${OUR_SIDE:-unknown}"
OPPONENT_SIDE="${OPPONENT_SIDE:-unknown}"
RESOLUTION="${RESOLUTION:-}"

usage() {
  cat <<EOF
seKret aGenda run commands

Usage:
  ./run.sh <command> [args...]

Commands:
  setup-ollama              Pull local models used by the app
  build-db                  Build SQLite from DOCX
  build-sides --us <docx> --opponent <docx>
                            Build SQLite from our/opponent DOCX files
  build-vector              Build Chroma vector index from SQLite
  build-native-vector       Build native desktop vector cache in SQLite
  rebuild                   Build SQLite, then rebuild Chroma
  search <query>            Keyword search through SQLite
  vector <query>            Vector search through Chroma with reranking
  hybrid <query>            Hybrid search through fast/deep vectors + SQLite
  hybrid --concept-debug <query>
                            Hybrid search with concept diagnostics
  side [--no-vector] [--debug-candidates] <query>
                            Perspective-aware two-lane debate retrieval
  format-preview <input> <grammar>
                            Preview evidence DSL parsing
  evals                     Run retrieval evals
  cli                       Start interactive CLI
  api                       Start FastAPI backend
  test                      Run tests
  debug                     Run fixed debug pipeline

Environment:
  DOCX_PATH=$DOCX_PATH
  DB_PATH=$DB_PATH
  CHROMA_PATH=$CHROMA_PATH
  OUR_SIDE=$OUR_SIDE
  OPPONENT_SIDE=$OPPONENT_SIDE
  RESOLUTION=$RESOLUTION
  SEKRET_OLLAMA_NUM_GPU=${SEKRET_OLLAMA_NUM_GPU:-}
  SEKRET_OLLAMA_MAIN_GPU=${SEKRET_OLLAMA_MAIN_GPU:-}

Examples:
  ./run.sh rebuild
  OUR_SIDE=negative OPPONENT_SIDE=affirmative ./run.sh build-sides --us data/ex-tech-NEG-APR.docx --opponent data/ex-tech-AFF-APR.docx
  ./run.sh vector "automation escalation"
  ./run.sh build-native-vector
  ./run.sh hybrid "AI sports betting"
  ./run.sh hybrid --concept-debug "Opponent says AI escalates because of automation."
  ./run.sh side "opponent says AI sports betting increases addiction"
  ./run.sh side --no-vector --debug-candidates "opponent says AI sports betting increases addiction"
  ./run.sh side --debug-candidates --target-novel 8 --max-depth 120 --max-active-probes 3 "opponent says AI sports betting increases addiction"
  SEKRET_OLLAMA_NUM_GPU=999 ./run.sh side --debug-candidates "opponent says AI sports betting increases addiction"
  OUR_SIDE=negative OPPONENT_SIDE=affirmative ./run.sh side "opponent says AI sports betting increases addiction"
  ./run.sh format-preview data/opponent.txt docs/opponent-format.sa
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
    python3 scripts/build_sqlite_from_docx.py \
      "$DOCX_PATH" \
      --db "$DB_PATH"
    ;;

  build-sides)
    python3 scripts/build_two_sided_db.py \
      "$@" \
      --db "$DB_PATH" \
      --our-side "$OUR_SIDE" \
      --opponent-side "$OPPONENT_SIDE"
    ;;

  build-vector)
    python3 scripts/build_vector_index.py \
      --db "$DB_PATH" \
      --chroma "$CHROMA_PATH" \
      --reset
    ;;

  build-native-vector)
    python3 scripts/build_native_vector_cache.py \
      --db "$DB_PATH" \
      --reset
    ;;

  rebuild)
    "$0" build-db
    "$0" build-vector
    "$0" build-native-vector
    ;;

  search)
    require_query "$@"
    python3 scripts/query_sqlite.py \
      "$*" \
      --db "$DB_PATH"
    ;;

  vector)
    require_query "$@"
    python3 scripts/query_vector.py \
      "$*" \
      --db "$DB_PATH" \
      --chroma "$CHROMA_PATH" \
      --limit 15 \
      --rerank \
      --top 3 \
      --compare-sqlite
    ;;

  hybrid)
    hybrid_flags=()

    if [[ "${1:-}" == "--concept-debug" ]]; then
      hybrid_flags+=(--concept-debug)
      shift
    fi

    require_query "$@"

    cmd=(
      python3
      scripts/query_hybrid.py
      "$*"
      --db "$DB_PATH"
      --chroma "$CHROMA_PATH"
      --limit 10
      --debug
    )

    if ((${#hybrid_flags[@]})); then
      cmd+=("${hybrid_flags[@]}")
    fi

    "${cmd[@]}"
    ;;

  side)
    side_flags=()
    query_parts=()
    while [[ $# -gt 0 ]]; do
      case "$1" in
        --no-vector|--debug-candidates)
          side_flags+=("$1")
          shift
          ;;
        --target-novel|--max-depth|--max-active-probes|--limit|--candidate-limit|--model)
          if [[ $# -lt 2 ]]; then
            echo "Missing value for $1"
            exit 1
          fi
          side_flags+=("$1" "$2")
          shift 2
          ;;
        *)
          query_parts+=("$1")
          shift
          ;;
      esac
    done
    require_query "${query_parts[@]}"
    python3 scripts/query_side.py \
      "${query_parts[*]}" \
      --db "$DB_PATH" \
      --chroma "$CHROMA_PATH" \
      --our-side "$OUR_SIDE" \
      --opponent-side "$OPPONENT_SIDE" \
      --resolution "$RESOLUTION" \
      "${side_flags[@]}"
    ;;

  format-preview)
    if [[ $# -lt 2 ]]; then
      echo "Usage: ./run.sh format-preview <input.txt> <grammar.sa> [--json] [--limit N]"
      exit 1
    fi
    python3 scripts/format_preview.py "$@"
    ;;

  evals)
    python3 scripts/run_retrieval_evals.py \
      --db "$DB_PATH" \
      --chroma "$CHROMA_PATH"
    ;;

  cli)
    python3 scripts/sekret.py \
      --db "$DB_PATH"
    ;;

  api)
    SEKRET_DB_PATH="$DB_PATH" \
      uvicorn backend.api.main:app --reload
    ;;

  test)
    python3 -m pytest tests
    ;;

  debug)
    python3 scripts/debug_pipeline.py \
      --db "$DB_PATH"
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
