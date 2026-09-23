from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
BACKUP_ROOT = PROJECT_ROOT / ".backups" / "confirmed_cleanup_decisions"
REPORTS_DIR = PROJECT_ROOT / "reports"

WEAK_DUPLICATE_DECISIONS = [
    {
        "source_question_id": "Q000132",
        "target_question_id": "Q000362",
        "decision": "delete_source_transfer_knowledge",
        "note": "2016 四川卷（理）第 9 题弱副本；保留有答案解析的导数题卡，补充函数知识点",
    },
    {
        "source_question_id": "Q000150",
        "target_question_id": "Q000377",
        "decision": "delete_source_transfer_knowledge",
        "note": "2021 新高考I卷第 7 题弱副本；保留有完整选项的导数题卡，补充函数知识点",
    },
    {
        "source_question_id": "Q000509",
        "target_question_id": "Q000434",
        "decision": "delete_source_transfer_knowledge",
        "note": "2021 新高考I卷第 16 题弱副本；保留排列组合题卡，补充数列知识点",
    },
    {
        "source_question_id": "Q000508",
        "target_question_id": "Q000506",
        "decision": "merge_answer_solution_and_relation",
        "note": "2021 新高考II卷第 12 题：保留来源正确的 Q000506，合并 Q000508 的答案解析与试卷关系",
    },
]

QUESTION_NUMBER_FIXES = [
    {
        "question_id": "Q000157",
        "target_question_number": "18",
        "note": "当前数据库关系为 2024 上海卷第 18 题；修正旧路径和 TeX 头部，避免误写为第 21 题",
    }
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def resolve_db_path(path: str | Path) -> Path:
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path.resolve()


def ensure_inside_project(path: Path) -> None:
    try:
        path.resolve().relative_to(PROJECT_ROOT.resolve())
    except ValueError as exc:
        raise ValueError(f"路径不在项目目录内，拒绝处理：{path}") from exc


def connect_database(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def copy_sqlite_database(source_db: Path, backup_db: Path) -> None:
    backup_db.parent.mkdir(parents=True, exist_ok=True)
    source_conn = sqlite3.connect(source_db)
    backup_conn = sqlite3.connect(backup_db)
    try:
        source_conn.backup(backup_conn)
    finally:
        backup_conn.close()
        source_conn.close()


def stable_id(prefix: str, *values: object, length: int = 12) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def question_row(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone()
    if row is None:
        raise ValueError(f"题目不存在：{question_id}")
    return dict(row)


def legacy_row(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM legacy_question_map WHERE question_id = ?", (question_id,)).fetchone()
    if row is None:
        raise ValueError(f"题目缺少 legacy_question_map：{question_id}")
    return dict(row)


def legacy_file_path(conn: sqlite3.Connection, question_id: str) -> Path:
    row = legacy_row(conn, question_id)
    path = PROJECT_ROOT / str(row["legacy_file_path"])
    ensure_inside_project(path)
    return path


def file_hash_text(text: str) -> str:
    return hashlib.sha1((text or "").encode("utf-8")).hexdigest()[:16]


def move_legacy_file_to_quarantine(path: Path, quarantine_root: Path) -> dict[str, Any]:
    ensure_inside_project(path)
    source_relative = relative_to_root(path)
    if not path.exists():
        return {"source": source_relative, "status": "missing", "quarantine_path": ""}
    target = quarantine_root / path.relative_to(PROJECT_ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f"{target.stem}_{datetime.now().strftime('%H%M%S')}{target.suffix}")
    shutil.move(str(path), str(target))
    return {"source": source_relative, "status": "moved", "quarantine_path": relative_to_root(target)}


def transfer_knowledge_links(conn: sqlite3.Connection, source_question_id: str, target_question_id: str) -> list[dict[str, Any]]:
    transferred: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT * FROM question_knowledge_area WHERE question_id = ?",
        (source_question_id,),
    ).fetchall()
    for row in rows:
        data = dict(row)
        before_changes = conn.total_changes
        conn.execute(
            """
            INSERT OR IGNORE INTO question_knowledge_area(
                question_id, knowledge_area_id, source, confidence, is_primary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                target_question_id,
                data["knowledge_area_id"],
                "manual_cleanup_transfer",
                data.get("confidence"),
                0,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        transferred.append(
            {
                "knowledge_area_id": data["knowledge_area_id"],
                "inserted": conn.total_changes > before_changes,
            }
        )
    return transferred


def replace_or_append_env(tex: str, env_name: str, body: str) -> str:
    content = tex or ""
    replacement = f"\\begin{{{env_name}}}\n{(body or '').strip()}\n\\end{{{env_name}}}"
    pattern = re.compile(
        rf"\\begin\{{{re.escape(env_name)}\}}[\s\S]*?\\end\{{{re.escape(env_name)}\}}",
        re.MULTILINE,
    )
    if pattern.search(content):
        return pattern.sub(lambda _match: replacement, content, count=1)
    return content.rstrip() + "\n\n" + replacement + "\n"


def normalize_line_endings(tex: str) -> str:
    return (tex or "").replace("\r\r\n", "\n").replace("\r\n", "\n").replace("\r", "\n")


def rewrite_problem_number(tex: str, target_number: str) -> str:
    pattern = re.compile(
        r"(\\begin\{problem\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{)([^{}]*)(\}\{[^{}]*\})",
        re.MULTILINE,
    )
    if pattern.search(tex or ""):
        return pattern.sub(lambda match: f"{match.group(1)}{target_number}{match.group(3)}", tex, count=1)
    return tex


def insert_revision(
    conn: sqlite3.Connection,
    question_id: str,
    *,
    changed_fields: list[str],
    before: dict[str, Any],
    after: dict[str, Any],
    note: str,
) -> str:
    revision_id = stable_id("QR", question_id, datetime.now().isoformat(), note, length=14)
    conn.execute(
        """
        INSERT INTO question_revision(
            revision_id, question_id, change_source, changed_fields_json,
            before_json, after_json, operator, note, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            revision_id,
            question_id,
            "manual_data_cleanup",
            json.dumps(changed_fields, ensure_ascii=False, separators=(",", ":")),
            json.dumps(before, ensure_ascii=False, separators=(",", ":")),
            json.dumps(after, ensure_ascii=False, separators=(",", ":")),
            "maintenance",
            note,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    return revision_id


def transfer_paper_relations(conn: sqlite3.Connection, source_question_id: str, target_question_id: str) -> list[dict[str, Any]]:
    transferred: list[dict[str, Any]] = []
    rows = conn.execute(
        "SELECT * FROM paper_question WHERE question_id = ? ORDER BY paper_question_id",
        (source_question_id,),
    ).fetchall()
    for row in rows:
        data = dict(row)
        new_paper_question_id = stable_id(
            "PQ",
            data["paper_id"],
            target_question_id,
            data.get("question_number") or "",
            data.get("sub_number") or "",
            length=12,
        )
        existing = conn.execute(
            """
            SELECT paper_question_id
            FROM paper_question
            WHERE paper_id = ? AND question_id = ? AND question_number = ? AND sub_number = ?
            """,
            (
                data["paper_id"],
                target_question_id,
                data.get("question_number") or "",
                data.get("sub_number") or "",
            ),
        ).fetchone()
        if existing:
            conn.execute("DELETE FROM paper_question WHERE paper_question_id = ?", (data["paper_question_id"],))
            transferred.append(
                {
                    "source_paper_question_id": data["paper_question_id"],
                    "target_paper_question_id": existing["paper_question_id"],
                    "status": "target_already_exists_deleted_source_relation",
                }
            )
            continue
        conn.execute(
            """
            UPDATE paper_question
            SET paper_question_id = ?, question_id = ?, updated_at = ?
            WHERE paper_question_id = ?
            """,
            (
                new_paper_question_id,
                target_question_id,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                data["paper_question_id"],
            ),
        )
        transferred.append(
            {
                "source_paper_question_id": data["paper_question_id"],
                "target_paper_question_id": new_paper_question_id,
                "status": "updated_to_target",
            }
        )
    return transferred


def merge_answer_solution(conn: sqlite3.Connection, source_question_id: str, target_question_id: str) -> dict[str, Any]:
    source = question_row(conn, source_question_id)
    target = question_row(conn, target_question_id)
    before = {
        "answer_tex": target.get("answer_tex") or "",
        "solution_tex": target.get("solution_tex") or "",
        "canonical_tex": target.get("canonical_tex") or "",
        "raw_source_tex": target.get("raw_source_tex") or "",
    }
    answer_tex = target.get("answer_tex") or source.get("answer_tex") or ""
    solution_tex = target.get("solution_tex") or source.get("solution_tex") or ""
    canonical_tex = normalize_line_endings(target.get("canonical_tex") or source.get("canonical_tex") or "")
    raw_source_tex = normalize_line_endings(target.get("raw_source_tex") or source.get("raw_source_tex") or "")
    if source.get("answer_tex"):
        canonical_tex = replace_or_append_env(canonical_tex, "answer", source["answer_tex"])
        raw_source_tex = replace_or_append_env(raw_source_tex, "answer", source["answer_tex"])
    if source.get("solution_tex"):
        canonical_tex = replace_or_append_env(canonical_tex, "solutions", source["solution_tex"])
        raw_source_tex = replace_or_append_env(raw_source_tex, "solutions", source["solution_tex"])

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE question
        SET answer_tex = ?, solution_tex = ?, canonical_tex = ?, raw_source_tex = ?,
            updated_at = ?, last_manual_edit_at = ?
        WHERE question_id = ?
        """,
        (answer_tex, solution_tex, canonical_tex, raw_source_tex, now, now, target_question_id),
    )
    conn.execute(
        """
        UPDATE legacy_question_map
        SET content_hash = ?, updated_at = ?
        WHERE question_id = ?
        """,
        (file_hash_text(raw_source_tex), now, target_question_id),
    )
    target_path = legacy_file_path(conn, target_question_id)
    if target_path.exists():
        target_path.write_text(raw_source_tex, encoding="utf-8")

    after = {
        "answer_tex": answer_tex,
        "solution_tex": solution_tex,
        "canonical_tex": canonical_tex,
        "raw_source_tex": raw_source_tex,
    }
    revision_id = insert_revision(
        conn,
        target_question_id,
        changed_fields=["answer_tex", "solution_tex", "canonical_tex", "raw_source_tex"],
        before=before,
        after=after,
        note=f"合并 {source_question_id} 的答案解析到 {target_question_id}",
    )
    return {"revision_id": revision_id, "target_legacy_file": relative_to_root(target_path)}


def delete_question(conn: sqlite3.Connection, question_id: str, quarantine_root: Path) -> dict[str, Any]:
    path = legacy_file_path(conn, question_id)
    file_action = move_legacy_file_to_quarantine(path, quarantine_root)
    cursor = conn.execute("DELETE FROM question WHERE question_id = ?", (question_id,))
    return {
        "question_id": question_id,
        "deleted_rows": cursor.rowcount,
        "legacy_file_action": file_action,
    }


def fix_question_number(conn: sqlite3.Connection, question_id: str, target_number: str) -> dict[str, Any]:
    question = question_row(conn, question_id)
    legacy = legacy_row(conn, question_id)
    old_path = PROJECT_ROOT / str(legacy["legacy_file_path"])
    ensure_inside_project(old_path)
    new_path = old_path.with_name(
        re.sub(
            r"-(\d+)(-[^-\\/]+\.tex)$",
            f"-{target_number}\\2",
            old_path.name,
            count=1,
        )
    )
    ensure_inside_project(new_path)
    if new_path != old_path and new_path.exists():
        raise FileExistsError(f"目标题号文件已存在，拒绝覆盖：{new_path}")

    raw_before = question.get("raw_source_tex") or ""
    canonical_before = question.get("canonical_tex") or ""
    raw_after = normalize_line_endings(rewrite_problem_number(raw_before, target_number))
    canonical_after = normalize_line_endings(rewrite_problem_number(canonical_before, target_number))
    source_file_after = ""
    if old_path.exists():
        source_file_after = normalize_line_endings(rewrite_problem_number(old_path.read_text(encoding="utf-8"), target_number))
        if new_path != old_path:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
        new_path.write_text(source_file_after, encoding="utf-8")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        """
        UPDATE question
        SET legacy_file_path = ?, raw_source_tex = ?, canonical_tex = ?,
            updated_at = ?, last_manual_edit_at = ?
        WHERE question_id = ?
        """,
        (relative_to_root(new_path), raw_after, canonical_after, now, now, question_id),
    )
    conn.execute(
        """
        UPDATE legacy_question_map
        SET legacy_file_path = ?, detected_question_number = ?, content_hash = ?, updated_at = ?
        WHERE question_id = ?
        """,
        (relative_to_root(new_path), target_number, file_hash_text(source_file_after or raw_after), now, question_id),
    )
    revision_id = insert_revision(
        conn,
        question_id,
        changed_fields=["legacy_file_path", "raw_source_tex", "canonical_tex"],
        before={
            "legacy_file_path": legacy["legacy_file_path"],
            "raw_source_tex": raw_before,
            "canonical_tex": canonical_before,
        },
        after={
            "legacy_file_path": relative_to_root(new_path),
            "raw_source_tex": raw_after,
            "canonical_tex": canonical_after,
        },
        note=f"修正旧题源题号为第 {target_number} 题",
    )
    return {
        "question_id": question_id,
        "old_path": relative_to_root(old_path),
        "new_path": relative_to_root(new_path),
        "target_question_number": target_number,
        "revision_id": revision_id,
    }


def apply_decisions(db_path: Path, *, apply: bool, stamp: str) -> dict[str, Any]:
    quarantine_root = BACKUP_ROOT / stamp
    backup_db = quarantine_root / "mathcyclus_before_confirmed_cleanup.sqlite3"

    report: dict[str, Any] = {
        "stamp": stamp,
        "mode": "apply" if apply else "dry_run",
        "database": relative_to_root(db_path),
        "database_backup": "",
        "weak_duplicate_decisions": WEAK_DUPLICATE_DECISIONS,
        "question_number_fixes": QUESTION_NUMBER_FIXES,
        "knowledge_transfers": [],
        "paper_relation_transfers": [],
        "answer_solution_merges": [],
        "deleted_questions": [],
        "fixed_question_numbers": [],
        "integrity_check": "not_run_in_dry_run",
        "foreign_key_errors": [],
    }

    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在：{db_path}")

    with connect_database(db_path) as conn:
        for decision in WEAK_DUPLICATE_DECISIONS:
            question_row(conn, decision["source_question_id"])
            question_row(conn, decision["target_question_id"])
        for fix in QUESTION_NUMBER_FIXES:
            question_row(conn, fix["question_id"])

    if not apply:
        return report

    copy_sqlite_database(db_path, backup_db)
    report["database_backup"] = relative_to_root(backup_db)

    with connect_database(db_path) as conn:
        for decision in WEAK_DUPLICATE_DECISIONS:
            source_question_id = decision["source_question_id"]
            target_question_id = decision["target_question_id"]
            report["knowledge_transfers"].append(
                {
                    "source_question_id": source_question_id,
                    "target_question_id": target_question_id,
                    "items": transfer_knowledge_links(conn, source_question_id, target_question_id),
                }
            )

            if decision["decision"] == "merge_answer_solution_and_relation":
                report["paper_relation_transfers"].append(
                    {
                        "source_question_id": source_question_id,
                        "target_question_id": target_question_id,
                        "items": transfer_paper_relations(conn, source_question_id, target_question_id),
                    }
                )
                report["answer_solution_merges"].append(
                    {
                        "source_question_id": source_question_id,
                        "target_question_id": target_question_id,
                        **merge_answer_solution(conn, source_question_id, target_question_id),
                    }
                )

            report["deleted_questions"].append(delete_question(conn, source_question_id, quarantine_root))

        for fix in QUESTION_NUMBER_FIXES:
            report["fixed_question_numbers"].append(
                fix_question_number(conn, fix["question_id"], fix["target_question_number"])
            )

        report["integrity_check"] = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        report["foreign_key_errors"] = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        conn.commit()

    manifest_path = quarantine_root / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["manifest"] = relative_to_root(manifest_path)
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report


def write_markdown_report(report: dict[str, Any], report_path: Path) -> None:
    delete_lines = []
    for item in report["deleted_questions"]:
        action = item.get("legacy_file_action") or {}
        delete_lines.append(
            f"| `{item.get('question_id')}` | {item.get('deleted_rows')} | "
            f"{action.get('status') or ''} | `{action.get('source') or ''}` | `{action.get('quarantine_path') or ''}` |"
        )
    relation_lines = []
    for group in report["paper_relation_transfers"]:
        for item in group.get("items") or []:
            relation_lines.append(
                f"| `{group['source_question_id']}` | `{group['target_question_id']}` | "
                f"`{item.get('source_paper_question_id')}` | `{item.get('target_paper_question_id')}` | {item.get('status')} |"
            )
    fix_lines = []
    for item in report["fixed_question_numbers"]:
        fix_lines.append(
            f"| `{item.get('question_id')}` | {item.get('target_question_number')} | "
            f"`{item.get('old_path')}` | `{item.get('new_path')}` | `{item.get('revision_id')}` |"
        )
    merge_lines = []
    for item in report["answer_solution_merges"]:
        merge_lines.append(
            f"| `{item.get('source_question_id')}` | `{item.get('target_question_id')}` | "
            f"`{item.get('target_legacy_file')}` | `{item.get('revision_id')}` |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"""# 已确认数据清洗决策执行报告

> 模式：{report['mode']}  
> 数据库：`{report['database']}`  
> 数据库备份：`{report.get('database_backup') or 'dry-run 未生成'}`

## 删除弱副本

| question_id | 删除行数 | 旧文件状态 | 原路径 | 隔离路径 |
| --- | ---: | --- | --- | --- |
{chr(10).join(delete_lines) or '| dry-run 未执行 | 0 |  |  |  |'}

## 试卷关系转移

| 来源题 | 目标题 | 原关系 ID | 新关系 ID | 状态 |
| --- | --- | --- | --- | --- |
{chr(10).join(relation_lines) or '| 无或 dry-run 未执行 |  |  |  |  |'}

## 答案解析合并

| 来源题 | 目标题 | 更新旧文件 | revision_id |
| --- | --- | --- | --- |
{chr(10).join(merge_lines) or '| 无或 dry-run 未执行 |  |  |'}

## 题号修正

| question_id | 目标题号 | 原路径 | 新路径 | revision_id |
| --- | --- | --- | --- | --- |
{chr(10).join(fix_lines) or '| 无或 dry-run 未执行 |  |  |  |'}

## 完整性

- `PRAGMA integrity_check`：`{report['integrity_check']}`
- 外键错误数：{len(report['foreign_key_errors'])}
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="执行已确认的数据清洗决策。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--apply", action="store_true", help="真正写库和移动文件；默认只做 dry-run。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = resolve_db_path(args.db)
    report = apply_decisions(db_path, apply=bool(args.apply), stamp=args.stamp)
    report_path = REPORTS_DIR / f"confirmed_cleanup_decisions_{args.stamp}.md"
    write_markdown_report(report, report_path)
    print(f"mode={report['mode']}")
    print(f"deleted={len(report['deleted_questions'])}")
    print(f"relation_transfers={sum(len(group.get('items') or []) for group in report['paper_relation_transfers'])}")
    print(f"number_fixes={len(report['fixed_question_numbers'])}")
    print(f"report={relative_to_root(report_path)}")
    if report.get("database_backup"):
        print(f"database_backup={report['database_backup']}")


if __name__ == "__main__":
    main()
