from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_with_knowledge.sqlite3"
DEFAULT_CORRECTIONS = PROJECT_ROOT / "db" / "seed" / "paper_question_corrections_20260902_final_review.csv"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
SUPPORTED_ACTIONS = {"move_relation", "drop_relation"}

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.precommit_database_audit import duplicate_paper_positions


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def resolve_project_path(path: str | Path) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = PROJECT_ROOT / target
    return target.resolve()


def ensure_inside_project(path: Path) -> None:
    try:
        path.resolve().relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"路径必须位于项目目录内：{path}") from exc


def stable_id(prefix: str, *values: object, length: int = 10) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def stable_relation_id(prefix: str, *values: object, length: int = 12) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def split_pipe_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").replace("，", "|").replace("、", "|").split("|") if item.strip()]


def read_corrections(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"题位修正 CSV 不存在：{path}")
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(file)
        ]


def table_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def database_counts(conn: sqlite3.Connection) -> dict[str, int]:
    return {
        "question": table_count(conn, "question"),
        "paper": table_count(conn, "paper"),
        "paper_question": table_count(conn, "paper_question"),
        "question_equivalence": table_count(conn, "question_equivalence"),
    }


def paper_question_row(conn: sqlite3.Connection, paper_question_id: str) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT
            pq.paper_question_id,
            pq.paper_id,
            pq.question_id,
            pq.question_number,
            pq.sub_number,
            pq.display_order,
            p.year,
            p.paper_series,
            p.track,
            p.paper_name
        FROM paper_question pq
        JOIN paper p ON p.paper_id = pq.paper_id
        WHERE pq.paper_question_id = ?
        """,
        (paper_question_id,),
    ).fetchone()


def question_exists(conn: sqlite3.Connection, question_id: str) -> bool:
    return conn.execute("SELECT 1 FROM question WHERE question_id = ?", (question_id,)).fetchone() is not None


def target_paper_id(row: dict[str, str]) -> str:
    return stable_id(
        "P",
        row.get("target_year", ""),
        row.get("target_paper_series", ""),
        row.get("target_track", ""),
        row.get("target_paper_name", ""),
    )


def ensure_target_paper(conn: sqlite3.Connection, row: dict[str, str]) -> str:
    required = [
        "target_year",
        "target_paper_series",
        "target_track",
        "target_paper_name",
    ]
    missing = [field for field in required if not row.get(field)]
    if missing:
        raise ValueError("move_relation 缺少目标字段：" + " | ".join(missing))

    year = int(row["target_year"])
    paper_series = row["target_paper_series"]
    track = row["target_track"]
    paper_name = row["target_paper_name"]
    existing = conn.execute(
        """
        SELECT paper_id
        FROM paper
        WHERE year = ? AND paper_series = ? AND track = ? AND paper_name = ?
        """,
        (year, paper_series, track, paper_name),
    ).fetchone()
    if existing:
        return str(existing[0])

    paper_id = target_paper_id(row)
    conn.execute(
        """
        INSERT INTO paper(
            paper_id, year, paper_series, track, paper_name, source_name, description
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_id,
            year,
            paper_series,
            track,
            paper_name,
            row.get("target_source_name") or paper_name,
            "paper_question_corrections dry-run created target paper",
        ),
    )
    return paper_id


def upsert_equivalence(conn: sqlite3.Connection, question_id_a: str, question_id_b: str, note: str) -> str:
    left, right = sorted([question_id_a, question_id_b])
    equivalence_id = stable_relation_id("QE", left, right, "same_question")
    conn.execute(
        """
        INSERT INTO question_equivalence(
            equivalence_id, question_id_a, question_id_b, relation_type,
            confidence, review_status, note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(question_id_a, question_id_b, relation_type)
        DO UPDATE SET
            confidence = excluded.confidence,
            review_status = excluded.review_status,
            note = excluded.note
        """,
        (equivalence_id, left, right, "same_question", 1.0, "approved", note),
    )
    return equivalence_id


def attach_equivalence_notes(conn: sqlite3.Connection, row: dict[str, str]) -> int:
    question_id = row.get("question_id", "")
    equivalent_ids = split_pipe_list(row.get("equivalent_question_ids", ""))
    if not question_id or not equivalent_ids:
        return 0
    written = 0
    for equivalent_id in equivalent_ids:
        if equivalent_id == question_id:
            continue
        if not question_exists(conn, equivalent_id):
            raise ValueError(f"equivalent_question_id 不存在：{equivalent_id}")
        upsert_equivalence(
            conn,
            question_id,
            equivalent_id,
            f"{row.get('correction_id')} paper-question correction: {row.get('rationale', '')}",
        )
        written += 1
    return written


def apply_one(conn: sqlite3.Connection, row: dict[str, str]) -> dict[str, object]:
    correction_id = row.get("correction_id", "")
    action = row.get("action", "")
    review_status = row.get("review_status", "")
    paper_question_id = row.get("paper_question_id", "")
    question_id = row.get("question_id", "")

    result = {
        "correction_id": correction_id,
        "action": action,
        "review_status": review_status,
        "paper_question_id": paper_question_id,
        "question_id": question_id,
        "status": "skipped",
        "message": "",
        "equivalence_written": 0,
    }
    if review_status != "approved":
        result["message"] = "review_status 不是 approved，不应用"
        return result
    if action not in SUPPORTED_ACTIONS:
        result["status"] = "invalid"
        result["message"] = "action 不支持"
        return result
    current = paper_question_row(conn, paper_question_id)
    if not current:
        result["status"] = "invalid"
        result["message"] = "paper_question_id 不存在"
        return result
    if str(current["question_id"]) != question_id:
        result["status"] = "invalid"
        result["message"] = f"question_id 不匹配：当前为 {current['question_id']}"
        return result

    try:
        equivalence_written = attach_equivalence_notes(conn, row)
        if action == "drop_relation":
            conn.execute("DELETE FROM paper_question WHERE paper_question_id = ?", (paper_question_id,))
            result["status"] = "applied"
            result["message"] = "已在副本中删除 paper_question 关系；题目本体保留"
            result["equivalence_written"] = equivalence_written
            return result

        paper_id = ensure_target_paper(conn, row)
        target_question_number = row.get("target_question_number", "")
        if not target_question_number:
            raise ValueError("move_relation 缺少 target_question_number")
        target_sub_number = row.get("target_sub_number", "")
        target_display_order = (
            int(row["target_display_order"])
            if row.get("target_display_order")
            else int(current["display_order"] or 0)
        )
        conn.execute(
            """
            UPDATE paper_question
            SET
                paper_id = ?,
                question_number = ?,
                sub_number = ?,
                display_order = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE paper_question_id = ?
            """,
            (
                paper_id,
                target_question_number,
                target_sub_number,
                target_display_order,
                paper_question_id,
            ),
        )
        result["status"] = "applied"
        result["message"] = f"已在副本中移动到 paper_id={paper_id} 第 {target_question_number} 题"
        result["equivalence_written"] = equivalence_written
        return result
    except Exception as exc:
        result["status"] = "invalid"
        result["message"] = str(exc)
        return result


def compact_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "无"
    return "，".join(f"`{key or '空'}`={value}" for key, value in sorted(counts.items()))


def markdown_count_delta(before: dict[str, int], after: dict[str, int]) -> str:
    return "\n".join(
        f"| `{table}` | {before.get(table, 0)} | {after.get(table, 0)} | {after.get(table, 0) - before.get(table, 0)} |"
        for table in before
    )


def markdown_results(results: list[dict[str, object]], status: str) -> str:
    selected = [row for row in results if row["status"] == status]
    if not selected:
        return "无"
    return "\n".join(
        f"- `{row['correction_id']}` / `{row['action']}` / `{row['paper_question_id']}`：{row['message']}"
        for row in selected
    )


def write_report(report: dict[str, Any], md_path: Path, json_path: Path) -> None:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    status_counts = Counter(str(row["status"]) for row in report["results"])
    action_counts = Counter(str(row["action"]) for row in report["results"])
    md_path.write_text(
        f"""# 试卷题位修正 Dry-run 报告

> 生成时间：{report['created_at']}  
> 来源数据库：`{report['source_db']}`  
> 输出数据库：`{report['output_db']}`  
> 修正表：`{report['corrections_csv']}`  
> 执行方式：复制预览库后只在副本中修正 `paper_question`；不修改正式库、不修改 `.tex`。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 修正行 | {len(report['results'])} |
| applied | {status_counts.get('applied', 0)} |
| skipped | {status_counts.get('skipped', 0)} |
| invalid | {status_counts.get('invalid', 0)} |
| 执行前重复题位 | {report['duplicate_positions_before']} |
| 执行后重复题位 | {report['duplicate_positions_after']} |
| 写入/更新同题关系 | {sum(int(row.get('equivalence_written') or 0) for row in report['results'])} |

- action 分布：{compact_counts(dict(action_counts))}

## 表计数变化

| 表 | 执行前 | 执行后 | 变化 |
| --- | ---: | ---: | ---: |
{markdown_count_delta(report['before_counts'], report['after_counts'])}

## 已应用

{markdown_results(report['results'], 'applied')}

## 无效项

{markdown_results(report['results'], 'invalid')}

## 跳过项

{markdown_results(report['results'], 'skipped')}

## 设计边界

- `drop_relation` 只删除 `paper_question` 纸面关系，不删除 `question` 本体。
- `move_relation` 只修正题目与试卷/题号的关系，不改旧 `.tex`。
- `equivalent_question_ids` 只写入同题关系，便于未来人工合并。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="在数据库副本上应用试卷题位修正；不改正式库。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源 SQLite 预览库。")
    parser.add_argument("--corrections", default=str(DEFAULT_CORRECTIONS), help="题位修正 CSV。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = resolve_project_path(args.source_db)
    corrections_path = resolve_project_path(args.corrections)
    ensure_inside_project(source_db)
    ensure_inside_project(corrections_path)
    if not source_db.exists():
        raise SystemExit(f"来源数据库不存在：{source_db}")
    if not corrections_path.exists():
        raise SystemExit(f"题位修正 CSV 不存在：{corrections_path}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_db = DATA_DIR / f"mathcyclus_preview_paper_corrected_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"paper_question_corrections_dry_run_{args.stamp}.md"
    json_path = REPORTS_DIR / f"paper_question_corrections_dry_run_{args.stamp}.json"
    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)

    corrections = read_corrections(corrections_path)
    conn = sqlite3.connect(output_db)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        before_counts = database_counts(conn)
        duplicate_positions_before = len(duplicate_paper_positions(conn))
        with conn:
            results = [apply_one(conn, row) for row in corrections]
        after_counts = database_counts(conn)
        duplicate_positions_after = len(duplicate_paper_positions(conn))
    finally:
        conn.close()

    status_counts = Counter(str(row["status"]) for row in results)
    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_db": relative_to_root(source_db),
        "output_db": relative_to_root(output_db),
        "corrections_csv": relative_to_root(corrections_path),
        "before_counts": before_counts,
        "after_counts": after_counts,
        "duplicate_positions_before": duplicate_positions_before,
        "duplicate_positions_after": duplicate_positions_after,
        "results": results,
        "status_counts": dict(sorted(status_counts.items())),
    }
    write_report(report, report_path, json_path)

    print(f"rows={len(results)}")
    print(f"applied={status_counts.get('applied', 0)}")
    print(f"skipped={status_counts.get('skipped', 0)}")
    print(f"invalid={status_counts.get('invalid', 0)}")
    print(f"duplicate_positions_before={duplicate_positions_before}")
    print(f"duplicate_positions_after={duplicate_positions_after}")
    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
