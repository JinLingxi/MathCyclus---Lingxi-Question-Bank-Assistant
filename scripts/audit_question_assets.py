from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
REPORTS_DIR = PROJECT_ROOT / "reports"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.asset_service import collect_asset_reference_issues

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


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def fetch_questions(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
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
        ORDER BY q.question_id
        """
    ).fetchall()


def question_assets(conn: sqlite3.Connection, question_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT *
        FROM question_asset
        WHERE question_id = ?
        ORDER BY role, sort_order, asset_id
        """,
        (question_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_drafts(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    if not table_exists(conn, "question_import_draft"):
        return []
    return conn.execute(
        """
        SELECT *
        FROM question_import_draft
        ORDER BY created_at DESC, draft_id
        """
    ).fetchall()


def draft_assets(conn: sqlite3.Connection, draft_id: str) -> list[dict]:
    if not table_exists(conn, "question_import_draft_asset"):
        return []
    rows = conn.execute(
        """
        SELECT *
        FROM question_import_draft_asset
        WHERE draft_id = ?
        ORDER BY role, sort_order, draft_asset_id
        """,
        (draft_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def audit_assets(db_path: Path) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        questions = fetch_questions(conn)
        asset_rows = conn.execute("SELECT * FROM question_asset").fetchall()
        missing_includegraphics = []
        found_includegraphics = []
        seen_includegraphics: set[tuple[str, str]] = set()
        unresolved_questionasset = []
        seen_questionasset: set[tuple[str, str]] = set()
        unused_asset_questions = []
        draft_reference_issues = []

        for row in questions:
            tex = "\n".join(
                str(row[field] or "")
                for field in ["stem_tex", "answer_tex", "solution_tex", "canonical_tex"]
            )
            include_refs = INCLUDE_GRAPHICS_PATTERN.findall(tex)
            questionasset_refs = QUESTION_ASSET_PATTERN.findall(tex)
            assets = question_assets(conn, row["question_id"])
            asset_aliases: set[str] = set()
            for asset in assets:
                file_path = str(asset.get("file_path") or "")
                original_name = str(asset.get("original_file_name") or "")
                for alias in [
                    str(asset.get("asset_id") or ""),
                    Path(file_path).stem,
                    Path(file_path).name,
                    Path(original_name).stem,
                    Path(original_name).name,
                ]:
                    if alias:
                        asset_aliases.add(alias)

            for ref in include_refs:
                include_key = (str(row["question_id"]), ref)
                if include_key in seen_includegraphics:
                    continue
                seen_includegraphics.add(include_key)
                resolved = resolve_graphics_ref(ref, row["legacy_file_path"] or "")
                item = {
                    "question_id": row["question_id"],
                    "legacy_id": row["legacy_id"],
                    "legacy_file_path": row["legacy_file_path"],
                    "ref": ref,
                    "resolved_path": relative_to_root(resolved) if resolved else "",
                }
                if resolved:
                    found_includegraphics.append(item)
                else:
                    missing_includegraphics.append(item)

            for alias in questionasset_refs:
                asset_key = (str(row["question_id"]), alias)
                if asset_key in seen_questionasset:
                    continue
                seen_questionasset.add(asset_key)
                if alias not in asset_aliases:
                    unresolved_questionasset.append(
                        {
                            "question_id": row["question_id"],
                            "legacy_id": row["legacy_id"],
                            "alias": alias,
                            "known_asset_aliases": sorted(asset_aliases),
                        }
                    )

            if assets and not include_refs and not questionasset_refs:
                unused_asset_questions.append(
                    {
                        "question_id": row["question_id"],
                        "legacy_id": row["legacy_id"],
                        "asset_count": len(assets),
                    }
                )

        for row in fetch_drafts(conn):
            draft = dict(row)
            assets = draft_assets(conn, row["draft_id"])
            issues = collect_asset_reference_issues(draft, assets, project_root=PROJECT_ROOT)
            issue_count = (
                len(issues.get("missing_includegraphics") or [])
                + len(issues.get("unresolved_questionasset") or [])
                + len(issues.get("missing_asset_files") or [])
            )
            if issue_count or issues.get("unreferenced_assets"):
                draft_reference_issues.append(
                    {
                        "draft_id": row["draft_id"],
                        "source_label": row["source_label"],
                        "review_status": row["review_status"],
                        "issue_count": issue_count,
                        "issues": issues,
                    }
                )
    finally:
        conn.close()

    role_counts = Counter(str(row["role"]) for row in asset_rows)
    draft_blocker_count = sum(
        1
        for row in draft_reference_issues
        if row.get("review_status") != "sample" and int(row.get("issue_count") or 0) > 0
    )
    return {
        "database": relative_to_root(db_path),
        "question_asset_count": len(asset_rows),
        "asset_role_counts": dict(sorted(role_counts.items())),
        "found_includegraphics_count": len(found_includegraphics),
        "missing_includegraphics": missing_includegraphics,
        "unresolved_questionasset": unresolved_questionasset,
        "unused_asset_questions": unused_asset_questions,
        "draft_reference_issue_count": len(draft_reference_issues),
        "draft_reference_blocker_count": draft_blocker_count,
        "draft_reference_issues": draft_reference_issues,
    }


def write_report(report: dict[str, object], path: Path) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    role_lines = "\n".join(
        f"| `{role}` | {count} |"
        for role, count in report["asset_role_counts"].items()
    ) or "| 无 | 0 |"
    missing_text = "\n".join(
        f"- `{row['question_id']}` / 旧 ID `{row['legacy_id']}` / `{row['ref']}`"
        for row in report["missing_includegraphics"][:50]
    ) or "无"
    unresolved_text = "\n".join(
        f"- `{row['question_id']}` / 旧 ID `{row['legacy_id']}` / `{row['alias']}`"
        for row in report["unresolved_questionasset"][:50]
    ) or "无"
    unused_text = "\n".join(
        f"- `{row['question_id']}` / 旧 ID `{row['legacy_id']}` / {row['asset_count']} 个资产未被正文占位符引用"
        for row in report["unused_asset_questions"][:50]
    ) or "无"
    draft_issue_text = "\n".join(
        f"- `{row['draft_id']}` / `{row['review_status']}` / {row['issue_count']} 个需处理问题 / {row['source_label']}"
        for row in report["draft_reference_issues"][:50]
    ) or "无"

    path.write_text(
        f"""# 题目图片与资源引用审计报告

> 生成时间：{now}  
> 数据库：`{report['database']}`  
> 审计方式：只读检查，不复制、不移动、不修改图片和 TeX。

## 总览

| 指标 | 数量 |
| --- | ---: |
| `question_asset` 记录 | {report['question_asset_count']} |
| 可解析 `includegraphics` 引用 | {report['found_includegraphics_count']} |
| 缺失 `includegraphics` 引用 | {len(report['missing_includegraphics'])} |
| 未解析 `questionasset` 占位符 | {len(report['unresolved_questionasset'])} |
| 有资产但正文未引用的题目 | {len(report['unused_asset_questions'])} |
| 草稿引用问题记录 | {report['draft_reference_issue_count']} |
| 非 sample 草稿引用阻塞 | {report['draft_reference_blocker_count']} |

## 资源角色

| role | 数量 |
| --- | ---: |
{role_lines}

## 缺失 includegraphics

{missing_text}

## 未解析 questionasset

{unresolved_text}

## 有资产但正文未引用

{unused_text}

## 草稿图片引用问题

{draft_issue_text}

## 判断

- 旧题库仍主要依赖 `includegraphics`。
- 新图系统建议逐步改用 `\\questionasset{{alias}}` 作为稳定占位符。
- 最终导出时再由导出器把占位符解析为实际图片路径。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计题目图片资产与 TeX 引用关系。")
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
    report = audit_assets(db_path)
    json_path = REPORTS_DIR / f"question_asset_audit_{args.stamp}.json"
    md_path = REPORTS_DIR / f"question_asset_audit_{args.stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    write_report(report, md_path)

    print(f"question_assets={report['question_asset_count']}")
    print(f"missing_includegraphics={len(report['missing_includegraphics'])}")
    print(f"unresolved_questionasset={len(report['unresolved_questionasset'])}")
    print(f"draft_reference_blockers={report['draft_reference_blocker_count']}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
