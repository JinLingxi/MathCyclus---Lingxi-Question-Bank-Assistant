"""Smoke test the parser adapter without requiring MinerU installation."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.document_parser_service import available_document_parsers, load_mineru_content_list


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mathcyclus_mineru_adapter_") as temp_dir:
        root = Path(temp_dir)
        image_path = root / "images" / "figure.png"
        image_path.parent.mkdir()
        image_path.write_bytes(b"not-a-real-image")
        content_path = root / "sample_content_list.json"
        content_path.write_text(
            json.dumps(
                [
                    {"type": "text", "page_idx": 0, "bbox": [10, 20, 100, 40], "text": "1. test"},
                    {"type": "equation", "page_idx": 0, "bbox": [10, 45, 100, 60], "latex": "x^2"},
                    {"type": "image", "page_idx": 0, "bbox": [10, 70, 100, 150], "img_path": "images/figure.png"},
                ],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = load_mineru_content_list(root)
        parsers = available_document_parsers()
        checks = {
            "pymupdf_available": any(item["name"] == "pymupdf" and item["available"] for item in parsers),
            "block_types_normalized": [item["type"] for item in result["blocks"]] == ["text", "formula", "image"],
            "page_index_normalized": all(item["page_number"] == 1 for item in result["blocks"]),
            "image_path_resolved": Path(result["blocks"][2]["source_path"]).is_file(),
        }
    for name, ok in checks.items():
        print(f"{name}={'ok' if ok else 'failed'}")
    print(f"status={'ok' if all(checks.values()) else 'failed'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
