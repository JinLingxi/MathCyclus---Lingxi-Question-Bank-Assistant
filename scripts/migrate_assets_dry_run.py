from __future__ import annotations

import argparse
import csv
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_DB = PROJECT_ROOT / "data" / "mathcyclus_preview_paper_mapped_20260902_with_knowledge.sqlite3"
DATA_DIR = PROJECT_ROOT / "data"
REPORTS_DIR = PROJECT_ROOT / "reports"
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".svg", ".bmp", ".webp"}
RELATED_FIGURE_MARKER = "相关图"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.asset_service import file_hash, make_asset_id


def relative_to_root(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def find_legacy_question_for_related_asset(asset_path: Path) -> Path | None:
    parent = asset_path.parent
    if RELATED_FIGURE_MARKER not in parent.name:
        return None
    base_name = parent.name.split(RELATED_FIGURE_MARKER, 1)[0].rstrip()
    candidate = parent.parent / f"{base_name}.tex"
    return candidate if candidate.exists() else None


def question_id_by_legacy_path(conn: sqlite3.Connection, legacy_path: Path) -> str:
    relative_path = relative_to_root(legacy_path)
    row = conn.execute(
        "SELECT question_id FROM legacy_question_map WHERE legacy_file_path = ?",
        (relative_path,),
    ).fetchone()
    return str(row[0]) if row else ""


def scan_assets(conn: sqlite3.Connection) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted((PROJECT_ROOT / "chapters").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
            continue
        legacy_question = find_legacy_question_for_related_asset(path)
        question_id = question_id_by_legacy_path(conn, legacy_question) if legacy_question else ""
        role = "problem"
        status = "matched" if question_id else "unmatched"
        asset_id = make_asset_id(question_id or "UNMATCHED", role, path)
        planned_path = f"assets/questions/{question_id}/{path.name}" if question_id else ""
        rows.append(
            {
                "asset_id": asset_id,
                "question_id": question_id,
                "role": role,
                "source_path": relative_to_root(path),
                "legacy_question_path": relative_to_root(legacy_question) if legacy_question else "",
                "planned_path": planned_path,
                "file_hash": file_hash(path),
                "status": status,
                "note": "" if question_id else "未能从相关图目录匹配到题目文件",
            }
        )
    return rows


def insert_asset_records(conn: sqlite3.Connection, rows: list[dict[str, str]], copy_files: bool) -> None:
    for index, row in enumerate(rows, start=1):
        if row["status"] != "matched":
            continue
        file_path = row["planned_path"] if copy_files else row["source_path"]
        conn.execute(
            """
            INSERT OR REPLACE INTO question_asset(
                asset_id, question_id, role, file_path, original_file_name,
                mime_type, file_hash, caption, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["asset_id"],
                row["question_id"],
                row["role"],
                file_path,
                Path(row["source_path"]).name,
                "image/png" if row["source_path"].lower().endswith(".png") else "",
                row["file_hash"],
                "",
                index,
            ),
        )

        if copy_files:
            source = PROJECT_ROOT / row["source_path"]
            target = PROJECT_ROOT / row["planned_path"]
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                shutil.copy2(source, target)


def write_csv(rows: list[dict[str, str]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0].keys()) if rows else ["status"])
        writer.writeheader()
        writer.writerows(rows)


def write_report(rows: list[dict[str, str]], source_db: Path, output_db: Path, csv_path: Path, report_path: Path, copy_files: bool) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    matched = [row for row in rows if row["status"] == "matched"]
    unmatched = [row for row in rows if row["status"] != "matched"]
    sample = "\n".join(
        f"- `{row['question_id']}`：`{row['source_path']}` -> `{row['planned_path'] or row['source_path']}`"
        for row in matched[:30]
    ) or "无"
    unmatched_sample = "\n".join(
        f"- `{row['source_path']}`：{row['note']}"
        for row in unmatched[:30]
    ) or "无"

    report_path.write_text(
        f"""# 图片资产迁移 Dry-run 报告

> 生成时间：{now}  
> 来源数据库：`{relative_to_root(source_db)}`  
> 输出数据库：`{relative_to_root(output_db)}`  
> 明细 CSV：`{relative_to_root(csv_path)}`  
> 执行方式：复制预览库后写入 `question_asset`；copy_files={copy_files}。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 扫描到图片资源 | {len(rows)} |
| 成功匹配题目 | {len(matched)} |
| 未匹配资源 | {len(unmatched)} |

## 匹配样例

{sample}

## 未匹配样例

{unmatched_sample}

## 说明

- 第一版只处理 `chapters/**/相关图/` 目录中的现有图片。
- 当前默认只在数据库副本中登记资产，不移动原始图片。
- 如果启用 `--copy-files`，会复制到 `assets/questions/<question_id>/`，该目录内容默认不进入 Git。
- 缺失的 `includegraphics` 引用不在本脚本中自动补图，仍需人工寻找原始图片。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把旧题库相关图图片登记到预览数据库，不改原题库。")
    parser.add_argument("--source-db", default=str(DEFAULT_SOURCE_DB), help="来源 SQLite 预览库。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    parser.add_argument("--copy-files", action="store_true", help="复制图片到 assets/questions/<question_id>/。默认不复制。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    source_db = Path(args.source_db)
    if not source_db.is_absolute():
        source_db = PROJECT_ROOT / source_db
    source_db = source_db.resolve()
    if not source_db.exists():
        raise SystemExit(f"来源数据库不存在：{source_db}")

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    output_db = DATA_DIR / f"mathcyclus_preview_assets_{args.stamp}.sqlite3"
    csv_path = REPORTS_DIR / f"asset_migration_dry_run_{args.stamp}.csv"
    report_path = REPORTS_DIR / f"asset_migration_dry_run_{args.stamp}.md"

    if output_db.exists():
        output_db.unlink()
    shutil.copy2(source_db, output_db)

    conn = sqlite3.connect(output_db)
    try:
        with conn:
            rows = scan_assets(conn)
            insert_asset_records(conn, rows, copy_files=args.copy_files)
    finally:
        conn.close()

    write_csv(rows, csv_path)
    write_report(rows, source_db, output_db, csv_path, report_path, args.copy_files)

    print(f"assets={len(rows)}")
    print(f"database={relative_to_root(output_db)}")
    print(f"report={relative_to_root(report_path)}")
    print(f"csv={relative_to_root(csv_path)}")


if __name__ == "__main__":
    main()
