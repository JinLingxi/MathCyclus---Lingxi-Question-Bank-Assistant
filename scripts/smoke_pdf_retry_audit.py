"""Verify isolated PDF commit failures, retries, and audit events."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

import fitz

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.database_service import readonly_database_connection
from services.pdf_import_service import (
    commit_pdf_import_candidates,
    create_pdf_import_job,
    load_pdf_import_job,
    retry_failed_pdf_import_candidates,
    update_pdf_question_candidate,
)


def main() -> int:
    source_db = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
    with tempfile.TemporaryDirectory(prefix="pdf_retry_smoke_") as temp_dir:
        root = Path(temp_dir)
        pdf = root / "sample.pdf"
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "I. Questions\n1. x+1=2\n2. x+2=3")
            document.save(pdf)
        db_path = root / source_db.name
        shutil.copy2(source_db, db_path)
        jobs_root = root / "jobs"
        create_pdf_import_job(pdf, jobs_root=jobs_root, job_id="retry_job", source_type="pdf_paper")
        payload = load_pdf_import_job("retry_job", jobs_root)["draft_payload"]
        ids = [item["source_item_id"] for item in payload["questions"]]
        update_pdf_question_candidate(
            "retry_job",
            ids[0],
            {"question_type_id": 4, "stem_tex": "x+1=2", "answer_tex": "1", "solution_tex": "solve", "review_status": "ready"},
            jobs_root=jobs_root,
        )
        payload = load_pdf_import_job("retry_job", jobs_root)["draft_payload"]
        for item in payload["questions"]:
            if item["source_item_id"] == ids[1]:
                item["stem_tex"] = ""
                item["review_status"] = "ready"
                item["validation"] = {"status": "ready", "errors": [], "warnings": []}
        (jobs_root / "retry_job" / "draft_payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        first = commit_pdf_import_candidates("retry_job", ids, db_path=db_path, jobs_root=jobs_root)
        assert len(first["committed"]) == 1 and len(first["failed"]) == 1, first
        question_ids = [first["committed"][0]["question_id"]]
        failed_id = first["failed"][0]["source_item_id"]
        payload = load_pdf_import_job("retry_job", jobs_root)["draft_payload"]
        for item in payload["questions"]:
            if item["source_item_id"] == failed_id:
                item.update({"stem_tex": "x+2=3", "answer_tex": "1", "solution_tex": "solve", "review_status": "ready"})
        (jobs_root / "retry_job" / "draft_payload.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        second = retry_failed_pdf_import_candidates("retry_job", db_path=db_path, jobs_root=jobs_root)
        assert len(second["committed"]) == 1 and not second["failed"], second
        question_ids.append(second["committed"][0]["question_id"])
        third = retry_failed_pdf_import_candidates("retry_job", db_path=db_path, jobs_root=jobs_root)
        assert not third["committed"] and not third["failed"] and not third["skipped"], third
        duplicate_attempt = commit_pdf_import_candidates("retry_job", ids, db_path=db_path, jobs_root=jobs_root)
        assert not duplicate_attempt["committed"] and len(duplicate_attempt["skipped"]) == 2, duplicate_attempt
        final = load_pdf_import_job("retry_job", jobs_root)["draft_payload"]
        actions = [event["action"] for event in final.get("audit_events", [])]
        with readonly_database_connection(str(db_path)) as connection:
            placeholders = ",".join("?" for _ in question_ids)
            committed_count = connection.execute(
                f"SELECT COUNT(*) FROM question WHERE question_id IN ({placeholders})", question_ids
            ).fetchone()[0]
        assert committed_count == 2, committed_count
        assert "retry_started" in actions and "retry_succeeded" in actions and "commit_skipped" in actions
    print("pdf_retry_audit_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
