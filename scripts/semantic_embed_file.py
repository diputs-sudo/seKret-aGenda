#!/usr/bin/env python3
"""Batch-embed the same blank-line chunks consumed by the C++ prototype."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--backend", choices=["feature-hash", "ollama"], required=True)
    parser.add_argument("--model", default="nomic-embed-text")
    args = parser.parse_args()
    text = args.input.read_text()
    chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
    process = subprocess.Popen(
        [sys.executable, str(Path(__file__).with_name("semantic_ai_worker.py")), "--backend", args.backend, "--model", args.model],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
    )
    assert process.stdin and process.stdout
    process.stdin.write(json.dumps({"op": "embed_batch", "texts": chunks, "dimensions": 256}) + "\n")
    process.stdin.close()
    response = json.loads(process.stdout.readline())
    process.wait()
    if response.get("workerError"):
        raise RuntimeError(response["workerError"])
    args.output.write_text("\n".join(" ".join(str(value) for value in vector) for vector in response["embeddings"]) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, RuntimeError, json.JSONDecodeError) as error:
        print(f"semantic_embed_file: {error}", file=sys.stderr)
        raise SystemExit(1)
