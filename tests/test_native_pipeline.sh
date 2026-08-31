#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB="${TMPDIR:-/tmp}/sekret-native-pipeline-test.sqlite3"

rm -f "$DB"
"$ROOT/scripts/native_pipeline.sh" import-docx "$ROOT/data/Training_Data.docx" --db "$DB" > /tmp/sekret-native-import.out

grep -q '^Sections: [1-9]' /tmp/sekret-native-import.out
grep -q '^Cards: [1-9]' /tmp/sekret-native-import.out
sqlite3 "$DB" 'SELECT count(*) FROM evidence_cards;' | grep -Eq '^[1-9][0-9]*$'
