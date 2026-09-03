from __future__ import annotations

import argparse
import csv
import hashlib
import json
import mimetypes
import re
import shutil
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from itertools import combinations
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_combined_20260902_initial.sqlite3"
DEFAULT_PAPER_POSITION_REVIEW = PROJECT_ROOT / "db" / "seed" / "paper_position_review_20260902_warning_review.csv"
DEFAULT_MISSING_ASSET_REVIEW = PROJECT_ROOT / "db" / "seed" / "missing_asset_review_20260902_warning_review.csv"
DEFAULT_IMPORT_DRAFT_REVIEW = PROJECT_ROOT / "db" / "seed" / "import_draft_review_20260902_warning_review.csv"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"

PAPER_POSITION_ACTIONS = {
    "keep_all",
    "split_sub_number",
    "mark_equivalent",
    "drop_duplicate_relation",
    "needs_manual_fix",
}
MISSING_ASSET_ACTIONS = {
    "locate_file",
    "replace_ref",
    "create_questionasset",
    "ignore_external",
    "needs_manual_fix",
}
IMPORT_DRAFT_ACTIONS = {
    "manual_complete_fields",
    "mark_ready",
    "reject",
    "keep_as_sample",
    "needs_manual_fix",
}
DROP_ID_PATTERN = re.compile(r"(?:drop_paper_question_ids?|drop_pq_ids?)\s*=\s*([A-Za-z0-9_|,;，；、\s-]+)")

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.precommit_database_audit import audit_database


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


def stable_id(prefix: str, *values: object, length: int = 12) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as file:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(file)
        ]


def split_pipe_list(value: str) -> list[str]:
    return [item.strip() for item in (value or "").split("|") if item.strip()]


def split_id_list(value: str) -> list[str]:
    return [item.strip() for item in re.split(r"[|,;，；、\s]+", value or "") if item.strip()]


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def table_count(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def database_counts(conn: sqlite3.Connection) -> dict[str, int]:
    tables = [
        "question",
        "paper",
        "paper_question",
        "knowledge_area",
        "question_knowledge_area",
        "question_equivalence",
        "question_asset",
        "question_import_draft",
        "question_import_draft_asset",
        "import_report_item",
    ]
    return {table: table_count(conn, table) for table in tables}


def question_exists(conn: sqlite3.Connection, question_id: str) -> bool:
    return conn.execute("SELECT 1 FROM question WHERE question_id = ?", (question_id,)).fetchone() is not None


def paper_question_exists(conn: sqlite3.Connection, paper_question_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM paper_question WHERE paper_question_id = ?",
            (paper_question_id,),
        ).fetchone()
        is not None
    )


def draft_exists(conn: sqlite3.Connection, draft_id: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM question_import_draft WHERE draft_id = ?",
            (draft_id,),
        ).fetchone()
        is not None
    )


def upsert_equivalence(
    conn: sqlite3.Connection,
    question_id_a: str,
    question_id_b: str,
    relation_type: str,
    review_status: str,
    note: str,
) -> str:
    left, right = sorted([question_id_a, question_id_b])
    equivalence_id = stable_id("QE", left, right, relation_type)
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
        (equivalence_id, left, right, relation_type, 1.0, review_status, note),
    )
    return equivalence_id


def reviewed(row: dict[str, str]) -> bool:
    return row.get("review_status", "").strip().lower() == "approved"


def action_result(
    *,
    kind: str,
    review_id: str,
    action: str,
    status: str,
    message: str,
    changed_rows: int = 0,
) -> dict[str, object]:
    return {
        "kind": kind,
        "review_id": review_id,
        "action": action,
        "status": status,
        "message": message,
        "changed_rows": changed_rows,
    }


def parse_drop_paper_question_ids(row: dict[str, str]) -> list[str]:
    note = row.get("reviewer_note", "")
    match = DROP_ID_PATTERN.search(note)
    if not match:
        return []
    return split_id_list(match.group(1))


def apply_paper_position_review(conn: sqlite3.Connection, row: dict[str, str]) -> dict[str, object]:
    review_id = row.get("review_id", "")
    action = row.get("suggested_action", "")
    question_ids = split_pipe_list(row.get("question_ids", ""))
    paper_question_ids = split_pipe_list(row.get("paper_question_ids", ""))

    if not reviewed(row):
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="skipped",
            message="review_status 不是 approved，不应用",
        )
    if action not in PAPER_POSITION_ACTIONS:
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="invalid",
            message="suggested_action 为空或不支持",
        )
    missing_questions = [question_id for question_id in question_ids if not question_exists(conn, question_id)]
    if missing_questions:
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="invalid",
            message="question_id 不存在：" + " | ".join(missing_questions),
        )
    missing_paper_questions = [
        paper_question_id for paper_question_id in paper_question_ids if not paper_question_exists(conn, paper_question_id)
    ]
    if missing_paper_questions:
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="invalid",
            message="paper_question_id 不存在：" + " | ".join(missing_paper_questions),
        )

    note = f"{review_id} {action}: {row.get('reviewer_note', '')}".strip()
    if action == "keep_all":
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="applied",
            message="确认保留全部重复题位；数据库副本不改题目关系",
        )
    if action == "needs_manual_fix":
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="manual",
            message="标记为需要人工处理；数据库副本不改",
        )
    if action == "mark_equivalent":
        written = 0
        for question_id_a, question_id_b in combinations(sorted(question_ids), 2):
            upsert_equivalence(conn, question_id_a, question_id_b, "same_question", "approved", note)
            written += 1
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="applied",
            changed_rows=written,
            message=f"已在副本中标记同题关系 {written} 条；不删除任何题目",
        )
    if action == "split_sub_number":
        changed = 0
        for index, paper_question_id in enumerate(paper_question_ids, start=1):
            conn.execute(
                """
                UPDATE paper_question
                SET sub_number = ?, updated_at = CURRENT_TIMESTAMP
                WHERE paper_question_id = ?
                """,
                (str(index), paper_question_id),
            )
            changed += 1
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="applied",
            changed_rows=changed,
            message="已在副本中按当前 CSV 顺序写入 sub_number=1..n",
        )

    drop_ids = parse_drop_paper_question_ids(row)
    if not drop_ids:
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="invalid",
            message="drop_duplicate_relation 必须在 reviewer_note 写 drop_paper_question_ids=PQ...|PQ...",
        )
    unknown_drop_ids = [paper_question_id for paper_question_id in drop_ids if paper_question_id not in paper_question_ids]
    if unknown_drop_ids:
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="invalid",
            message="待删除 paper_question_id 不在当前审查组：" + " | ".join(unknown_drop_ids),
        )
    if len(drop_ids) >= len(paper_question_ids):
        return action_result(
            kind="paper_position",
            review_id=review_id,
            action=action,
            status="invalid",
            message="不能删除当前组内全部 paper_question 关系",
        )
    for paper_question_id in drop_ids:
        conn.execute("DELETE FROM paper_question WHERE paper_question_id = ?", (paper_question_id,))
    return action_result(
        kind="paper_position",
        review_id=review_id,
        action=action,
        status="applied",
        changed_rows=len(drop_ids),
        message="已在副本中删除指定重复 paper_question 关系",
    )


def field_contains(conn: sqlite3.Connection, question_id: str, field: str, needle: str) -> bool:
    row = conn.execute(f"SELECT {field} FROM question WHERE question_id = ?", (question_id,)).fetchone()
    return bool(row and needle and needle in str(row[0] or ""))


def infer_asset_role(conn: sqlite3.Connection, question_id: str, missing_ref: str) -> str:
    if field_contains(conn, question_id, "stem_tex", missing_ref):
        return "problem"
    if field_contains(conn, question_id, "answer_tex", missing_ref):
        return "answer"
    if field_contains(conn, question_id, "solution_tex", missing_ref):
        return "solution"
    if field_contains(conn, question_id, "canonical_tex", missing_ref):
        return "solution"
    return "problem"


def next_asset_sort_order(conn: sqlite3.Connection, question_id: str, role: str) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(MAX(sort_order), 0) + 1
        FROM question_asset
        WHERE question_id = ? AND role = ?
        """,
        (question_id, role),
    ).fetchone()
    return int(row[0] or 1)


def insert_question_asset(
    conn: sqlite3.Connection,
    question_id: str,
    role: str,
    asset_path: Path,
    caption: str,
) -> str:
    relative_path = relative_to_root(asset_path)
    asset_id = stable_id("A", question_id, role, relative_path, file_hash(asset_path))
    mime_type = mimetypes.guess_type(asset_path.name)[0] or ""
    conn.execute(
        """
        INSERT OR IGNORE INTO question_asset(
            asset_id, question_id, role, file_path, original_file_name,
            mime_type, file_hash, caption, sort_order
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            asset_id,
            question_id,
            role,
            relative_path,
            asset_path.name,
            mime_type,
            file_hash(asset_path),
            caption,
            next_asset_sort_order(conn, question_id, role),
        ),
    )
    return asset_id


def replace_graphics_ref(conn: sqlite3.Connection, question_id: str, old_ref: str, new_ref: str) -> int:
    changed = 0
    for field in ["stem_tex", "answer_tex", "solution_tex", "canonical_tex", "raw_source_tex"]:
        row = conn.execute(f"SELECT {field} FROM question WHERE question_id = ?", (question_id,)).fetchone()
        if not row:
            continue
        value = str(row[0] or "")
        if old_ref not in value:
            continue
        conn.execute(
            f"""
            UPDATE question
            SET {field} = ?, updated_at = CURRENT_TIMESTAMP
            WHERE question_id = ?
            """,
            (value.replace(old_ref, new_ref), question_id),
        )
        changed += 1
    return changed


def apply_missing_asset_review(conn: sqlite3.Connection, row: dict[str, str]) -> dict[str, object]:
    review_id = row.get("review_id", "")
    action = row.get("suggested_action", "")
    question_id = row.get("question_id", "")
    missing_ref = row.get("missing_ref", "")
    replacement_path_text = row.get("replacement_path", "")

    if not reviewed(row):
        return action_result(
            kind="missing_asset",
            review_id=review_id,
            action=action,
            status="skipped",
            message="review_status 不是 approved，不应用",
        )
    if action not in MISSING_ASSET_ACTIONS:
        return action_result(
            kind="missing_asset",
            review_id=review_id,
            action=action,
            status="invalid",
            message="suggested_action 为空或不支持",
        )
    if not question_exists(conn, question_id):
        return action_result(
            kind="missing_asset",
            review_id=review_id,
            action=action,
            status="invalid",
            message=f"question_id 不存在：{question_id}",
        )
    if action == "ignore_external":
        return action_result(
            kind="missing_asset",
            review_id=review_id,
            action=action,
            status="applied",
            message="确认外部或暂不处理图片；数据库副本不改",
        )
    if action == "needs_manual_fix":
        return action_result(
            kind="missing_asset",
            review_id=review_id,
            action=action,
            status="manual",
            message="标记为需要人工处理；数据库副本不改",
        )
    if not replacement_path_text:
        return action_result(
            kind="missing_asset",
            review_id=review_id,
            action=action,
            status="invalid",
            message="locate_file/replace_ref/create_questionasset 必须填写 replacement_path",
        )

    replacement_path = resolve_project_path(replacement_path_text)
    ensure_inside_project(replacement_path)
    if not replacement_path.exists() or not replacement_path.is_file():
        return action_result(
            kind="missing_asset",
            review_id=review_id,
            action=action,
            status="invalid",
            message=f"replacement_path 文件不存在：{replacement_path_text}",
        )

    role = infer_asset_role(conn, question_id, missing_ref)
    changed = 0
    messages = []
    if action in {"locate_file", "replace_ref"}:
        changed += replace_graphics_ref(conn, question_id, missing_ref, relative_to_root(replacement_path))
        messages.append(f"替换 TeX 引用字段 {changed} 个")
    if action == "create_questionasset":
        asset_id = insert_question_asset(conn, question_id, role, replacement_path, row.get("reviewer_note", ""))
        changed += 1
        messages.append(f"登记 question_asset `{asset_id}`")
    return action_result(
        kind="missing_asset",
        review_id=review_id,
        action=action,
        status="applied",
        changed_rows=changed,
        message="；".join(messages) or "已处理",
    )


def draft_required_fields(conn: sqlite3.Connection, draft_id: str) -> dict[str, str]:
    row = conn.execute(
        """
        SELECT stem_tex, answer_tex, solution_tex
        FROM question_import_draft
        WHERE draft_id = ?
        """,
        (draft_id,),
    ).fetchone()
    if not row:
        return {}
    return {
        "stem_tex": str(row[0] or ""),
        "answer_tex": str(row[1] or ""),
        "solution_tex": str(row[2] or ""),
    }


def apply_import_draft_review(conn: sqlite3.Connection, row: dict[str, str]) -> dict[str, object]:
    review_id = row.get("review_id", "")
    draft_id = row.get("draft_id", "")
    action = row.get("review_decision", "")

    if not action:
        return action_result(
            kind="import_draft",
            review_id=review_id,
            action=action,
            status="skipped",
            message="未填写 review_decision，不应用",
        )
    if action not in IMPORT_DRAFT_ACTIONS:
        return action_result(
            kind="import_draft",
            review_id=review_id,
            action=action,
            status="invalid",
            message="review_decision 不支持",
        )
    if not draft_exists(conn, draft_id):
        return action_result(
            kind="import_draft",
            review_id=review_id,
            action=action,
            status="invalid",
            message=f"draft_id 不存在：{draft_id}",
        )
    note = row.get("reviewer_note", "")
    if action in {"manual_complete_fields", "needs_manual_fix"}:
        return action_result(
            kind="import_draft",
            review_id=review_id,
            action=action,
            status="manual",
            message="标记为需要人工补充；数据库副本不改",
        )
    if action == "mark_ready":
        fields = draft_required_fields(conn, draft_id)
        missing = [field for field, value in fields.items() if not value.strip()]
        if missing:
            return action_result(
                kind="import_draft",
                review_id=review_id,
                action=action,
                status="invalid",
                message="mark_ready 前必须补齐字段：" + " | ".join(missing),
            )
        status = "ready"
        reason = note
    elif action == "reject":
        status = "rejected"
        reason = note or "人工审查拒绝"
    else:
        status = "sample"
        reason = note or "保留为样例草稿，不进入正式题表"

    conn.execute(
        """
        UPDATE question_import_draft
        SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
        WHERE draft_id = ?
        """,
        (status, reason, draft_id),
    )
    return action_result(
        kind="import_draft",
        review_id=review_id,
        action=action,
        status="applied",
        changed_rows=1,
        message=f"已在副本中把草稿状态更新为 `{status}`",
    )


def apply_all_reviews(
    conn: sqlite3.Connection,
    paper_position_rows: list[dict[str, str]],
    missing_asset_rows: list[dict[str, str]],
    import_draft_rows: list[dict[str, str]],
) -> list[dict[str, object]]:
    results: list[dict[str, object]] = []
    for row in paper_position_rows:
        results.append(apply_paper_position_review(conn, row))
    for row in missing_asset_rows:
        results.append(apply_missing_asset_review(conn, row))
    for row in import_draft_rows:
        results.append(apply_import_draft_review(conn, row))
    return results


def compact_counts(counts: dict[str, int]) -> str:
    if not counts:
        return "无"
    return "，".join(f"`{key or '空'}`={value}" for key, value in sorted(counts.items()))


def markdown_count_delta(before: dict[str, int], after: dict[str, int]) -> str:
    return "\n".join(
        f"| `{table}` | {before.get(table, 0)} | {after.get(table, 0)} | {after.get(table, 0) - before.get(table, 0)} |"
        for table in before
    )


def markdown_results(results: list[dict[str, object]], status: str, limit: int = 50) -> str:
    selected = [row for row in results if row["status"] == status]
    if not selected:
        return "无"
    lines = []
    for row in selected[:limit]:
        lines.append(
            f"- `{row['kind']}` / `{row['review_id']}` / `{row['action'] or '空'}`：{row['message']}"
        )
    if len(selected) > limit:
        lines.append(f"- 另有 {len(selected) - limit} 项未展示")
    return "\n".join(lines)


def write_report(report: dict[str, Any], md_path: Path, json_path: Path) -> None:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    results = report["results"]
    status_counts = Counter(str(row["status"]) for row in results)
    kind_counts = Counter(str(row["kind"]) for row in results)
    action_counts = Counter(f"{row['kind']}:{row['action'] or '空'}" for row in results)
    before_audit = report["before_audit"]
    after_audit = report["after_audit"]
    md_path.write_text(
        f"""# 数据 warning 人工审查应用 Dry-run 报告

> 生成时间：{report['created_at']}  
> 来源数据库：`{report['source_db']}`  
> 输出数据库：`{report['output_db']}`  
> 执行方式：复制预览库后只在副本中应用已审查决策；不修改正式库、不修改 `.tex`。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 审查行总数 | {len(results)} |
| applied | {status_counts.get('applied', 0)} |
| skipped | {status_counts.get('skipped', 0)} |
| manual | {status_counts.get('manual', 0)} |
| invalid | {status_counts.get('invalid', 0)} |

- 类型分布：{compact_counts(dict(kind_counts))}
- 动作分布：{compact_counts(dict(action_counts))}
- 执行前审计：`{before_audit['status']}`，warning {len(before_audit.get('warnings') or [])}，blocker {len(before_audit.get('blockers') or [])}
- 执行后审计：`{after_audit['status']}`，warning {len(after_audit.get('warnings') or [])}，blocker {len(after_audit.get('blockers') or [])}

## 表计数变化

| 表 | 执行前 | 执行后 | 变化 |
| --- | ---: | ---: | ---: |
{markdown_count_delta(report['before_counts'], report['after_counts'])}

## 已应用

{markdown_results(results, 'applied')}

## 需要人工处理

{markdown_results(results, 'manual')}

## 无效决策

{markdown_results(results, 'invalid')}

## 跳过项

{markdown_results(results, 'skipped')}

## 使用规则

- 试卷重复题位只有 `review_status=approved` 时才会应用。
- `drop_duplicate_relation` 必须在 `reviewer_note` 写 `drop_paper_question_ids=PQ...|PQ...`，避免误删整组关系。
- 缺失图片只有填写有效 `replacement_path` 后才会替换引用或登记资产。
- AI/OCR 草稿必须填写 `review_decision`；`mark_ready` 会检查题干、答案、解析是否齐全。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="在数据库副本上应用数据 warning 人工审查结果；不改正式库。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源综合预览 SQLite。")
    parser.add_argument("--paper-position-review", default=str(DEFAULT_PAPER_POSITION_REVIEW), help="重复试卷题位审查 CSV。")
    parser.add_argument("--missing-asset-review", default=str(DEFAULT_MISSING_ASSET_REVIEW), help="缺失图片引用审查 CSV。")
    parser.add_argument("--import-draft-review", default=str(DEFAULT_IMPORT_DRAFT_REVIEW), help="AI/OCR 草稿审查 CSV。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = resolve_project_path(args.source_db)
    paper_position_path = resolve_project_path(args.paper_position_review)
    missing_asset_path = resolve_project_path(args.missing_asset_review)
    import_draft_path = resolve_project_path(args.import_draft_review)

    ensure_inside_project(source_db)
    ensure_inside_project(paper_position_path)
    ensure_inside_project(missing_asset_path)
    ensure_inside_project(import_draft_path)
    if not source_db.exists():
        raise SystemExit(f"来源数据库不存在：{source_db}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_db = DATA_DIR / f"mathcyclus_preview_warning_review_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"data_warning_review_dry_run_{args.stamp}.md"
    json_path = REPORTS_DIR / f"data_warning_review_dry_run_{args.stamp}.json"
    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)

    before_audit = audit_database(output_db)
    conn = sqlite3.connect(output_db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        before_counts = database_counts(conn)
        with conn:
            results = apply_all_reviews(
                conn,
                read_csv(paper_position_path),
                read_csv(missing_asset_path),
                read_csv(import_draft_path),
            )
        after_counts = database_counts(conn)
    finally:
        conn.close()
    after_audit = audit_database(output_db)

    status_counts = Counter(str(row["status"]) for row in results)
    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source_db": relative_to_root(source_db),
        "output_db": relative_to_root(output_db),
        "review_csvs": {
            "paper_position_review": relative_to_root(paper_position_path),
            "missing_asset_review": relative_to_root(missing_asset_path),
            "import_draft_review": relative_to_root(import_draft_path),
        },
        "before_counts": before_counts,
        "after_counts": after_counts,
        "before_audit": before_audit,
        "after_audit": after_audit,
        "results": results,
        "status_counts": dict(sorted(status_counts.items())),
    }
    write_report(report, report_path, json_path)

    print(f"rows={len(results)}")
    print(f"applied={status_counts.get('applied', 0)}")
    print(f"skipped={status_counts.get('skipped', 0)}")
    print(f"manual={status_counts.get('manual', 0)}")
    print(f"invalid={status_counts.get('invalid', 0)}")
    print(f"before_audit={before_audit['status']}")
    print(f"after_audit={after_audit['status']}")
    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
