"""Smoke test the document import entry surface and PDF service isolation."""

from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import fitz
from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORMAL_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": bool(ok), "detail": detail}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def main() -> int:
    checks: list[dict[str, Any]] = []
    database_hash_before = sha256(FORMAL_DB)
    with tempfile.TemporaryDirectory(prefix="mathcyclus_pdf_ui_") as temp_dir:
        temp_root = Path(temp_dir)
        source_pdf = temp_root / "ui-smoke.pdf"
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "1. Find the value of x")
            document.save(source_pdf)
        os.environ["MATHCYCLUS_PDF_UI_SMOKE_ROOT"] = str(temp_root / "jobs")
        os.environ["MATHCYCLUS_PDF_UI_SMOKE_SOURCE"] = str(source_pdf)
        script = """
import os
from pathlib import Path
import services.pdf_import_service as pdf_service

pdf_service.DEFAULT_JOBS_ROOT = Path(os.environ["MATHCYCLUS_PDF_UI_SMOKE_ROOT"])
if not pdf_service.list_pdf_import_jobs(pdf_service.DEFAULT_JOBS_ROOT):
    pdf_service.create_pdf_import_job(
        os.environ["MATHCYCLUS_PDF_UI_SMOKE_SOURCE"],
        jobs_root=pdf_service.DEFAULT_JOBS_ROOT,
        job_id="pdf_ui_smoke",
        source_type="pdf_paper",
    )
from question_bank_app import render_sqlite_manual_draft_entry
render_sqlite_manual_draft_entry()
"""
        app = AppTest.from_string(script, default_timeout=30).run()
        checks.append(check("initial_render_has_no_exception", not app.exception, [item.message for item in app.exception]))
        mode_buttons = {item.label: item for item in app.button}
        checks.append(
            check(
                "three_entry_modes_visible",
                all(label in mode_buttons for label in ["批量试题录入", "同卷试题录入", "同书试题录入"]),
                sorted(mode_buttons),
            )
        )
        checks.append(check("single_entry_mode_removed", "单题录入" not in mode_buttons))
        mode_button = mode_buttons.get("同卷试题录入")
        if mode_button is not None:
            mode_button.click()
            app.run(timeout=30)
            checks.append(
                check(
                    "same_paper_review_workspace_has_no_exception",
                    not app.exception,
                    [item.message for item in app.exception],
                )
            )
            restore_button = next((item for item in app.button if item.label == "恢复"), None)
            checks.append(check("recent_document_restore_visible", restore_button is not None))
            if restore_button is not None:
                restore_button.click()
                app.run(timeout=30)
                checks.append(check("restored_document_has_no_exception", not app.exception, [item.message for item in app.exception]))
                button_labels = [item.label for item in app.button]
                queue_detail = {
                    "buttons": button_labels,
                    "warnings": [item.value for item in app.warning],
                    "batch_text": [item.value[:80] for item in app.text_area if item.label == "批量 TeX 内容"],
                }
                checks.append(
                    check(
                        "page_ai_status_visible",
                        any("PDF 页面识别" in str(item.value) for item in app.markdown),
                        queue_detail,
                    )
                )
                checks.append(
                    check(
                        "failed_retry_available_when_needed",
                        "按页重试失败题" in button_labels
                        or not any("失败" in str(item.value) for item in app.warning),
                        queue_detail,
                    )
                )
                checks.append(check("per_question_topic_multiselect_visible", "知识板块" in [item.label for item in app.multiselect]))
                process_mode = next((item for item in app.radio if item.label == "处理范围"), None)
                checks.append(check("per_question_range_removed", process_mode is None))
        checks.extend(
            [
                check(
                    "same_paper_source_fields_visible",
                    all(
                        label in [item.label for item in app.text_input]
                        for label in ["年份 / 册次", "试卷 / 来源名称"]
                    ),
                ),
                check(
                    "same_paper_tex_editor_visible",
                    "批量 TeX 内容" in [item.label for item in app.text_area],
                ),
            ]
        )
    os.environ.pop("MATHCYCLUS_PDF_UI_SMOKE_ROOT", None)
    os.environ.pop("MATHCYCLUS_PDF_UI_SMOKE_SOURCE", None)
    database_hash_after = sha256(FORMAL_DB)
    checks.append(check("formal_database_unchanged", database_hash_after == database_hash_before))
    failed = [item for item in checks if not item["ok"]]
    for item in checks:
        print(f"{item['name']}={'ok' if item['ok'] else 'failed'}")
        if not item["ok"] and item["detail"]:
            print(f"detail={item['detail']}")
    print(f"status={'failed' if failed else 'ok'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
