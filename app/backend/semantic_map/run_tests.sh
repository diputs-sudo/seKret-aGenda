#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_DIR="${TMPDIR:-/tmp}/sekret-semantic-map-tests"
mkdir -p "$BUILD_DIR"

c++ -std=c++17 -Wall -Wextra -Werror -I "$ROOT" \
  "$ROOT/semantic_map.cpp" "$ROOT/tests/semantic_map_test.cpp" \
  -o "$BUILD_DIR/semantic_map_test"

"$BUILD_DIR/semantic_map_test"
echo "semantic map tests passed"
