"""Smoke test AI recovery for pages without heuristic question numbers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.document_ai_queue_service import load_queue, queue_summary
from services.pdf_import_service import create_pdf_import_job, load_pdf_import_job


def _page_tex(number: str) -> str:
    return f"""---{number}.tex---
\\begin{{problem}}{{2026}}{{G}}{{Smoke Paper}}{{{number}}}{{函数}}
求 $x+1=2$。
\\end{{problem}}
\\begin{{answer}}1\\end{{answer}}
\\begin{{solutions}}移项得 $x=1$。\\end{{solutions}}
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="pdf_unassigned_ai_smoke_") as temp_dir:
        root = Path(temp_dir)
        pdf = root / "sample.pdf"
        with fitz.open() as document:
            first = document.new_page()
            first.insert_text((72, 72), "Exam instructions without a question number")
            second = document.new_page()
            second.insert_text((72, 72), "1. Existing numbered question")
            document.save(pdf)

        job = create_pdf_import_job(
            pdf,
            jobs_root=root / "jobs",
            job_id="unassigned_ai_smoke",
            source_type="pdf_paper",
            source_metadata={"source_name": "Smoke Paper", "year": 2026},
        )
        jobs_root = root / "jobs"
        calls = {1: 0, 2: 0}

        def fake_recognizer(image_path, *, page_number=1, question_numbers=None, timeout=240):
            calls[page_number] += 1
            if page_number == 1 and calls[page_number] <= 3:
                return {"error": "timeout"}
            return {
                "tex": _page_tex("1"),
                "page_number": page_number,
                "model_name": "smoke-model",
                "prompt_file": "ocr_prompt.txt",
                "prompt_sha256": "smoke-prompt",
                "recognizer_version": "page_v1",
            }

        from question_bank_app import _sqlite_refine_document_pages

        with patch("services.ai_service.recognize_document_page_tex", side_effect=fake_recognizer):
            first_result = _sqlite_refine_document_pages("unassigned_ai_smoke", jobs_root)
            first_payload = load_pdf_import_job("unassigned_ai_smoke", jobs_root)["draft_payload"]
            first_queue = load_queue("unassigned_ai_smoke", jobs_root=jobs_root)
            assert [item.get("status") for item in first_queue.get("items") or []] == ["pending", "failed"], first_queue
            failed_ids = {
                str(item.get("source_item_id") or "")
                for item in first_queue.get("items") or []
                if item.get("status") == "failed"
            }
            assert first_result["failed"] == 1, first_result
            assert len(first_payload.get("questions") or []) == 1, first_payload.get("questions")
            assert len(failed_ids) == 1, first_queue

            retry_result = _sqlite_refine_document_pages(
                "unassigned_ai_smoke",
                jobs_root,
                only_source_item_ids=failed_ids,
            )
            retry_payload = load_pdf_import_job("unassigned_ai_smoke", jobs_root)["draft_payload"]
            retry_queue = load_queue("unassigned_ai_smoke", jobs_root=jobs_root)
            assert [item.get("status") for item in retry_queue.get("items") or []] == ["pending", "succeeded"], retry_queue
            assert retry_result["failed"] == 0 and retry_result["succeeded"] == 1, retry_result
            assert len(retry_payload.get("questions") or []) == 2, retry_payload.get("questions")
            generated = [
                item
                for item in retry_payload["questions"]
                if (item.get("extra") or {}).get("ai_generated_from_page") == 1
            ]
            assert len(generated) == 1, generated
            assert generated[0]["extra"]["source_type"] == "pdf_paper", generated[0]
            assert generated[0]["extra"]["source_kind"] == "试卷", generated[0]
            assert queue_summary(retry_queue)["failed"] == 0, retry_queue

            resume_result = _sqlite_refine_document_pages("unassigned_ai_smoke", jobs_root)
            resumed_payload = load_pdf_import_job("unassigned_ai_smoke", jobs_root)["draft_payload"]
            assert resume_result["pages"] == 1 and len(resumed_payload["questions"]) == 2, resume_result
            before_count = len(resumed_payload["questions"])
            repeat_result = _sqlite_refine_document_pages("unassigned_ai_smoke", jobs_root)
            repeat_payload = load_pdf_import_job("unassigned_ai_smoke", jobs_root)["draft_payload"]
            assert repeat_result["pages"] == 0, {
                "result": repeat_result,
                "queue": load_queue("unassigned_ai_smoke", jobs_root=jobs_root),
                "questions": repeat_payload["questions"],
            }
            assert len(repeat_payload["questions"]) == before_count, repeat_payload["questions"]

    print("pdf_unassigned_ai_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
