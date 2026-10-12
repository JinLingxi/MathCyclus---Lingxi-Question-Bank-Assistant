"""Smoke-test the unified AI data factory surface without touching the formal DB."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import fitz
from streamlit.testing.v1 import AppTest


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    with tempfile.TemporaryDirectory(prefix="mathcyclus_factory_ui_") as temp_dir:
        root = Path(temp_dir)
        jobs_root = root / "jobs"
        source_pdf = root / "factory-smoke.pdf"
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "1. Find the value of x")
            document.save(source_pdf)

        os.environ["MATHCYCLUS_FACTORY_SMOKE_ROOT"] = str(jobs_root)
        os.environ["MATHCYCLUS_FACTORY_SMOKE_SOURCE"] = str(source_pdf)
        os.environ["MATHCYCLUS_FACTORY_PROJECT_ROOT"] = str(project_root)
        script = """
import os
import sys
from pathlib import Path
sys.path.insert(0, os.environ["MATHCYCLUS_FACTORY_PROJECT_ROOT"])
import services.pdf_import_service as pdf_service

pdf_service.DEFAULT_JOBS_ROOT = Path(os.environ["MATHCYCLUS_FACTORY_SMOKE_ROOT"])
pdf_service.create_pdf_import_job(
    os.environ["MATHCYCLUS_FACTORY_SMOKE_SOURCE"],
    jobs_root=pdf_service.DEFAULT_JOBS_ROOT,
    job_id="factory_ui_smoke",
    source_type="pdf_misc",
)
from question_bank_app import render_ai_data_factory_tool
render_ai_data_factory_tool()
"""
        try:
            app = AppTest.from_string(script, default_timeout=30).run()
            if app.exception:
                print("factory_render_has_no_exception=failed")
                print([item.message for item in app.exception])
                return 1

            labels = [item.label for item in app.button]
            markdown = [str(item.value) for item in app.markdown]
            metrics = [item.label for item in app.metric]
            checks = {
                "factory_render_has_no_exception": not app.exception,
                "review_entry_visible": "打开草稿审核" in labels,
                "asset_pipeline_copy_visible": any("Asset" in item and "Pipeline" in item for item in markdown),
                "elapsed_metric_visible": "已用时" in metrics,
            }
            for name, ok in checks.items():
                print(f"{name}={'ok' if ok else 'failed'}")
            failed = [name for name, ok in checks.items() if not ok]
            print(f"status={'failed' if failed else 'ok'}")
            return 1 if failed else 0
        finally:
            os.environ.pop("MATHCYCLUS_FACTORY_SMOKE_ROOT", None)
            os.environ.pop("MATHCYCLUS_FACTORY_SMOKE_SOURCE", None)
            os.environ.pop("MATHCYCLUS_FACTORY_PROJECT_ROOT", None)


if __name__ == "__main__":
    raise SystemExit(main())
