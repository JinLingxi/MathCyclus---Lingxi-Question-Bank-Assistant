from __future__ import annotations

import argparse
import json
import re
import sqlite3
from collections import Counter
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
REPORTS_DIR = PROJECT_ROOT / "reports"
INCLUDE_GRAPHICS_PATTERN = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^{}]+)\}",
    re.MULTILINE,
)
QUESTION_ASSET_PATTERN = re.compile(
    r"\\questionasset\{(?P<alias>[^{}]+)\}",
    re.MULTILINE,
)


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def count_table(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def integrity_checks(conn: sqlite3.Connection) -> dict[str, object]:
    integrity = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
    foreign_keys = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
    return {
        "integrity_check": integrity,
        "foreign_key_errors": foreign_keys,
    }


def duplicate_paper_positions(conn: sqlite3.Connection) -> list[dict]:
    if not table_exists(conn, "paper_question"):
        return []
    rows = conn.execute(
        """
        SELECT
            p.paper_id,
            p.year,
            p.paper_name,
            p.track,
            pq.question_number,
            pq.sub_number,
            COUNT(*) AS duplicate_count
        FROM paper_question pq
        JOIN paper p ON p.paper_id = pq.paper_id
        GROUP BY p.paper_id, pq.question_number, pq.sub_number
        HAVING COUNT(*) > 1
        ORDER BY p.year, p.paper_name, CAST(pq.question_number AS INTEGER), pq.question_number
        """
    ).fetchall()
    return [dict(row) for row in rows]


def orphan_relation_counts(conn: sqlite3.Connection) -> dict[str, int]:
    checks = {
        "paper_question": """
            SELECT COUNT(*)
            FROM paper_question pq
            LEFT JOIN paper p ON p.paper_id = pq.paper_id
            LEFT JOIN question q ON q.question_id = pq.question_id
            WHERE p.paper_id IS NULL OR q.question_id IS NULL
        """,
        "question_knowledge_area": """
            SELECT COUNT(*)
            FROM question_knowledge_area qka
            LEFT JOIN question q ON q.question_id = qka.question_id
            LEFT JOIN knowledge_area ka ON ka.knowledge_area_id = qka.knowledge_area_id
            WHERE q.question_id IS NULL OR ka.knowledge_area_id IS NULL
        """,
        "question_asset": """
            SELECT COUNT(*)
            FROM question_asset qa
            LEFT JOIN question q ON q.question_id = qa.question_id
            WHERE q.question_id IS NULL
        """,
        "book_exercise_question": """
            SELECT COUNT(*)
            FROM book_exercise_question beq
            LEFT JOIN book b ON b.book_id = beq.book_id
            LEFT JOIN question q ON q.question_id = beq.question_id
            WHERE b.book_id IS NULL OR q.question_id IS NULL
        """,
        "topic_question": """
            SELECT COUNT(*)
            FROM topic_question tq
            LEFT JOIN topic t ON t.topic_id = tq.topic_id
            LEFT JOIN question q ON q.question_id = tq.question_id
            WHERE t.topic_id IS NULL OR q.question_id IS NULL
        """,
    }
    result: dict[str, int] = {}
    for table, sql in checks.items():
        if table_exists(conn, table):
            result[table] = int(conn.execute(sql).fetchone()[0])
    return result


def resolve_graphics_ref(ref: str, source_file: str) -> Path | None:
    candidates: list[Path] = []
    ref_path = Path(ref)
    if ref_path.is_absolute():
        candidates.append(ref_path)
    else:
        if source_file:
            candidates.append((PROJECT_ROOT / source_file).parent / ref)
        candidates.append(PROJECT_ROOT / ref)
        candidates.append(PROJECT_ROOT / "chapters" / ref)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def missing_graphics_refs(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    if not table_exists(conn, "question"):
        return []
    rows = conn.execute(
        """
        SELECT
            q.question_id,
            q.legacy_id,
            q.stem_tex,
            q.answer_tex,
            q.solution_tex,
            q.canonical_tex,
            l.legacy_file_path
        FROM question q
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        """
    ).fetchall()
    missing: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        tex = "\n".join(
            str(row[field] or "")
            for field in ["stem_tex", "answer_tex", "solution_tex", "canonical_tex"]
        )
        for ref in INCLUDE_GRAPHICS_PATTERN.findall(tex):
            key = (str(row["question_id"]), ref)
            if key in seen:
                continue
            seen.add(key)
            if not resolve_graphics_ref(ref, row["legacy_file_path"] or ""):
                missing.append(
                    {
                        "question_id": row["question_id"],
                        "legacy_id": row["legacy_id"],
                        "legacy_file_path": row["legacy_file_path"],
                        "ref": ref,
                    }
                )
                if len(missing) >= limit:
                    return missing
    return missing


def unresolved_questionasset_refs(conn: sqlite3.Connection, limit: int = 200) -> list[dict]:
    if not table_exists(conn, "question_asset"):
        return []
    rows = conn.execute(
        """
        SELECT
            q.question_id,
            q.stem_tex,
            q.answer_tex,
            q.solution_tex,
            q.canonical_tex
        FROM question q
        """
    ).fetchall()
    unresolved: list[dict] = []
    for row in rows:
        tex = "\n".join(str(row[field] or "") for field in ["stem_tex", "answer_tex", "solution_tex", "canonical_tex"])
        refs = QUESTION_ASSET_PATTERN.findall(tex)
        if not refs:
            continue
        assets: set[str] = set()
        for asset_row in conn.execute(
            """
            SELECT asset_id, file_path, original_file_name
            FROM question_asset
            WHERE question_id = ?
            """,
            (row["question_id"],),
        ).fetchall():
            file_path = str(asset_row["file_path"] or "")
            original_name = str(asset_row["original_file_name"] or "")
            for alias in [
                str(asset_row["asset_id"] or ""),
                Path(file_path).stem,
                Path(file_path).name,
                Path(original_name).stem,
                Path(original_name).name,
            ]:
                if alias:
                    assets.add(alias)
        for alias in refs:
            if alias not in assets:
                unresolved.append({"question_id": row["question_id"], "alias": alias})
                if len(unresolved) >= limit:
                    return unresolved
    return unresolved


def draft_status_counts(conn: sqlite3.Connection) -> dict[str, int]:
    if not table_exists(conn, "question_import_draft"):
        return {}
    rows = conn.execute(
        """
        SELECT review_status, COUNT(*)
        FROM question_import_draft
        GROUP BY review_status
        """
    ).fetchall()
    return {str(row[0]): int(row[1]) for row in rows}


def audit_database(db_path: Path) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        integrity = integrity_checks(conn)
        table_counts = {
            table: count_table(conn, table)
            for table in [
                "question",
                "paper",
                "paper_question",
                "knowledge_area",
                "question_knowledge_area",
                "question_equivalence",
                "question_asset",
                "question_revision",
                "import_batch",
                "question_import_draft",
                "book",
                "book_section",
                "book_exercise_question",
                "topic_module",
                "topic",
                "topic_question",
            ]
        }
        duplicate_positions = duplicate_paper_positions(conn)
        orphan_counts = orphan_relation_counts(conn)
        missing_graphics = missing_graphics_refs(conn)
        unresolved_assets = unresolved_questionasset_refs(conn)
        draft_counts = draft_status_counts(conn)
    finally:
        conn.close()

    blockers = []
    if integrity["integrity_check"] != "ok":
        blockers.append("SQLite integrity_check 未通过")
    if integrity["foreign_key_errors"]:
        blockers.append("存在外键错误")
    if any(value > 0 for value in orphan_counts.values()):
        blockers.append("存在失联关系记录")
    if draft_counts.get("blocked", 0):
        blockers.append("存在 blocked 草稿")
    warnings = []
    if duplicate_positions:
        warnings.append("存在同一试卷同一题号重复位置，需要人工确认")
    if missing_graphics:
        warnings.append("存在 includegraphics 缺失图片引用")
    if unresolved_assets:
        warnings.append("存在未解析 questionasset 占位符")
    if draft_counts.get("needs_review", 0):
        warnings.append("存在 needs_review 草稿")

    return {
        "database": relative_to_root(db_path),
        "table_counts": table_counts,
        "integrity": integrity,
        "orphan_relation_counts": orphan_counts,
        "duplicate_paper_positions": duplicate_positions,
        "missing_graphics_refs": missing_graphics,
        "unresolved_questionasset_refs": unresolved_assets,
        "draft_status_counts": draft_counts,
        "blockers": blockers,
        "warnings": warnings,
        "status": "blocked" if blockers else "warning" if warnings else "ok",
    }


def write_markdown(report: dict[str, object], path: Path) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    table_counts = report["table_counts"]
    table_lines = "\n".join(f"| `{key}` | {value} |" for key, value in table_counts.items())
    orphan_lines = "\n".join(
        f"| `{key}` | {value} |"
        for key, value in report["orphan_relation_counts"].items()
    ) or "| 无 | 0 |"
    duplicate_sample = "\n".join(
        f"- `{row['year']} {row['paper_name']} {row['track']} 第{row['question_number']}题`：{row['duplicate_count']} 条"
        for row in report["duplicate_paper_positions"][:30]
    ) or "无"
    missing_graphics_sample = "\n".join(
        f"- `{row['question_id']}` / 旧 ID `{row['legacy_id']}`：`{row['ref']}`"
        for row in report["missing_graphics_refs"][:30]
    ) or "无"
    asset_sample = "\n".join(
        f"- `{row['question_id']}`：`{row['alias']}`"
        for row in report["unresolved_questionasset_refs"][:30]
    ) or "无"
    blocker_text = "\n".join(f"- {item}" for item in report["blockers"]) or "无"
    warning_text = "\n".join(f"- {item}" for item in report["warnings"]) or "无"
    draft_lines = "\n".join(
        f"| `{key}` | {value} |"
        for key, value in sorted(report["draft_status_counts"].items())
    ) or "| 无 | 0 |"

    path.write_text(
        f"""# 提交前数据库安全审计报告

> 生成时间：{now}  
> 数据库：`{report['database']}`  
> 状态：`{report['status']}`  
> 审计方式：只读检查，不修改数据库和 `.tex` 文件。

## 阻断项

{blocker_text}

## 警告项

{warning_text}

## 表计数

| 表 | 数量 |
| --- | ---: |
{table_lines}

## 失联关系

| 关系表 | 数量 |
| --- | ---: |
{orphan_lines}

## 草稿状态

| review_status | 数量 |
| --- | ---: |
{draft_lines}

## 重复试卷位置样例

{duplicate_sample}

## 缺失图片引用样例

{missing_graphics_sample}

## 未解析资源占位符样例

{asset_sample}

## 判断

- `blocked` 表示不能进入正式提交。
- `warning` 表示可以继续开发，但正式导入前必须人工确认。
- `ok` 表示本脚本覆盖的基础检查没有发现问题。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="提交正式数据库前的只读安全审计。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path = db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = audit_database(db_path)
    json_path = REPORTS_DIR / f"precommit_database_audit_{args.stamp}.json"
    md_path = REPORTS_DIR / f"precommit_database_audit_{args.stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown(report, md_path)

    print(f"status={report['status']}")
    print(f"blockers={len(report['blockers'])}")
    print(f"warnings={len(report['warnings'])}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
