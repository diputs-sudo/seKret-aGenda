#!/usr/bin/env python3
"""Extract readable paragraph text from a DOCX without imposing debate formatting rules."""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from zipfile import ZipFile

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = f"{{{W_NS}}}"


def extract(path: Path) -> list[str]:
    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))

    paragraphs: list[str] = []
    for paragraph in root.findall(f".//{W}body/{W}p"):
        parts: list[str] = []
        for node in paragraph.iter():
            if node.tag == f"{W}t":
                parts.append(node.text or "")
            elif node.tag == f"{W}tab":
                parts.append("\t")
            elif node.tag in {f"{W}br", f"{W}cr"}:
                parts.append("\n")
        text = "".join(parts).strip()
        if text:
            paragraphs.append(text)
    return paragraphs


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("docx", type=Path)
    args = parser.parse_args()
    try:
        sys.stdout.write("\n\n".join(extract(args.docx)))
        sys.stdout.write("\n")
    except (OSError, KeyError, ET.ParseError, ValueError) as error:
        print(f"extract_docx_text: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
