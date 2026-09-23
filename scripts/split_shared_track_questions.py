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
BACKUP_ROOT = PROJECT_ROOT / ".backups" / "split_shared_track_questions"
REPORTS_DIR = PROJECT_ROOT / "reports"

TARGET_TRACKS = [
    {"track": "文科", "source_name": "浙江卷（文）", "legacy_suffix": "W"},
    {"track": "理科", "source_name": "浙江卷（理）", "legacy_suffix": "L"},
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def stable_id(prefix: str, *values: object, length: int = 10) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def stable_relation_id(prefix: str, *values: object, length: int = 12) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


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
        raise ValueError(f"路径不在项目目录内：{path}") from exc


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


def file_hash(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()[:16]


def fetch_question_bundle(conn: sqlite3.Connection, question_id: str) -> dict[str, Any]:
    question = conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone()
    if question is None:
        raise ValueError(f"题目不存在：{question_id}")

    paper_links = [
        dict(row)
        for row in conn.execute(
            """
            SELECT
                pq.*,
                p.year,
                p.paper_series,
                p.track,
                p.paper_name,
                p.source_name
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            WHERE pq.question_id = ?
            ORDER BY p.year, p.paper_name, pq.question_number
            """,
            (question_id,),
        ).fetchall()
    ]
    if len(paper_links) != 1:
        raise ValueError(f"{question_id} 当前 paper_question 关系数量为 {len(paper_links)}，需要正好 1 条")

    legacy = conn.execute("SELECT * FROM legacy_question_map WHERE question_id = ?", (question_id,)).fetchone()
    if legacy is None:
        raise ValueError(f"{question_id} 缺少 legacy_question_map，不能安全复制旧文件")

    return {
        "question": dict(question),
        "paper_link": paper_links[0],
        "legacy": dict(legacy),
        "knowledge_links": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM question_knowledge_area WHERE question_id = ?",
                (question_id,),
            ).fetchall()
        ],
        "analysis": dict(row)
        if (row := conn.execute("SELECT * FROM question_analysis WHERE question_id = ?", (question_id,)).fetchone())
        else None,
        "assets": [
            dict(row)
            for row in conn.execute(
                "SELECT * FROM question_asset WHERE question_id = ? ORDER BY sort_order, asset_id",
                (question_id,),
            ).fetchall()
        ],
    }


def next_question_ids(conn: sqlite3.Connection, count: int) -> list[str]:
    max_number = int(
        conn.execute(
            "SELECT COALESCE(MAX(CAST(SUBSTR(question_id, 2) AS INTEGER)), 0) FROM question WHERE question_id GLOB 'Q[0-9]*'"
        ).fetchone()[0]
    )
    return [f"Q{number:06d}" for number in range(max_number + 1, max_number + count + 1)]


def target_legacy_path(source_path: str, source_name: str) -> Path:
    path = PROJECT_ROOT / source_path
    ensure_inside_project(path)
    filename = path.name
    if "浙江卷（文、理）" in filename:
        filename = filename.replace("浙江卷（文、理）", source_name)
    elif "浙江卷" in filename:
        filename = filename.replace("浙江卷", source_name, 1)
    else:
        filename = f"{path.stem}-{source_name}{path.suffix}"
    target = path.with_name(filename).resolve()
    ensure_inside_project(target)
    return target


def rewrite_problem_header(tex: str, *, year: Any, paper_series: str, source_name: str, number: str, topic: str) -> str:
    content = tex or ""
    header = (
        f"\\begin{{problem}}{{{year or ''}}}{{{paper_series or 'G'}}}"
        f"{{{source_name}}}{{{number or ''}}}{{{topic or ''}}}"
    )
    pattern = re.compile(
        r"\\begin\{problem\}"
        r"\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}",
        re.MULTILINE,
    )
    if pattern.search(content):
        return pattern.sub(lambda _match: header, content, count=1)
    return header + "\n" + content


def rewrite_legacy_id(tex: str, legacy_id: str) -> str:
    content = tex or ""
    if re.search(r"(?m)^%\s*ID\s*:", content):
        return re.sub(r"(?m)^%\s*ID\s*:.*$", f"% ID: {legacy_id}", content, count=1)
    return f"% ID: {legacy_id}\n" + content


def build_target_tex(bundle: dict[str, Any], *, source_name: str, legacy_id: str) -> str:
    question = bundle["question"]
    paper_link = bundle["paper_link"]
    legacy = bundle["legacy"]
    base_tex = question.get("raw_source_tex") or question.get("canonical_tex") or ""
    topic = legacy.get("detected_topic") or legacy.get("detected_chapter") or ""
    content = rewrite_problem_header(
        base_tex,
        year=paper_link.get("year") or legacy.get("detected_year"),
        paper_series=paper_link.get("paper_series") or "G",
        source_name=source_name,
        number=paper_link.get("question_number") or legacy.get("detected_question_number") or "",
        topic=topic,
    )
    return rewrite_legacy_id(content, legacy_id)


def ensure_target_paper(conn: sqlite3.Connection, *, year: int, paper_series: str, track: str, paper_name: str, source_name: str) -> str:
    row = conn.execute(
        """
        SELECT paper_id
        FROM paper
        WHERE year = ? AND paper_series = ? AND track = ? AND paper_name = ?
        """,
        (year, paper_series, track, paper_name),
    ).fetchone()
    if row:
        return str(row["paper_id"])
    paper_id = stable_id("P", year, paper_series, track, paper_name)
    conn.execute(
        """
        INSERT INTO paper(paper_id, year, paper_series, track, paper_name, source_name, description)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (paper_id, year, paper_series, track, paper_name, source_name, "由文理共用题拆分时创建"),
    )
    return paper_id


def insert_question_copy(
    conn: sqlite3.Connection,
    *,
    bundle: dict[str, Any],
    new_question_id: str,
    target_paper_id: str,
    target_track: str,
    target_source_name: str,
    target_legacy_id: str,
    target_file_path: str,
    target_tex: str,
) -> dict[str, Any]:
    question = dict(bundle["question"])
    paper_link = bundle["paper_link"]
    legacy = bundle["legacy"]
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    question.update(
        {
            "question_id": new_question_id,
            "legacy_id": target_legacy_id,
            "legacy_file_path": target_file_path,
            "canonical_tex": target_tex,
            "raw_source_tex": target_tex,
            "created_at": now,
            "updated_at": now,
            "last_manual_edit_at": now,
        }
    )
    columns = [row["name"] for row in conn.execute("PRAGMA table_info(question)").fetchall()]
    conn.execute(
        f"INSERT INTO question({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
        [question.get(column) for column in columns],
    )

    if bundle.get("analysis"):
        analysis = dict(bundle["analysis"])
        analysis["question_id"] = new_question_id
        columns = [row["name"] for row in conn.execute("PRAGMA table_info(question_analysis)").fetchall()]
        conn.execute(
            f"INSERT INTO question_analysis({', '.join(columns)}) VALUES ({', '.join('?' for _ in columns)})",
            [analysis.get(column) for column in columns],
        )

    for link in bundle["knowledge_links"]:
        conn.execute(
            """
            INSERT OR IGNORE INTO question_knowledge_area(
                question_id, knowledge_area_id, source, confidence, is_primary, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                new_question_id,
                link["knowledge_area_id"],
                link.get("source") or "split_shared_track",
                link.get("confidence"),
                link.get("is_primary") or 0,
                now,
            ),
        )

    topic = legacy.get("detected_topic") or legacy.get("detected_chapter") or ""
    conn.execute(
        """
        INSERT INTO legacy_question_map(
            question_id, legacy_id, legacy_file_path, content_hash, detected_chapter,
            detected_year, detected_source, detected_question_number, detected_topic,
            scan_status, scan_note, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            new_question_id,
            target_legacy_id,
            target_file_path,
            hashlib.sha1(target_tex.encode("utf-8")).hexdigest()[:16],
            legacy.get("detected_chapter") or topic,
            paper_link.get("year") or legacy.get("detected_year"),
            target_source_name,
            paper_link.get("question_number") or legacy.get("detected_question_number") or "",
            topic,
            "ok",
            "split_shared_track_from_" + str(question.get("question_id") or ""),
            now,
            now,
        ),
    )

    paper_question_id = stable_relation_id(
        "PQ",
        target_paper_id,
        new_question_id,
        paper_link.get("question_number") or "",
        paper_link.get("sub_number") or "",
    )
    conn.execute(
        """
        INSERT INTO paper_question(
            paper_question_id, paper_id, question_id, question_number, sub_number,
            display_order, origin_tex, location_tex, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_question_id,
            target_paper_id,
            new_question_id,
            paper_link.get("question_number") or "",
            paper_link.get("sub_number") or "",
            paper_link.get("display_order") or 0,
            paper_link.get("origin_tex") or "",
            paper_link.get("location_tex") or "",
            now,
            now,
        ),
    )

    return {
        "question_id": new_question_id,
        "legacy_id": target_legacy_id,
        "track": target_track,
        "paper_id": target_paper_id,
        "paper_question_id": paper_question_id,
        "legacy_file_path": target_file_path,
    }


def copy_assets_for_target(
    conn: sqlite3.Connection,
    *,
    bundle: dict[str, Any],
    new_question_id: str,
) -> list[dict[str, Any]]:
    copied: list[dict[str, Any]] = []
    for asset in bundle["assets"]:
        source_path = Path(str(asset.get("file_path") or ""))
        if not source_path.is_absolute():
            source_path = PROJECT_ROOT / source_path
        target_relative = Path("assets") / "questions" / new_question_id / source_path.name
        target_path = PROJECT_ROOT / target_relative
        if source_path.exists():
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
            target_file_hash = file_hash(target_path)
        else:
            target_file_hash = str(asset.get("file_hash") or "")

        asset_id = stable_relation_id(
            "QA",
            new_question_id,
            asset.get("role") or "",
            asset.get("original_file_name") or source_path.name,
            asset.get("sort_order") or 0,
        )
        conn.execute(
            """
            INSERT INTO question_asset(
                asset_id, question_id, role, file_path, original_file_name,
                mime_type, width, height, file_hash, caption, sort_order, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                new_question_id,
                asset.get("role") or "problem",
                target_relative.as_posix(),
                asset.get("original_file_name") or source_path.name,
                asset.get("mime_type") or "",
                asset.get("width"),
                asset.get("height"),
                target_file_hash,
                asset.get("caption") or "",
                asset.get("sort_order") or 0,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            ),
        )
        copied.append(
            {
                "asset_id": asset_id,
                "source": relative_to_root(source_path),
                "target": target_relative.as_posix(),
                "source_exists": source_path.exists(),
            }
        )
    return copied


def move_original_legacy_file(source_relative: str, quarantine_root: Path) -> dict[str, Any]:
    source = PROJECT_ROOT / source_relative
    ensure_inside_project(source)
    if not source.exists():
        return {"source": source_relative, "status": "missing", "quarantine_path": ""}
    target = quarantine_root / source.relative_to(PROJECT_ROOT)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        target = target.with_name(f"{target.stem}_{datetime.now().strftime('%H%M%S')}{target.suffix}")
    shutil.move(str(source), str(target))
    return {
        "source": source_relative,
        "status": "moved",
        "quarantine_path": relative_to_root(target),
    }


def remove_empty_papers(conn: sqlite3.Connection, paper_ids: set[str]) -> list[dict[str, Any]]:
    removed: list[dict[str, Any]] = []
    for paper_id in sorted(paper_ids):
        count = int(
            conn.execute(
                "SELECT COUNT(*) FROM paper_question WHERE paper_id = ?",
                (paper_id,),
            ).fetchone()[0]
        )
        if count != 0:
            continue
        row = conn.execute("SELECT * FROM paper WHERE paper_id = ?", (paper_id,)).fetchone()
        if row:
            removed.append(dict(row))
            conn.execute("DELETE FROM paper WHERE paper_id = ?", (paper_id,))
    return removed


def split_questions(db_path: Path, question_ids: list[str], *, apply: bool, stamp: str) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在：{db_path}")

    with connect_database(db_path) as conn:
        bundles = [fetch_question_bundle(conn, question_id) for question_id in question_ids]
        allocated_ids = next_question_ids(conn, len(question_ids) * len(TARGET_TRACKS))

    planned: list[dict[str, Any]] = []
    id_iter = iter(allocated_ids)
    for bundle in bundles:
        question = bundle["question"]
        paper_link = bundle["paper_link"]
        legacy = bundle["legacy"]
        old_legacy_id = str(question.get("legacy_id") or legacy.get("legacy_id") or question["question_id"])
        for target in TARGET_TRACKS:
            new_question_id = next(id_iter)
            target_legacy_id = f"{old_legacy_id}-{target['legacy_suffix']}"
            target_path = target_legacy_path(str(legacy["legacy_file_path"]), str(target["source_name"]))
            target_tex = build_target_tex(bundle, source_name=str(target["source_name"]), legacy_id=target_legacy_id)
            planned.append(
                {
                    "source_question_id": question["question_id"],
                    "source_paper_id": paper_link["paper_id"],
                    "new_question_id": new_question_id,
                    "target_legacy_id": target_legacy_id,
                    "target_track": target["track"],
                    "target_source_name": target["source_name"],
                    "target_paper_name": "浙江卷",
                    "year": paper_link.get("year") or legacy.get("detected_year"),
                    "paper_series": paper_link.get("paper_series") or "G",
                    "question_number": paper_link.get("question_number") or legacy.get("detected_question_number") or "",
                    "sub_number": paper_link.get("sub_number") or "",
                    "target_legacy_file_path": relative_to_root(target_path),
                    "target_tex": target_tex,
                    "target_exists": target_path.exists(),
                }
            )

    report: dict[str, Any] = {
        "stamp": stamp,
        "mode": "apply" if apply else "dry_run",
        "database": relative_to_root(db_path),
        "source_question_ids": question_ids,
        "planned": [{key: value for key, value in item.items() if key != "target_tex"} for item in planned],
        "created_questions": [],
        "moved_original_files": [],
        "removed_source_papers": [],
        "database_backup": "",
        "integrity_check": "not_run_in_dry_run",
        "foreign_key_errors": [],
    }

    if not apply:
        return report

    collisions = [item["target_legacy_file_path"] for item in planned if item["target_exists"]]
    if collisions:
        raise FileExistsError("目标旧 TeX 文件已存在，已拒绝覆盖：" + " | ".join(collisions))

    quarantine_root = BACKUP_ROOT / stamp
    backup_db = quarantine_root / "mathcyclus_before_split.sqlite3"
    copy_sqlite_database(db_path, backup_db)
    report["database_backup"] = relative_to_root(backup_db)

    for item in planned:
        target_path = PROJECT_ROOT / item["target_legacy_file_path"]
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_text(str(item["target_tex"]), encoding="utf-8")

    with connect_database(db_path) as conn:
        source_paper_ids = {bundle["paper_link"]["paper_id"] for bundle in bundles}
        created_by_source: dict[str, list[str]] = {}
        bundle_by_source = {bundle["question"]["question_id"]: bundle for bundle in bundles}

        for item in planned:
            bundle = bundle_by_source[str(item["source_question_id"])]
            target_paper_id = ensure_target_paper(
                conn,
                year=int(item["year"]),
                paper_series=str(item["paper_series"]),
                track=str(item["target_track"]),
                paper_name=str(item["target_paper_name"]),
                source_name=str(item["target_source_name"]),
            )
            created = insert_question_copy(
                conn,
                bundle=bundle,
                new_question_id=str(item["new_question_id"]),
                target_paper_id=target_paper_id,
                target_track=str(item["target_track"]),
                target_source_name=str(item["target_source_name"]),
                target_legacy_id=str(item["target_legacy_id"]),
                target_file_path=str(item["target_legacy_file_path"]),
                target_tex=str(item["target_tex"]),
            )
            created["assets"] = copy_assets_for_target(
                conn,
                bundle=bundle,
                new_question_id=str(item["new_question_id"]),
            )
            report["created_questions"].append(created)
            created_by_source.setdefault(str(item["source_question_id"]), []).append(str(item["new_question_id"]))

        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for source_question_id, new_ids in created_by_source.items():
            for left_index, left_id in enumerate(new_ids):
                for right_id in new_ids[left_index + 1 :]:
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO question_equivalence(
                            equivalence_id, question_id_a, question_id_b, relation_type,
                            confidence, review_status, note, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            stable_relation_id("QE", left_id, right_id, "same_shared_track_source"),
                            left_id,
                            right_id,
                            "same_shared_track_source",
                            1.0,
                            "approved",
                            f"由 {source_question_id} 拆分为文科/理科副本",
                            now,
                        ),
                    )

        for bundle in bundles:
            conn.execute("DELETE FROM question WHERE question_id = ?", (bundle["question"]["question_id"],))
            moved = move_original_legacy_file(str(bundle["legacy"]["legacy_file_path"]), quarantine_root)
            moved["question_id"] = bundle["question"]["question_id"]
            report["moved_original_files"].append(moved)

        report["removed_source_papers"] = remove_empty_papers(conn, source_paper_ids)
        report["integrity_check"] = str(conn.execute("PRAGMA integrity_check").fetchone()[0])
        report["foreign_key_errors"] = [dict(row) for row in conn.execute("PRAGMA foreign_key_check").fetchall()]
        conn.commit()

    manifest_path = quarantine_root / "manifest.json"
    manifest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["manifest"] = relative_to_root(manifest_path)
    return report


def write_report(report: dict[str, Any], report_path: Path) -> None:
    planned_lines = []
    for item in report["planned"]:
        planned_lines.append(
            f"| `{item['source_question_id']}` | `{item['new_question_id']}` | {item['target_track']} | "
            f"{item['target_source_name']} | {item['question_number']} | `{item['target_legacy_file_path']}` |"
        )
    moved_lines = []
    for item in report["moved_original_files"]:
        moved_lines.append(
            f"| `{item.get('question_id') or ''}` | {item.get('status') or ''} | "
            f"`{item.get('source') or ''}` | `{item.get('quarantine_path') or ''}` |"
        )
    removed_paper_lines = []
    for paper in report["removed_source_papers"]:
        removed_paper_lines.append(
            f"| `{paper.get('paper_id')}` | {paper.get('year')} | {paper.get('track')} | "
            f"{paper.get('paper_name')} | {paper.get('source_name')} |"
        )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        f"""# 文理共用题拆分报告

> 模式：{report['mode']}  
> 数据库：`{report['database']}`  
> 数据库备份：`{report.get('database_backup') or 'dry-run 未生成'}`

## 计划拆分

| 原 question_id | 新 question_id | track | 来源名 | 题号 | 新旧文件路径 |
| --- | --- | --- | --- | --- | --- |
{chr(10).join(planned_lines) or '| 无 |  |  |  |  |  |'}

## 原旧 TeX 文件隔离

| 原 question_id | 状态 | 原路径 | 隔离路径 |
| --- | --- | --- | --- |
{chr(10).join(moved_lines) or '| dry-run 未执行 |  |  |  |'}

## 被删除的综合试卷记录

| paper_id | year | track | paper_name | source_name |
| --- | --- | --- | --- | --- |
{chr(10).join(removed_paper_lines) or '| 无 |  |  |  |'}

## 完整性

- `PRAGMA integrity_check`：`{report['integrity_check']}`
- 外键错误数：{len(report['foreign_key_errors'])}
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把文理共用的综合试卷题拆成文科/理科两份。")
    parser.add_argument("question_ids", nargs="+", help="要拆分的原 question_id。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--apply", action="store_true", help="真正写库并复制/隔离旧 TeX；默认只预演。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = resolve_db_path(args.db)
    report = split_questions(
        db_path,
        [str(question_id).strip() for question_id in args.question_ids if str(question_id).strip()],
        apply=bool(args.apply),
        stamp=args.stamp,
    )
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"split_shared_track_questions_{args.stamp}.md"
    write_report(report, report_path)
    print(f"mode={report['mode']}")
    print(f"planned={len(report['planned'])}")
    print(f"created={len(report['created_questions'])}")
    print(f"report={relative_to_root(report_path)}")
    if report.get("database_backup"):
        print(f"database_backup={report['database_backup']}")


if __name__ == "__main__":
    main()
