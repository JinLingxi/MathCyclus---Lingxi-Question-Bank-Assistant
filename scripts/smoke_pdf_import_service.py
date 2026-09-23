"""Smoke test the private PyMuPDF import-job pipeline."""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

import fitz
from PIL import Image


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORMAL_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.pdf_import_service import (
    bulk_mark_pdf_candidates_ready,
    create_pdf_import_job,
    list_pdf_import_jobs,
    load_pdf_import_job,
    refresh_pdf_import_source_metadata,
    split_pages_into_question_drafts,
    update_pdf_question_candidate,
)


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def main() -> int:
    checks: list[dict[str, Any]] = []
    database_hash_before = sha256(FORMAL_DB)
    with tempfile.TemporaryDirectory(prefix="mathcyclus_pdf_import_") as temp_dir:
        temp_root = Path(temp_dir)
        source_pdf = temp_root / "sample.pdf"
        image_buffer = io.BytesIO()
        Image.new("RGB", (80, 60), color=(240, 80, 80)).save(image_buffer, format="PNG")
        with fitz.open() as document:
            first_page = document.new_page()
            first_page.insert_text(
                (72, 72),
                "Exam title\n1. Fill in your name\n2. Read the instructions\n3. Return the paper\nI. Choice Questions\n1. Given x^2 + 1",
            )
            first_page.insert_image(fitz.Rect(100, 180, 180, 240), stream=image_buffer.getvalue())
            second_page = document.new_page()
            second_page.insert_text((72, 72), "continued condition\n2. Find y = 2x")
            second_page.draw_line((110, 130), (180, 130), color=(0, 0, 0), width=2)
            second_page.draw_line((145, 95), (145, 165), color=(0, 0, 0), width=2)
            second_page.draw_line((115, 155), (175, 105), color=(0, 0, 0), width=2)
            document.save(source_pdf)

        result = create_pdf_import_job(
            source_pdf,
            jobs_root=temp_root / "jobs",
            job_id="pdf_smoke_job",
            source_type="pdf_paper",
            source_metadata={"paper_name": "Smoke Paper", "year": 2026},
        )
        job_dir = Path(result["job_dir"])
        refresh_result = refresh_pdf_import_source_metadata(
            "pdf_smoke_job",
            {"source_name": "Smoke Paper Revised", "year": 2026, "paper_series": "G", "track": ""},
            db_path=FORMAL_DB,
            jobs_root=temp_root / "jobs",
        )
        refreshed_draft = json.loads((job_dir / "draft_payload.json").read_text(encoding="utf-8"))
        checks = [
            check("source_metadata_refresh", refreshed_draft.get("source_metadata", {}).get("source_name") == "Smoke Paper Revised", refresh_result),
            check("candidate_source_refresh", all(
                item.get("extra", {}).get("detected_source") == "Smoke Paper Revised"
                for item in refreshed_draft.get("questions", [])
            )),
        ]
        manifest = json.loads((job_dir / "job_manifest.json").read_text(encoding="utf-8"))
        draft = json.loads((job_dir / "draft_payload.json").read_text(encoding="utf-8"))

        checks.extend(
            [
                check("job_status_drafted", result["status"] == "drafted", result),
                check("source_pdf_copied", (job_dir / "source.pdf").is_file()),
                check("page_images_rendered", all((job_dir / f"pages/page_{number:03d}.png").is_file() for number in (1, 2))),
                check("manifest_page_count", manifest.get("document", {}).get("page_count") == 2, manifest),
                check("draft_text_extracted", "x^2 + 1" in draft["pages"][0]["raw_text"] and "y = 2x" in draft["pages"][1]["raw_text"]),
                check("question_candidates_created", len(draft.get("questions") or []) == 2, draft.get("questions")),
                check(
                    "question_crops_created",
                    all(
                        question.get("extra", {}).get("question_crop_paths")
                        and all((job_dir / path).is_file() for path in question["extra"]["question_crop_paths"])
                        for question in draft.get("questions") or []
                    ),
                    [question.get("extra", {}).get("question_crop_paths") for question in draft.get("questions") or []],
                ),
                check(
                    "embedded_image_extracted",
                    len([item for item in draft["pages"][0].get("image_candidates") or [] if item.get("type") == "image"]) == 1
                    and (job_dir / draft["pages"][0]["image_candidates"][0]["source_path"]).is_file(),
                    draft["pages"][0].get("image_candidates"),
                ),
                check(
                    "vector_region_extracted",
                    any(
                        item.get("type") == "vector_region" and (job_dir / item["source_path"]).is_file()
                        for item in draft["pages"][1].get("image_candidates") or []
                    ),
                    draft["pages"][1].get("image_candidates"),
                ),
                check(
                    "image_suggested_for_question",
                    draft["pages"][0]["image_candidates"][0].get("suggested_question_number") == "1"
                    and bool(draft["pages"][0]["image_candidates"][0].get("bbox")),
                    draft["pages"][0]["image_candidates"][0],
                ),
                check(
                    "image_bound_to_question_draft",
                    len(draft["questions"][0].get("assets") or []) == 1
                    and draft["questions"][0]["assets"][0].get("caption") == "figure_01",
                    draft["questions"][0].get("assets"),
                ),
                check(
                    "image_marker_created",
                    draft["questions"][0]["extra"].get("image_markers") == ["[IMAGE: q1_figure_01]"]
                    and "[IMAGE: q1_figure_01]" in draft["questions"][0]["extra"].get("stem_source_with_image_markers", ""),
                    draft["questions"][0]["extra"],
                ),
                check(
                    "cross_page_question_merged",
                    draft["questions"][0]["extra"]["page_start"] == 1
                    and draft["questions"][0]["extra"]["page_end"] == 2
                    and "continued condition" in draft["questions"][0]["stem_tex"],
                    draft["questions"][0],
                ),
                check(
                    "preamble_preserved",
                    "Exam title" in draft.get("unassigned_blocks", [])[0]["raw_text"]
                    and "Fill in your name" in draft.get("unassigned_blocks", [])[0]["raw_text"],
                ),
                check("draft_requires_review", draft.get("status") == "needs_review" and all(item["review_status"] == "needs_review" for item in draft["questions"])),
                check("import_report_created", (job_dir / "import_report.md").is_file()),
                check("formal_database_writes_disabled", result["writes_formal_database"] is False and manifest["writes_formal_database"] is False),
            ]
        )
        listed_jobs = list_pdf_import_jobs(temp_root / "jobs")
        loaded_job = load_pdf_import_job("pdf_smoke_job", temp_root / "jobs")
        checks.append(check("job_listed", len(listed_jobs) == 1 and listed_jobs[0]["job_id"] == "pdf_smoke_job", listed_jobs))
        checks.append(check("job_loaded", loaded_job["draft_payload"]["job_id"] == "pdf_smoke_job"))
        first_candidate_id = draft["questions"][0]["source_item_id"]
        try:
            update_pdf_question_candidate(
                "pdf_smoke_job",
                first_candidate_id,
                {"review_status": "ready"},
                jobs_root=temp_root / "jobs",
            )
        except ValueError:
            incomplete_ready_blocked = True
        else:
            incomplete_ready_blocked = False
        checks.append(check("incomplete_ready_blocked", incomplete_ready_blocked))
        update_result = update_pdf_question_candidate(
            "pdf_smoke_job",
            first_candidate_id,
            {
                "question_type_id": 4,
                "stem_tex": "Given x^2 + 1 and the continued condition.",
                "answer_tex": "2",
                "solution_tex": "Substitute the given value.",
                "tags": ["function"],
                "review_status": "ready",
            },
            jobs_root=temp_root / "jobs",
        )
        updated_job = load_pdf_import_job("pdf_smoke_job", temp_root / "jobs")
        checks.append(check("candidate_update_saved", update_result["review_status"] == "ready", update_result))
        checks.append(
            check(
                "review_status_count_updated",
                updated_job["manifest"]["draft_summary"]["review_status_counts"] == {"needs_review": 1, "ready": 1},
                updated_job["manifest"]["draft_summary"],
            )
        )
        bulk_result = bulk_mark_pdf_candidates_ready("pdf_smoke_job", jobs_root=temp_root / "jobs")
        checks.append(
            check(
                "bulk_ready_keeps_incomplete_for_review",
                bulk_result["ready_count"] == 1 and bulk_result["skipped_count"] == 1,
                bulk_result,
            )
        )
        try:
            create_pdf_import_job(source_pdf, jobs_root=temp_root / "jobs", job_id="../outside")
        except ValueError:
            invalid_job_id_blocked = True
        else:
            invalid_job_id_blocked = False
        checks.append(check("invalid_job_id_blocked", invalid_job_id_blocked))
        fallback_drafts, fallback_unassigned = split_pages_into_question_drafts(
            [{"page_number": 1, "raw_text": "Unnumbered exercise text"}],
            source_type="pdf_misc",
        )
        checks.append(
            check(
                "unnumbered_page_fallback",
                len(fallback_drafts) == 1
                and fallback_drafts[0]["extra"]["splitter"] == "page_fallback_v1"
                and fallback_unassigned == [],
                fallback_drafts,
            )
        )

    database_hash_after = sha256(FORMAL_DB)
    checks.append(check("formal_database_unchanged", database_hash_after == database_hash_before, {"before": database_hash_before, "after": database_hash_after}))
    failed = [item for item in checks if not item["ok"]]
    print(json.dumps({"status": "failed" if failed else "ok", "checks": checks}, ensure_ascii=False, indent=2))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
