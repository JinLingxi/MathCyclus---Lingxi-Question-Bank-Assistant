from __future__ import annotations

import argparse
import csv
import re
import sqlite3
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_20260901_initial.sqlite3"
DEFAULT_OUTPUT = PROJECT_ROOT / "db" / "seed" / "paper_name_mapping.csv"


def normalize_track(source_name: str) -> str:
    if "新高考" in source_name:
        return "新高考"
    if "（文）" in source_name or "文科" in source_name:
        return "文科"
    if "（理）" in source_name or "理科" in source_name:
        return "理科"
    return "综合"


def normalize_paper_name(source_name: str) -> str:
    name = (source_name or "").strip()
    name = re.sub(r"（文）$", "", name)
    name = re.sub(r"（理）$", "", name)
    name = re.sub(r"\(文\)$", "", name)
    name = re.sub(r"\(理\)$", "", name)
    name = name.replace(" ", "")
    return name or "未知试卷"


def iter_papers(db_path: Path) -> list[tuple]:
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(
            """
            SELECT
                p.year,
                p.paper_series,
                p.track,
                p.paper_name,
                p.source_name,
                COUNT(pq.paper_question_id) AS question_count
            FROM paper p
            LEFT JOIN paper_question pq ON pq.paper_id = p.paper_id
            GROUP BY p.paper_id
            ORDER BY p.year, p.paper_series, p.paper_name
            """
        ).fetchall()
    finally:
        conn.close()


def write_mapping(rows: list[tuple], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "source_year",
                "source_series",
                "source_track",
                "source_name",
                "normalized_paper_name",
                "normalized_track",
                "question_count",
                "review_status",
                "note",
            ],
        )
        writer.writeheader()
        for year, series, source_track, paper_name, source_name, question_count in rows:
            raw_name = source_name or paper_name or ""
            normalized_track = normalize_track(raw_name)
            writer.writerow(
                {
                    "source_year": year or "",
                    "source_series": series or "",
                    "source_track": source_track or "",
                    "source_name": raw_name,
                    "normalized_paper_name": normalize_paper_name(raw_name),
                    "normalized_track": normalized_track,
                    "question_count": question_count,
                    "review_status": "pending",
                    "note": "",
                }
            )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从预览数据库生成试卷名称映射草案。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT), help="输出 CSV 路径。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = PROJECT_ROOT / output_path

    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    rows = iter_papers(db_path)
    write_mapping(rows, output_path)
    print(f"papers={len(rows)}")
    print(f"output={output_path.relative_to(PROJECT_ROOT).as_posix()}")


if __name__ == "__main__":
    main()
