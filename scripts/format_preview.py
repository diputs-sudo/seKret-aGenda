#!/usr/bin/env python3
"""Preview Secret Agenda Evidence Format Language parsing."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.format_lang import parse_text


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Preview deterministic evidence-format parsing before ingestion."
    )
    parser.add_argument("input", type=Path, help="Plain-text evidence input")
    parser.add_argument("grammar", type=Path, help="Secret Agenda format grammar")
    parser.add_argument("--json", action="store_true", help="Print JSON output")
    parser.add_argument("--limit", type=int, default=5, help="Number of cards to preview")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    preview = parse_text(
        args.input.read_text(encoding="utf-8"),
        args.grammar.read_text(encoding="utf-8"),
    )
    payload = preview.to_dict()

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    summary = payload["summary"]
    print("Format Test")
    print("=" * 40)
    print(f"Detected cards: {summary['detected_cards']}")
    print(f"High confidence: {summary['high_confidence']}")
    print(f"Warnings: {summary['warnings']}")
    print(f"Failed: {summary['failed']}")

    print("\nFields")
    print("-" * 40)
    detected = max(summary["detected_cards"], 1)
    for name, count in sorted(summary["fields"].items()):
        print(f"[{name}] {count}/{detected}")

    diagnostics = payload["diagnostics"]
    if diagnostics:
        print("\nDiagnostics")
        print("-" * 40)
        for diagnostic in diagnostics:
            location = ""
            if diagnostic.get("block_index") is not None:
                location = f" block={diagnostic['block_index']}"
            confidence = ""
            if diagnostic.get("confidence") is not None:
                confidence = f" confidence={diagnostic['confidence']}"
            print(
                f"{diagnostic['severity'].upper()} {diagnostic['code']}: "
                f"{diagnostic['message']}{location}{confidence}"
            )

    print("\nPreview")
    print("-" * 40)
    for index, card in enumerate(payload["cards"][: args.limit], start=1):
        print(f"\nCARD {index}")
        print(f"Confidence: {card['overall_confidence']:.3f}")
        for name, value in card["fields"].items():
            if name == "content":
                print("Content:")
                print(value)
            else:
                print(f"{name}: {value}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
