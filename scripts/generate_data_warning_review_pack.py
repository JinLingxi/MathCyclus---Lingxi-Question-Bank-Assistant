from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_combined_20260902_initial.sqlite3"
DEFAULT_REVIEW_DIR = PROJECT_ROOT / "db" / "seed"
REPORTS_DIR = PROJECT_ROOT / "reports"

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


def stable_review_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "") for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]
    return f"{prefix}{digest}"


def pipe_join(items: list[object]) -> str:
    return "|".join(str(item or "") for item in items)


def one_line(text: object, *, limit: int = 240) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    return compact[: limit - 1] + "…"


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return (
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        is not None
    )


def fetch_duplicate_position_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "paper_question"):
        return []
    duplicate_positions = conn.execute(
        """
        SELECT
            p.paper_id,
            p.year,
            p.paper_series,
            p.track,
            p.paper_name,
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

    rows: list[dict[str, Any]] = []
    for position in duplicate_positions:
        items = conn.execute(
            """
            SELECT
                pq.paper_question_id,
                pq.question_id,
                pq.display_order,
                q.legacy_id,
                l.legacy_file_path,
                l.detected_chapter,
                substr(q.stem_tex, 1, 220) AS stem_preview
            FROM paper_question pq
            JOIN question q ON q.question_id = pq.question_id
            LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
            WHERE pq.paper_id = ?
              AND pq.question_number = ?
              AND pq.sub_number = ?
            ORDER BY pq.display_order, pq.question_id
            """,
            (
                position["paper_id"],
                position["question_number"],
                position["sub_number"],
            ),
        ).fetchall()
        question_ids = [item["question_id"] for item in items]
        rows.append(
            {
                "review_id": stable_review_id(
                    "PPR",
                    position["paper_id"],
                    position["question_number"],
                    position["sub_number"],
                ),
                "review_status": "pending",
                "suggested_action": "",
                "paper_id": position["paper_id"],
                "year": position["year"],
                "paper_series": position["paper_series"],
                "track": position["track"],
                "paper_name": position["paper_name"],
                "question_number": position["question_number"],
                "sub_number": position["sub_number"],
                "duplicate_count": position["duplicate_count"],
                "question_ids": pipe_join(question_ids),
                "paper_question_ids": pipe_join([item["paper_question_id"] for item in items]),
                "legacy_ids": pipe_join([item["legacy_id"] for item in items]),
                "chapters": pipe_join([item["detected_chapter"] for item in items]),
                "legacy_file_paths": pipe_join([item["legacy_file_path"] for item in items]),
                "stem_previews": pipe_join([one_line(item["stem_preview"]) for item in items]),
                "allowed_actions": "keep_all|split_sub_number|mark_equivalent|drop_duplicate_relation|needs_manual_fix",
                "reviewer_note": "",
            }
        )
    return rows


def iter_candidate_files() -> list[Path]:
    ignored_dirs = {
        ".git",
        ".venv",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tikz_cache",
        ".edge-test-profile",
    }
    candidates: list[Path] = []
    stack = [PROJECT_ROOT]
    while stack:
        directory = stack.pop()
        try:
            children = list(directory.iterdir())
        except OSError:
            continue
        for child in children:
            if child.is_dir():
                if child.name not in ignored_dirs:
                    stack.append(child)
            elif child.is_file():
                candidates.append(child)
    return candidates


def normalized_name(name: str) -> str:
    return "".join(ch.lower() for ch in name if not ch.isspace())


def find_asset_candidates(ref: str, files: list[Path], limit: int) -> list[str]:
    ref_name = Path(ref).name
    normalized_ref = normalized_name(ref_name)
    exact: list[Path] = []
    fuzzy: list[Path] = []
    for path in files:
        name = path.name
        if name == ref_name:
            exact.append(path)
        elif normalized_name(name) == normalized_ref:
            fuzzy.append(path)
    result = exact + [path for path in fuzzy if path not in exact]
    return [relative_to_root(path) for path in result[:limit]]


def fetch_missing_asset_rows(
    audit: dict[str, Any],
    *,
    candidate_limit: int,
) -> list[dict[str, Any]]:
    files = iter_candidate_files()
    rows: list[dict[str, Any]] = []
    for item in audit.get("missing_graphics_refs", []):
        candidates = find_asset_candidates(str(item.get("ref", "")), files, candidate_limit)
        rows.append(
            {
                "review_id": stable_review_id(
                    "MAR",
                    item.get("question_id"),
                    item.get("legacy_id"),
                    item.get("ref"),
                ),
                "review_status": "pending",
                "suggested_action": "locate_file",
                "question_id": item.get("question_id", ""),
                "legacy_id": item.get("legacy_id", ""),
                "legacy_file_path": item.get("legacy_file_path", ""),
                "missing_ref": item.get("ref", ""),
                "candidate_count": len(candidates),
                "candidate_file_paths": pipe_join(candidates),
                "allowed_actions": "locate_file|replace_ref|create_questionasset|ignore_external|needs_manual_fix",
                "replacement_path": "",
                "reviewer_note": "",
            }
        )
    return rows


def fetch_import_draft_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_exists(conn, "question_import_draft"):
        return []
    rows = conn.execute(
        """
        SELECT
            d.draft_id,
            d.batch_id,
            d.source_item_id,
            d.source_label,
            d.proposed_action,
            d.target_question_id,
            d.review_status,
            d.review_reason,
            d.question_type_id,
            d.difficulty,
            d.tags_json,
            d.note,
            d.official_flag,
            substr(d.stem_tex, 1, 240) AS stem_preview,
            COUNT(a.draft_asset_id) AS asset_count
        FROM question_import_draft d
        LEFT JOIN question_import_draft_asset a ON a.draft_id = d.draft_id
        GROUP BY d.draft_id
        ORDER BY
            CASE d.review_status
                WHEN 'blocked' THEN 0
                WHEN 'needs_review' THEN 1
                WHEN 'ready' THEN 2
                WHEN 'approved' THEN 3
                ELSE 4
            END,
            d.created_at,
            d.draft_id
        """
    ).fetchall()
    result: list[dict[str, Any]] = []
    for row in rows:
        suggested_next_action = "manual_complete_fields" if row["review_status"] == "needs_review" else ""
        result.append(
            {
                "review_id": stable_review_id("IDR", row["draft_id"]),
                "draft_id": row["draft_id"],
                "batch_id": row["batch_id"],
                "source_item_id": row["source_item_id"],
                "source_label": row["source_label"],
                "proposed_action": row["proposed_action"],
                "target_question_id": row["target_question_id"] or "",
                "review_status": row["review_status"],
                "review_reason": row["review_reason"],
                "question_type_id": row["question_type_id"] or "",
                "difficulty": row["difficulty"] or "",
                "tags_json": row["tags_json"],
                "note": row["note"],
                "official_flag": row["official_flag"],
                "stem_preview": one_line(row["stem_preview"]),
                "asset_count": row["asset_count"],
                "suggested_next_action": suggested_next_action,
                "review_decision": "",
                "allowed_next_actions": "manual_complete_fields|mark_ready|reject|keep_as_sample|needs_manual_fix",
                "reviewer_note": "",
            }
        )
    return result


def read_existing_review_rows(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        return {
            str(row.get("review_id") or "").strip(): {
                key: (value or "").strip()
                for key, value in row.items()
            }
            for row in csv.DictReader(file)
            if str(row.get("review_id") or "").strip()
        }


def preserve_existing_fields(
    path: Path,
    rows: list[dict[str, Any]],
    preserve_fields: list[str],
) -> list[dict[str, Any]]:
    existing_rows = read_existing_review_rows(path)
    if not existing_rows:
        return rows
    merged_rows: list[dict[str, Any]] = []
    for row in rows:
        merged = dict(row)
        existing = existing_rows.get(str(row.get("review_id") or "").strip())
        if existing:
            for field in preserve_fields:
                if field in merged and existing.get(field):
                    merged[field] = existing[field]
        merged_rows.append(merged)
    return merged_rows


def write_csv(
    path: Path,
    rows: list[dict[str, Any]],
    *,
    overwrite: bool,
    preserve_fields: list[str] | None = None,
) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"文件已存在，避免覆盖：{path}")
    if overwrite and preserve_fields:
        rows = preserve_existing_fields(path, rows, preserve_fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(rows[0].keys()) if rows else ["review_id", "review_status", "reviewer_note"]
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def markdown_csv_paths(csv_paths: dict[str, str]) -> str:
    return "\n".join(f"- {name}：`{path}`" for name, path in csv_paths.items()) or "- 未生成"


def markdown_rows(rows: list[dict[str, Any]], label_keys: list[str], limit: int = 20) -> str:
    if not rows:
        return "无"
    lines = []
    for row in rows[:limit]:
        parts = [f"{key}={row.get(key, '')}" for key in label_keys]
        lines.append("- " + "；".join(parts))
    if len(rows) > limit:
        lines.append(f"- 另有 {len(rows) - limit} 项未展示")
    return "\n".join(lines)


def write_report(
    report: dict[str, Any],
    *,
    md_path: Path,
    json_path: Path,
) -> None:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_path.write_text(
        f"""# 数据 warning 人工审查包

> 生成时间：{report['created_at']}  
> 数据库：`{report['database']}`  
> 执行方式：只读扫描数据库；只生成报告和可编辑审查 CSV，不修改 SQLite、不修改 `.tex`。

## 总览

| 项目 | 数量 |
| --- | ---: |
| 数据库审计 blocker | {report['audit_blocker_count']} |
| 数据库审计 warning | {report['audit_warning_count']} |
| 重复试卷题位 | {report['duplicate_position_count']} |
| 缺失图片引用 | {report['missing_asset_count']} |
| 导入草稿 | {report['import_draft_count']} |
| `needs_review` 草稿 | {report['needs_review_draft_count']} |

## 生成的审查 CSV

{markdown_csv_paths(report['csv_paths'])}

## 重复试卷题位样例

{markdown_rows(report['duplicate_position_rows'], ['review_id', 'year', 'paper_name', 'track', 'question_number', 'question_ids'])}

## 缺失图片引用样例

{markdown_rows(report['missing_asset_rows'], ['review_id', 'question_id', 'missing_ref', 'candidate_count'])}

## 导入草稿样例

{markdown_rows(report['import_draft_rows'], ['draft_id', 'review_status', 'review_reason', 'stem_preview'])}

## 建议处理顺序

1. 先看 `paper_position_review`：判断同卷同题号重复到底是小题、跨知识板块重复收录，还是真重复。
2. 再看 `missing_asset_review`：找回原图，或决定把旧 `includegraphics` 迁成 `questionasset` 占位符。
3. 最后看 `import_draft_review`：示例草稿不应进入正式库；真实草稿必须补齐答案、解答和图片关系后再标记 ready。
4. 人工审查完成后，再新增“应用审查决策”的 dry-run 脚本，不要直接改正式库。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="生成数据库 warning 的人工审查包。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 预览数据库路径。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    parser.add_argument("--review-dir", default=str(DEFAULT_REVIEW_DIR), help="审查 CSV 输出目录。")
    parser.add_argument("--write-review-csvs", action="store_true", help="同时生成可人工编辑的审查 CSV。")
    parser.add_argument("--overwrite", action="store_true", help="允许覆盖同名审查 CSV。")
    parser.add_argument("--candidate-limit", type=int, default=8, help="每个缺失图片最多展示多少个候选文件。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = resolve_project_path(args.db)
    review_dir = resolve_project_path(args.review_dir)
    ensure_inside_project(db_path)
    ensure_inside_project(review_dir)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        audit = audit_database(db_path)
        duplicate_rows = fetch_duplicate_position_rows(conn)
        missing_asset_rows = fetch_missing_asset_rows(audit, candidate_limit=max(1, args.candidate_limit))
        import_draft_rows = fetch_import_draft_rows(conn)
    finally:
        conn.close()

    csv_paths: dict[str, str] = {}
    if args.write_review_csvs:
        csv_specs = {
            "paper_position_review": review_dir / f"paper_position_review_{args.stamp}.csv",
            "missing_asset_review": review_dir / f"missing_asset_review_{args.stamp}.csv",
            "import_draft_review": review_dir / f"import_draft_review_{args.stamp}.csv",
        }
        write_csv(
            csv_specs["paper_position_review"],
            duplicate_rows,
            overwrite=args.overwrite,
            preserve_fields=["review_status", "suggested_action", "reviewer_note"],
        )
        write_csv(
            csv_specs["missing_asset_review"],
            missing_asset_rows,
            overwrite=args.overwrite,
            preserve_fields=["review_status", "suggested_action", "replacement_path", "reviewer_note"],
        )
        write_csv(
            csv_specs["import_draft_review"],
            import_draft_rows,
            overwrite=args.overwrite,
            preserve_fields=["review_decision", "reviewer_note"],
        )
        csv_paths = {name: relative_to_root(path) for name, path in csv_specs.items()}

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "database": relative_to_root(db_path),
        "audit_status": audit["status"],
        "audit_blocker_count": len(audit.get("blockers") or []),
        "audit_warning_count": len(audit.get("warnings") or []),
        "duplicate_position_count": len(duplicate_rows),
        "missing_asset_count": len(missing_asset_rows),
        "import_draft_count": len(import_draft_rows),
        "needs_review_draft_count": sum(1 for row in import_draft_rows if row["review_status"] == "needs_review"),
        "csv_paths": csv_paths,
        "duplicate_position_rows": duplicate_rows,
        "missing_asset_rows": missing_asset_rows,
        "import_draft_rows": import_draft_rows,
    }
    md_path = REPORTS_DIR / f"data_warning_review_pack_{args.stamp}.md"
    json_path = REPORTS_DIR / f"data_warning_review_pack_{args.stamp}.json"
    write_report(report, md_path=md_path, json_path=json_path)

    print(f"audit_status={report['audit_status']}")
    print(f"duplicate_positions={report['duplicate_position_count']}")
    print(f"missing_assets={report['missing_asset_count']}")
    print(f"import_drafts={report['import_draft_count']}")
    print(f"needs_review_drafts={report['needs_review_draft_count']}")
    print(f"review_csvs={len(csv_paths)}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
