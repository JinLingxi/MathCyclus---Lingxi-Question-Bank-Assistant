from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_20260901_initial.sqlite3"
DEFAULT_MAPPING = PROJECT_ROOT / "db" / "seed" / "paper_name_mapping.csv"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"


def relative_to_root(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def stable_id(prefix: str, *values: object, length: int = 10) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    suffix = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}{suffix}"


def load_mapping(path: Path) -> dict[tuple[str, str, str], dict[str, str]]:
    mapping: dict[tuple[str, str, str], dict[str, str]] = {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        for row in csv.DictReader(file):
            key = (
                (row.get("source_year") or "").strip(),
                (row.get("source_series") or "").strip(),
                (row.get("source_name") or "").strip(),
            )
            mapping[key] = row
    return mapping


def fetch_papers(conn: sqlite3.Connection) -> list[dict]:
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        """
        SELECT
            p.paper_id,
            p.year,
            p.paper_series,
            p.track,
            p.paper_name,
            p.source_name,
            p.description,
            COUNT(pq.paper_question_id) AS question_count
        FROM paper p
        LEFT JOIN paper_question pq ON pq.paper_id = p.paper_id
        GROUP BY p.paper_id
        ORDER BY p.year, p.paper_series, p.paper_name
        """
    ).fetchall()
    return [dict(row) for row in rows]


def normalize_papers(
    conn: sqlite3.Connection,
    mapping: dict[tuple[str, str, str], dict[str, str]],
) -> list[dict]:
    papers = fetch_papers(conn)
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    normalized_rows: list[dict] = []

    for paper in papers:
        source_year = "" if paper["year"] is None else str(paper["year"])
        source_series = paper["paper_series"] or ""
        source_name = paper["source_name"] or paper["paper_name"] or ""
        map_row = mapping.get((source_year, source_series, source_name))
        if map_row:
            normalized_name = (map_row.get("normalized_paper_name") or source_name).strip()
            normalized_track = (map_row.get("normalized_track") or paper["track"] or "").strip()
            review_status = (map_row.get("review_status") or "pending").strip()
            note = (map_row.get("note") or "").strip()
        else:
            normalized_name = paper["paper_name"] or source_name or "未知试卷"
            normalized_track = paper["track"] or ""
            review_status = "missing_mapping"
            note = "未在映射表中找到"

        normalized_key = (
            source_year,
            source_series,
            normalized_track,
            normalized_name,
        )
        row = {
            **paper,
            "normalized_name": normalized_name,
            "normalized_track": normalized_track,
            "normalized_key": normalized_key,
            "review_status": review_status,
            "note": note,
            "canonical_paper_id": stable_id("P", *normalized_key),
        }
        grouped[normalized_key].append(row)
        normalized_rows.append(row)

    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("DELETE FROM paper")

    for normalized_key, group in sorted(grouped.items()):
        source_year, source_series, normalized_track, normalized_name = normalized_key
        canonical_id = stable_id("P", *normalized_key)
        source_names = sorted({row["source_name"] or row["paper_name"] or "" for row in group})
        descriptions = sorted({row["description"] or "" for row in group if row["description"]})
        conn.execute(
            """
            INSERT INTO paper(
                paper_id, year, paper_series, track, paper_name, source_name, description
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                canonical_id,
                int(source_year) if source_year else None,
                source_series,
                normalized_track,
                normalized_name,
                " / ".join(source_names),
                " / ".join(descriptions),
            ),
        )

        for row in group:
            conn.execute(
                "UPDATE paper_question SET paper_id = ? WHERE paper_id = ?",
                (canonical_id, row["paper_id"]),
            )

    conn.execute("PRAGMA foreign_keys = ON")
    return normalized_rows


def write_report(
    normalized_rows: list[dict],
    source_db: Path,
    output_db: Path,
    mapping_path: Path,
    report_path: Path,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    grouped: dict[tuple[str, str, str, str], list[dict]] = defaultdict(list)
    for row in normalized_rows:
        grouped[row["normalized_key"]].append(row)

    merge_groups = {key: rows for key, rows in grouped.items() if len(rows) > 1}
    pending_rows = [row for row in normalized_rows if row["review_status"] != "approved"]
    changed_rows = [
        row
        for row in normalized_rows
        if (row["paper_name"] or "") != row["normalized_name"]
        or (row["track"] or "") != row["normalized_track"]
    ]

    merge_sample = "\n".join(
        "- "
        + f"`{key[0]} / {key[1]} / {key[2]} / {key[3]}` <= "
        + "；".join(f"`{row['source_name'] or row['paper_name']}`" for row in rows)
        for key, rows in list(merge_groups.items())[:30]
    ) or "无"

    changed_sample = "\n".join(
        f"- `{row['source_name'] or row['paper_name']}`："
        f"`{row['paper_name']}` / `{row['track']}` -> "
        f"`{row['normalized_name']}` / `{row['normalized_track']}`"
        for row in changed_rows[:30]
    ) or "无"

    report_path.write_text(
        f"""# 试卷名称映射 Dry-run 报告

> 生成时间：{now}  
> 来源数据库：`{relative_to_root(source_db)}`  
> 输出数据库：`{relative_to_root(output_db)}`  
> 映射文件：`{relative_to_root(mapping_path)}`  
> 执行方式：复制预览库后应用映射，不修改原始 `.tex`，不修改原预览库。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 原始试卷记录 | {len(normalized_rows)} |
| 规范化后试卷记录 | {len(grouped)} |
| 发生合并的规范化组 | {len(merge_groups)} |
| 名称或 track 被调整 | {len(changed_rows)} |
| 仍需人工审查映射 | {len(pending_rows)} |

## 合并样例

{merge_sample}

## 名称或 Track 调整样例

{changed_sample}

## 说明

- 映射表当前默认 `review_status = pending`，因此报告中的“仍需人工审查映射”较多是正常现象。
- 当前 dry-run 已经把 `paper_question.paper_id` 指向规范化后的 `paper.paper_id`。
- 正式应用前，应先人工审查 `db/seed/paper_name_mapping.csv`。
- 不建议自动合并语义可能不同的试卷名称，例如 `全国I卷` 与 `全国卷I`。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="复制预览库并应用试卷名称映射，生成 dry-run 报告。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源 SQLite 预览库。")
    parser.add_argument("--mapping", default=str(DEFAULT_MAPPING), help="试卷名称映射 CSV。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.source_db)
    mapping_path = Path(args.mapping)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    if not mapping_path.is_absolute():
        mapping_path = PROJECT_ROOT / mapping_path

    if not source_db.exists():
        raise SystemExit(f"来源数据库不存在：{source_db}")
    if not mapping_path.exists():
        raise SystemExit(f"映射文件不存在：{mapping_path}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_db = DATA_DIR / f"mathcyclus_preview_paper_mapped_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"paper_mapping_dry_run_{args.stamp}.md"

    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)

    mapping = load_mapping(mapping_path)
    conn = sqlite3.connect(output_db)
    try:
        with conn:
            normalized_rows = normalize_papers(conn, mapping)
        orphan_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM paper_question pq
            LEFT JOIN paper p ON p.paper_id = pq.paper_id
            WHERE p.paper_id IS NULL
            """
        ).fetchone()[0]
        if orphan_count:
            raise RuntimeError(f"存在失联 paper_question：{orphan_count}")
    finally:
        conn.close()

    write_report(normalized_rows, source_db, output_db, mapping_path, report_path)
    print(f"source_papers={len(normalized_rows)}")
    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
