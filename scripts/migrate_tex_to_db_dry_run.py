from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from collections import defaultdict
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from scan_tex_library import (
    CHAPTERS_DIR,
    PROJECT_ROOT,
    REPORTS_DIR,
    extract_env,
    extract_problem_header,
    iter_question_tex_files,
    parse_meta,
    read_text,
    relative_to_root,
    scan_file,
)


DATA_DIR = PROJECT_ROOT / "data"
SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
PROBLEM_ENV_PATTERN = re.compile(
    r"\\begin\{problem\}(?:\{[^{}]*\}){0,5}(?P<body>[\s\S]*?)\\end\{problem\}",
    re.MULTILINE,
)
CHOICE_BLOCK_PATTERN = re.compile(
    r"\\begin\{choices\}(?P<body>[\s\S]*?)\\end\{choices\}",
    re.MULTILINE,
)
CHOICE_ITEM_PATTERN = re.compile(r"\\choice\s*\{(?P<body>[\s\S]*?)\}", re.MULTILINE)


def natural_key(path: Path) -> list[object]:
    relative = relative_to_root(path)
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", relative)]


def make_question_id(index: int) -> str:
    return f"Q{index:06d}"


def make_relation_id(prefix: str, index: int) -> str:
    return f"{prefix}{index:06d}"


def stable_suffix(*values: object, length: int = 10) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def make_knowledge_area_id(name: str) -> str:
    return f"KA{stable_suffix(name, length=10)}"


def make_equivalence_id(question_id_a: str, question_id_b: str, relation_type: str) -> str:
    return f"QE{stable_suffix(question_id_a, question_id_b, relation_type, length=12)}"


def normalize_stem_for_equivalence(text: str) -> str:
    result = text or ""
    for old, new in [
        (" ", ""),
        ("\r", ""),
        ("\n", ""),
        ("\t", ""),
        ("．", "."),
        ("，", ","),
        ("。", "."),
    ]:
        result = result.replace(old, new)
    return result


def extract_balanced_brace(text: str, open_brace_index: int) -> tuple[str, int] | None:
    if open_brace_index >= len(text) or text[open_brace_index] != "{":
        return None

    depth = 0
    start = open_brace_index + 1
    index = open_brace_index
    while index < len(text):
        char = text[index]
        if char == "\\":
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index].strip(), index + 1
        index += 1
    return None


def extract_choices(choice_block_body: str) -> list[str]:
    choices: list[str] = []
    index = 0
    marker = r"\choice"
    while True:
        choice_index = choice_block_body.find(marker, index)
        if choice_index == -1:
            break
        brace_index = choice_block_body.find("{", choice_index + len(marker))
        if brace_index == -1:
            break
        parsed = extract_balanced_brace(choice_block_body, brace_index)
        if not parsed:
            break
        choice_text, next_index = parsed
        choices.append(choice_text)
        index = next_index
    return choices


def problem_body_without_choices(clean_text: str) -> tuple[str, list[str]]:
    match = PROBLEM_ENV_PATTERN.search(clean_text)
    if not match:
        return "", []

    body = match.group("body").strip()
    choices: list[str] = []
    choice_block = CHOICE_BLOCK_PATTERN.search(body)
    if choice_block:
        block_body = choice_block.group("body")
        choices = extract_choices(block_body)
        body = CHOICE_BLOCK_PATTERN.sub("", body).strip()
    return body, choices


def parse_int(value: str | None) -> int | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    try:
        return int(stripped)
    except ValueError:
        return None


def infer_question_type_id(choices: list[str], answer_tex: str, header_number: str) -> int:
    if choices:
        return 1
    number = parse_int(header_number)
    if number is not None and number <= 16:
        return 3
    if answer_tex.strip() or number is not None and number >= 17:
        return 4
    return 5


def init_database(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    schema = SCHEMA_PATH.read_text(encoding="utf-8")
    conn.executescript(schema)
    return conn


def insert_question(
    conn: sqlite3.Connection,
    question_id: str,
    path: Path,
    source_index: int,
) -> dict[str, object]:
    text = read_text(path)
    meta, clean_text = parse_meta(text)
    header = extract_problem_header(clean_text)
    stem_tex, choices = problem_body_without_choices(clean_text)
    answer_tex = extract_env(clean_text, "answer")
    solution_tex = extract_env(clean_text, "solutions")
    scan_record = scan_file(path)

    question_type_id = infer_question_type_id(choices, answer_tex, header.get("number", ""))
    difficulty = parse_int(meta.get("难度星级"))
    tags = [item.strip() for item in re.split(r"[，,]", meta.get("标签", "")) if item.strip()]
    usage_count = parse_int(meta.get("组卷引用次数")) or 0

    conn.execute(
        """
        INSERT INTO question(
            question_id, question_type_id, stem_tex, choices_json, answer_tex, solution_tex,
            difficulty, tags_json, note, canonical_tex, raw_source_tex, normalized_status,
            legacy_id, legacy_file_path, usage_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_id,
            question_type_id,
            stem_tex,
            json.dumps(choices, ensure_ascii=False),
            answer_tex,
            solution_tex,
            difficulty,
            json.dumps(tags, ensure_ascii=False),
            meta.get("备注", ""),
            clean_text,
            text,
            "raw",
            meta.get("ID", ""),
            relative_to_root(path),
            usage_count,
        ),
    )

    conn.execute(
        """
        INSERT INTO question_analysis(question_id)
        VALUES (?)
        """,
        (question_id,),
    )

    if scan_record.chapter:
        knowledge_area_id = make_knowledge_area_id(scan_record.chapter)
        conn.execute(
            """
            INSERT OR IGNORE INTO knowledge_area(knowledge_area_id, name)
            VALUES (?, ?)
            """,
            (knowledge_area_id, scan_record.chapter),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO question_knowledge_area(
                question_id, knowledge_area_id, source, confidence, is_primary
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            (question_id, knowledge_area_id, "legacy_directory", 1.0, 1),
        )

    conn.execute(
        """
        INSERT INTO legacy_question_map(
            question_id, legacy_id, legacy_file_path, content_hash, detected_chapter,
            detected_year, detected_source, detected_question_number, detected_topic,
            scan_status, scan_note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question_id,
            meta.get("ID", ""),
            relative_to_root(path),
            scan_record.content_hash,
            scan_record.chapter,
            parse_int(header.get("year")),
            header.get("source", ""),
            header.get("number", ""),
            header.get("topic", ""),
            scan_record.status,
            scan_record.warnings,
        ),
    )

    paper_id = None
    paper_question_id = None
    year = parse_int(header.get("year"))
    source = header.get("source", "")
    category = header.get("category", "")
    if year or source:
        track = ""
        if "文" in source:
            track = "文科"
        elif "理" in source:
            track = "理科"
        elif "新高考" in source:
            track = "新高考"

        paper_id = f"P{year or 0:04d}_{stable_suffix(year, category, track, source)}"
        conn.execute(
            """
            INSERT OR IGNORE INTO paper(
                paper_id, year, paper_series, track, paper_name, source_name
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (paper_id, year, category, track, source or "未知试卷", source),
        )

        paper_question_id = make_relation_id("PQ", source_index)
        conn.execute(
            """
            INSERT OR IGNORE INTO paper_question(
                paper_question_id, paper_id, question_id, question_number, sub_number,
                display_order, origin_tex
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                paper_question_id,
                paper_id,
                question_id,
                header.get("number", ""),
                "",
                parse_int(header.get("number")) or source_index,
                "",
            ),
        )

    return {
        "question_id": question_id,
        "legacy_id": meta.get("ID", ""),
        "legacy_file_path": relative_to_root(path),
        "paper_id": paper_id,
        "paper_question_id": paper_question_id,
        "scan_status": scan_record.status,
        "warnings": scan_record.warnings,
        "detected_year": header.get("year", ""),
        "detected_source": header.get("source", ""),
        "detected_question_number": header.get("number", ""),
        "detected_topic": header.get("topic", ""),
        "choice_count": len(choices),
        "stem_key": normalize_stem_for_equivalence(stem_tex),
    }


def insert_equivalence_candidates(conn: sqlite3.Connection, rows: list[dict[str, object]]) -> int:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        stem_key = str(row.get("stem_key") or "")
        if stem_key:
            grouped[stem_key].append(row)

    inserted = 0
    for group in grouped.values():
        if len(group) < 2:
            continue
        sorted_group = sorted(group, key=lambda item: str(item["question_id"]))
        for index, left in enumerate(sorted_group):
            for right in sorted_group[index + 1 :]:
                question_id_a = str(left["question_id"])
                question_id_b = str(right["question_id"])
                conn.execute(
                    """
                    INSERT OR IGNORE INTO question_equivalence(
                        equivalence_id, question_id_a, question_id_b, relation_type,
                        confidence, review_status, note
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        make_equivalence_id(question_id_a, question_id_b, "same_stem"),
                        question_id_a,
                        question_id_b,
                        "same_stem",
                        1.0,
                        "pending",
                        "dry-run detected identical normalized stem",
                    ),
                )
                inserted += 1
    return inserted


def write_markdown_report(rows: list[dict[str, object]], db_path: Path, report_path: Path) -> None:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    warning_rows = [row for row in rows if row["warnings"]]
    paper_count = len({row["paper_id"] for row in rows if row["paper_id"]})
    knowledge_area_count = len({row["detected_topic"] or "" for row in rows if row["detected_topic"]})

    sample = "\n".join(
        f"- `{row['question_id']}` ← `{row['legacy_file_path']}`"
        f"；旧 ID `{row['legacy_id']}`；来源 `{row['detected_year']} {row['detected_source']} {row['detected_question_number']}`"
        for row in rows[:20]
    )
    warning_sample = "\n".join(
        f"- `{row['question_id']}`：`{row['legacy_file_path']}`；警告 `{row['warnings']}`"
        for row in warning_rows[:20]
    ) or "无"

    report_path.write_text(
        f"""# TeX 到 SQLite 迁移 Dry-run 报告

> 生成时间：{now}  
> 预览数据库：`{relative_to_root(db_path)}`  
> 迁移方式：dry-run，生成新的预览数据库，不修改任何 `.tex` 文件。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 预览迁移题目数 | {len(rows)} |
| 预览试卷数 | {paper_count} |
| 预览知识板块数 | {knowledge_area_count} |
| 含警告题目数 | {len(warning_rows)} |

## 前 20 条 ID 映射样例

{sample}

## 警告样例

{warning_sample}

## 说明

- 本次生成的 `question_id` 采用相对路径排序后的 `Q000001` 格式。
- 旧 `% ID` 已保存为 `legacy_id`。
- 原始 `.tex` 路径已保存为 `legacy_file_path`。
- 当前脚本只用于验证 schema、字段解析和迁移方向，不作为正式入库。
- 正式迁移前需要先检查扫描报告中的图片引用缺失问题。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="把现有 TeX 题库迁移到预览 SQLite，不修改源文件。")
    parser.add_argument("--root", default=str(CHAPTERS_DIR), help="题库目录，默认 chapters。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="输出时间戳。")
    parser.add_argument("--limit", type=int, default=0, help="仅迁移前 N 个文件，用于快速测试。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root = root.resolve()

    db_path = DATA_DIR / f"mathcyclus_preview_{args.stamp}.sqlite3"
    report_path = REPORTS_DIR / f"tex_to_db_dry_run_{args.stamp}.md"
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    files = sorted(iter_question_tex_files(root), key=natural_key)
    if args.limit > 0:
        files = files[: args.limit]

    conn = init_database(db_path)
    rows: list[dict[str, object]] = []
    with conn:
        for index, path in enumerate(files, start=1):
            rows.append(insert_question(conn, make_question_id(index), path, index))
        equivalence_count = insert_equivalence_candidates(conn, rows)
    conn.close()

    write_markdown_report(rows, db_path, report_path)

    print(f"questions={len(rows)}")
    print(f"equivalence_candidates={equivalence_count}")
    print(f"database={relative_to_root(db_path)}")
    print(f"report={relative_to_root(report_path)}")


if __name__ == "__main__":
    main()
