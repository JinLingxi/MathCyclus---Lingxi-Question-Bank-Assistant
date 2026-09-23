from __future__ import annotations

import sys
import tempfile
from pathlib import Path

import fitz


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.document_ai_queue_service import (
    create_or_refresh_queue,
    finish_queue_item,
    load_queue,
    next_queue_item,
    queue_summary,
    retry_failed_items,
    reset_queue_range,
    set_queue_status,
)
from services.pdf_import_service import create_pdf_import_job


def main() -> int:
    checks = {}
    with tempfile.TemporaryDirectory(prefix="mathcyclus_ai_queue_") as temp_dir:
        root = Path(temp_dir)
        pdf = root / "sample.pdf"
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "I. Choice Questions\n1. First question\n2. Second question")
            document.save(pdf)
        create_pdf_import_job(pdf, jobs_root=root / "jobs", job_id="queue_smoke", source_type="pdf_paper")
        queue = create_or_refresh_queue("queue_smoke", jobs_root=root / "jobs")
        checks["queue_created"] = queue_summary(queue)["total"] == 2
        set_queue_status("queue_smoke", "running", jobs_root=root / "jobs")
        first = next_queue_item("queue_smoke", jobs_root=root / "jobs")
        finish_queue_item("queue_smoke", first["source_item_id"], result={"stem_tex": "first"}, jobs_root=root / "jobs")
        second = next_queue_item("queue_smoke", jobs_root=root / "jobs")
        finish_queue_item("queue_smoke", second["source_item_id"], error="timeout", jobs_root=root / "jobs")
        failed = load_queue("queue_smoke", jobs_root=root / "jobs")
        checks["results_persisted"] = queue_summary(failed)["succeeded"] == 1 and queue_summary(failed)["failed"] == 1
        retried = retry_failed_items("queue_smoke", jobs_root=root / "jobs")
        checks["failed_retryable"] = queue_summary(retried)["pending"] == 1 and queue_summary(retried)["succeeded"] == 1
        refreshed = create_or_refresh_queue("queue_smoke", jobs_root=root / "jobs")
        checks["refresh_preserves_progress"] = queue_summary(refreshed)["succeeded"] == 1 and queue_summary(refreshed)["pending"] == 1
        set_queue_status("queue_smoke", "running", jobs_root=root / "jobs")
        retry = next_queue_item("queue_smoke", jobs_root=root / "jobs")
        checks["retry_attempt_incremented"] = retry.get("attempts") == 2
        recovered = create_or_refresh_queue("queue_smoke", jobs_root=root / "jobs")
        checks["interrupted_item_recovered"] = queue_summary(recovered)["running"] == 0 and queue_summary(recovered)["pending"] == 1
        reset = reset_queue_range("queue_smoke", 1, 1, jobs_root=root / "jobs")
        checks["range_reset"] = queue_summary(reset)["pending"] == 2
    for name, ok in checks.items():
        print(f"{name}={'ok' if ok else 'failed'}")
    print(f"status={'ok' if all(checks.values()) else 'failed'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
