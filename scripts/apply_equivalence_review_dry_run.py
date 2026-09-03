from __future__ import annotations

import argparse
import csv
import hashlib
import shutil
import sqlite3
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_with_knowledge.sqlite3"
DEFAULT_DECISIONS = PROJECT_ROOT / "db" / "seed" / "equivalence_review_decisions_20260902_initial.csv"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

SUPPORTED_DECISIONS = {"pending", "keep_all", "mark_equivalent", "merge_to_canonical", "ignore"}


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def stable_id(prefix: str, *values: object, length: int = 12) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def make_equivalence_id(question_id_a: str, question_id_b: str, relation_type: str) -> str:
    left, right = sorted([question_id_a, question_id_b])
    return stable_id("QE", left, right, relation_type)


def make_knowledge_area_id(name: str) -> str:
    return stable_id("KA", name, length=10)


def split_pipe_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def load_decisions(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as file:
        rows = [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(file)
        ]
    return rows


def question_exists(conn: sqlite3.Connection, question_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM question WHERE question_id = ?", (question_id,)).fetchone()
    return row is not None


def validate_row(conn: sqlite3.Connection, row: dict[str, str]) -> list[str]:
    errors: list[str] = []
    decision = row.get("decision", "")
    question_ids = split_pipe_list(row.get("question_ids", ""))
    canonical_question_id = row.get("canonical_question_id", "")

    if decision not in SUPPORTED_DECISIONS:
        errors.append(f"decision 不支持：{decision}")

    if len(question_ids) < 2:
        errors.append("question_ids 少于 2 个，无法建立关系")

    missing_ids = [question_id for question_id in question_ids if not question_exists(conn, question_id)]
    if missing_ids:
        errors.append("question_id 不存在：" + " | ".join(missing_ids))

    if decision == "merge_to_canonical":
        if not canonical_question_id:
            errors.append("merge_to_canonical 必须填写 canonical_question_id")
        elif canonical_question_id not in question_ids:
            errors.append("canonical_question_id 必须属于 question_ids")

    if decision == "mark_equivalent" and canonical_question_id and canonical_question_id not in question_ids:
        errors.append("mark_equivalent 的 canonical_question_id 必须属于 question_ids")

    return errors


def upsert_equivalence(
    conn: sqlite3.Connection,
    question_id_a: str,
    question_id_b: str,
    relation_type: str,
    review_status: str,
    confidence: float | None,
    note: str,
) -> str:
    left, right = sorted([question_id_a, question_id_b])
    equivalence_id = make_equivalence_id(left, right, relation_type)
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
        (
            equivalence_id,
            left,
            right,
            relation_type,
            confidence,
            review_status,
            note,
        ),
    )
    return equivalence_id


def update_existing_equivalences(
    conn: sqlite3.Connection,
    question_ids: list[str],
    review_status: str,
    note: str,
) -> int:
    updated = 0
    for question_id_a, question_id_b in combinations(sorted(question_ids), 2):
        row = conn.execute(
            """
            SELECT equivalence_id
            FROM question_equivalence
            WHERE (
                (question_id_a = ? AND question_id_b = ?)
                OR (question_id_a = ? AND question_id_b = ?)
            )
            """,
            (question_id_a, question_id_b, question_id_b, question_id_a),
        ).fetchone()
        if not row:
            continue
        conn.execute(
            """
            UPDATE question_equivalence
            SET review_status = ?, note = ?
            WHERE equivalence_id = ?
            """,
            (review_status, note, row[0]),
        )
        updated += 1
    return updated


def ensure_knowledge_area(conn: sqlite3.Connection, name: str) -> str:
    knowledge_area_id = make_knowledge_area_id(name)
    conn.execute(
        """
        INSERT OR IGNORE INTO knowledge_area(knowledge_area_id, name, description)
        VALUES (?, ?, ?)
        """,
        (knowledge_area_id, name, "人工同题审查 dry-run 补充"),
    )
    return knowledge_area_id


def transfer_knowledge_links(conn: sqlite3.Connection, question_ids: list[str], canonical_question_id: str) -> int:
    transferred = 0
    for question_id in question_ids:
        if question_id == canonical_question_id:
            continue
        rows = conn.execute(
            """
            SELECT knowledge_area_id, source, confidence
            FROM question_knowledge_area
            WHERE question_id = ?
            """,
            (question_id,),
        ).fetchall()
        for row in rows:
            before_changes = conn.total_changes
            conn.execute(
                """
                INSERT OR IGNORE INTO question_knowledge_area(
                    question_id, knowledge_area_id, source, confidence, is_primary
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    canonical_question_id,
                    row[0],
                    f"{row[1] or 'migration'}+equivalence_dry_run",
                    row[2],
                    0,
                ),
            )
            if conn.total_changes > before_changes:
                transferred += 1
    return transferred


def attach_manual_knowledge_areas(
    conn: sqlite3.Connection,
    canonical_question_id: str,
    knowledge_area_names: list[str],
) -> int:
    inserted = 0
    for name in knowledge_area_names:
        knowledge_area_id = ensure_knowledge_area(conn, name)
        before_changes = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO question_knowledge_area(
                question_id, knowledge_area_id, source, confidence, is_primary
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (canonical_question_id, knowledge_area_id, "manual_equivalence_review_dry_run", 1.0, 0),
        )
        if conn.total_changes > before_changes:
            inserted += 1
    return inserted


def apply_decision(conn: sqlite3.Connection, row: dict[str, str]) -> dict[str, object]:
    review_id = row.get("review_id", "")
    issue_type = row.get("issue_type", "")
    decision = row.get("decision", "")
    question_ids = split_pipe_list(row.get("question_ids", ""))
    canonical_question_id = row.get("canonical_question_id", "")
    manual_knowledge_areas = split_pipe_list(row.get("merge_into_knowledge_areas", ""))
    note = f"{review_id} {decision}: {row.get('note', '')}".strip()

    errors = validate_row(conn, row)
    if errors:
        return {
            "review_id": review_id,
            "issue_type": issue_type,
            "decision": decision,
            "status": "invalid",
            "question_ids": question_ids,
            "canonical_question_id": canonical_question_id,
            "equivalence_written": 0,
            "knowledge_links_added": 0,
            "message": "；".join(errors),
        }

    if decision == "pending":
        return {
            "review_id": review_id,
            "issue_type": issue_type,
            "decision": decision,
            "status": "skipped",
            "question_ids": question_ids,
            "canonical_question_id": canonical_question_id,
            "equivalence_written": 0,
            "knowledge_links_added": 0,
            "message": "pending 不写入预览库",
        }

    if decision == "keep_all":
        updated = update_existing_equivalences(conn, question_ids, "kept", note)
        return {
            "review_id": review_id,
            "issue_type": issue_type,
            "decision": decision,
            "status": "applied",
            "question_ids": question_ids,
            "canonical_question_id": canonical_question_id,
            "equivalence_written": updated,
            "knowledge_links_added": 0,
            "message": f"保留全部；已更新既有同题候选 {updated} 条",
        }

    if decision == "ignore":
        updated = update_existing_equivalences(conn, question_ids, "ignored", note)
        return {
            "review_id": review_id,
            "issue_type": issue_type,
            "decision": decision,
            "status": "applied",
            "question_ids": question_ids,
            "canonical_question_id": canonical_question_id,
            "equivalence_written": updated,
            "knowledge_links_added": 0,
            "message": f"忽略该问题；已更新既有同题候选 {updated} 条",
        }

    if decision == "mark_equivalent":
        relation_type = "same_stem" if issue_type == "same_stem" else "same_question"
        written = 0
        pairs = list(combinations(sorted(question_ids), 2))
        for question_id_a, question_id_b in pairs:
            upsert_equivalence(
                conn,
                question_id_a,
                question_id_b,
                relation_type,
                "approved",
                1.0,
                note,
            )
            written += 1
        return {
            "review_id": review_id,
            "issue_type": issue_type,
            "decision": decision,
            "status": "applied",
            "question_ids": question_ids,
            "canonical_question_id": canonical_question_id,
            "equivalence_written": written,
            "knowledge_links_added": 0,
            "message": f"已标记同题关系 {written} 条，不合并题目",
        }

    relation_type = "merge_candidate"
    written = 0
    for question_id in sorted(question_ids):
        if question_id == canonical_question_id:
            continue
        upsert_equivalence(
            conn,
            canonical_question_id,
            question_id,
            relation_type,
            "approved_merge",
            1.0,
            note,
        )
        written += 1

    knowledge_added = transfer_knowledge_links(conn, question_ids, canonical_question_id)
    knowledge_added += attach_manual_knowledge_areas(conn, canonical_question_id, manual_knowledge_areas)

    return {
        "review_id": review_id,
        "issue_type": issue_type,
        "decision": decision,
        "status": "applied",
        "question_ids": question_ids,
        "canonical_question_id": canonical_question_id,
        "equivalence_written": written,
        "knowledge_links_added": knowledge_added,
        "message": "已在副本中标记可合并关系，并把知识板块补到 canonical 题；未删除任何题目",
    }


def database_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        "question",
        "paper",
        "paper_question",
        "knowledge_area",
        "question_knowledge_area",
        "question_equivalence",
    ]
    return {
        table: int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
        for table in tables
    }


def write_report(
    results: list[dict[str, object]],
    before_counts: dict[str, int],
    after_counts: dict[str, int],
    source_db: Path,
    output_db: Path,
    decisions_path: Path,
    report_path: Path,
) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    decision_counts = Counter(str(row["decision"]) for row in results)
    status_counts = Counter(str(row["status"]) for row in results)
    applied_rows = [row for row in results if row["status"] == "applied"]
    invalid_rows = [row for row in results if row["status"] == "invalid"]

    decision_lines = "\n".join(
        f"| `{decision}` | {count} |"
        for decision, count in sorted(decision_counts.items())
    ) or "| 无 | 0 |"
    status_lines = "\n".join(
        f"| `{status}` | {count} |"
        for status, count in sorted(status_counts.items())
    ) or "| 无 | 0 |"
    count_lines = "\n".join(
        f"| `{table}` | {before_counts.get(table, 0)} | {after_counts.get(table, 0)} | {after_counts.get(table, 0) - before_counts.get(table, 0)} |"
        for table in before_counts
    )

    applied_text = "\n".join(
        f"- `{row['review_id']}` / `{row['decision']}`：{row['message']}"
        for row in applied_rows[:50]
    ) or "无"
    invalid_text = "\n".join(
        f"- `{row['review_id']}` / `{row['decision']}`：{row['message']}"
        for row in invalid_rows[:50]
    ) or "无"

    report_path.write_text(
        f"""# 同题关系人工决策 Dry-run 报告

> 生成时间：{now}  
> 来源数据库：`{relative_to_root(source_db)}`  
> 输出数据库：`{relative_to_root(output_db)}`  
> 决策表：`{relative_to_root(decisions_path)}`  
> 执行方式：复制预览库后应用人工决策；不删除题目，不修改原始 `.tex`。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 决策行总数 | {len(results)} |
| 已应用行 | {len(applied_rows)} |
| 无效行 | {len(invalid_rows)} |
| 写入/更新同题关系 | {sum(int(row['equivalence_written']) for row in results)} |
| 补充知识板块关系 | {sum(int(row['knowledge_links_added']) for row in results)} |

## 决策分布

| decision | 数量 |
| --- | ---: |
{decision_lines}

## 执行状态

| status | 数量 |
| --- | ---: |
{status_lines}

## 表计数变化

| 表 | 执行前 | 执行后 | 变化 |
| --- | ---: | ---: | ---: |
{count_lines}

## 已应用样例

{applied_text}

## 无效行

{invalid_text}

## 安全边界

- `pending` 行不会写入预览库。
- `merge_to_canonical` 只标记可合并关系，并补充 canonical 题的知识板块关系。
- 本脚本不会删除 `question`、`paper_question`、`question_asset` 或旧 `.tex` 文件。
- 正式合并前仍需要单独生成备份、差异报告和回滚方案。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="在数据库副本上应用同题/重复题人工决策，不改正式数据。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源 SQLite 预览库。")
    parser.add_argument("--decisions", default=str(DEFAULT_DECISIONS), help="人工决策 CSV。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.source_db)
    decisions_path = Path(args.decisions)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    if not decisions_path.is_absolute():
        decisions_path = PROJECT_ROOT / decisions_path
    source_db = source_db.resolve()
    decisions_path = decisions_path.resolve()

    if not source_db.exists():
        raise SystemExit(f"来源数据库不存在：{source_db}")
    if not decisions_path.exists():
        raise SystemExit(f"决策表不存在：{decisions_path}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_db = DATA_DIR / f"mathcyclus_preview_equivalence_review_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"equivalence_review_dry_run_{args.stamp}.md"

    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)

    decisions = load_decisions(decisions_path)
    conn = sqlite3.connect(output_db)
    try:
        before_counts = database_counts(conn)
        with conn:
            results = [apply_decision(conn, row) for row in decisions]
        after_counts = database_counts(conn)
    finally:
        conn.close()

    write_report(results, before_counts, after_counts, source_db, output_db, decisions_path, report_path)

    print(f"decisions={len(results)}")
    print(f"applied={sum(1 for row in results if row['status'] == 'applied')}")
    print(f"invalid={sum(1 for row in results if row['status'] == 'invalid')}")
    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
