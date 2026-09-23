from __future__ import annotations

import sqlite3
import sys
import tempfile
from contextlib import closing
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.database_service import initialize_database
from services.paper_catalog_service import add_paper_alias, add_standard_paper, match_paper, record_match_review


def main() -> int:
    smoke_root = PROJECT_ROOT / "data" / "smoke"
    smoke_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mathcyclus_paper_catalog_", dir=smoke_root) as temp_dir:
        db_path = Path(temp_dir) / "catalog.sqlite3"
        initialize_database(db_path)
        canonical = add_standard_paper(
            db_path, year=2024, paper_series="G", track="新高考", paper_name="新高考II卷"
        )
        add_paper_alias(db_path, canonical["paper_standard_id"], "2024新课标全国II卷")

        exact = match_paper(
            db_path, year="2024", paper_series="g", track="新高考", paper_name="新高考Ⅱ卷"
        )
        assert exact["status"] == "exact", exact
        assert exact["selected"]["paper_standard_id"] == canonical["paper_standard_id"], exact

        alias = match_paper(
            db_path, year=2024, paper_series="G", track="新高考", paper_name="2024 新课标全国 II 卷"
        )
        assert alias["status"] == "exact", alias
        assert alias["selected"]["match_reason"] == "exact_alias", alias

        similar = match_paper(
            db_path, year=2024, paper_series="G", track="新高考", paper_name="新高考全国II卷"
        )
        assert similar["status"] == "needs_confirmation", similar
        assert similar["candidates"], similar

        wrong_year = match_paper(
            db_path, year=2023, paper_series="G", track="新高考", paper_name="新高考II卷"
        )
        assert wrong_year["status"] == "new_paper", wrong_year

        wrong_track = match_paper(
            db_path, year=2024, paper_series="G", track="理科", paper_name="新高考II卷"
        )
        assert wrong_track["status"] in {"needs_confirmation", "new_paper"}, wrong_track

        new_name = match_paper(
            db_path, year=2026, paper_series="G", track="新高考", paper_name="未来新卷"
        )
        assert new_name["status"] == "new_paper", new_name

        review = record_match_review(
            db_path,
            similar,
            decision="accepted",
            confirmed_standard_id=canonical["paper_standard_id"],
            batch_id="BATCH_TEST",
        )
        assert review["decision"] == "accepted", review
        assert review["confirmed_standard_id"] == canonical["paper_standard_id"], review

        with closing(sqlite3.connect(db_path)) as conn:
            count = conn.execute("SELECT COUNT(*) FROM paper_match_review").fetchone()[0]
        assert count == 1, count

    print("smoke_paper_catalog_service: status=ok")
    print("writes_project_database=false")
    print("deletes_files=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
