"""Extract DOCX paragraphs and native formulas into a review-only JSON file."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.word_formula_service import read_docx_formula_paragraphs


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.resolve() == args.source.resolve():
        parser.error("输出文件不能覆盖原始 Word 文档")
    result = read_docx_formula_paragraphs(args.source)
    # Exclusive creation protects existing reports and original material.
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(f"paragraphs={len(result['paragraphs'])} equations={result['equation_count']} diagnostics={len(result['diagnostics'])}")


if __name__ == "__main__":
    main()
