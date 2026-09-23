from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
REPORTS_DIR = PROJECT_ROOT / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = db_path.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def normalize_tex_for_compare(tex: str) -> str:
    text = tex or ""
    text = re.sub(r"(?m)%.*$", "", text)
    text = re.sub(r"\\(?:displaystyle|textstyle|left|right)\b", "", text)
    text = text.replace("，", ",").replace("。", ".")
    text = re.sub(r"\s+", "", text)
    return text


def strip_track_suffix(name: str) -> str:
    text = str(name or "").strip()
    text = re.sub(r"[（(]\s*[文理]\s*[）)]$", "", text)
    text = re.sub(r"[（(]\s*文\s*[、,，]\s*理\s*[）)]$", "", text)
    text = text.replace("（文、理）", "").replace("(文、理)", "")
    return text.strip()


def infer_track_from_text(text: str) -> set[str]:
    value = str(text or "")
    expected: set[str] = set()
    if any(token in value for token in ["文、理", "文理", "文理科", "（文、理）", "(文、理)"]):
        expected.add("综合")
    if any(token in value for token in ["文科", "（文）", "(文)", "文卷", "文数"]):
        expected.add("文科")
    if any(token in value for token in ["理科", "（理）", "(理)", "理卷", "理数"]):
        expected.add("理科")
    if "新高考" in value:
        expected.add("新高考")
    return expected


def short_text(value: str, limit: int = 90) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)] + "…"


def markdown_escape(value: Any) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", " ")


def table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def fetch_questions(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT
            q.question_id,
            q.legacy_id,
            q.legacy_file_path,
            q.stem_tex,
            q.choices_json,
            q.answer_tex,
            q.solution_tex,
            q.difficulty,
            q.tags_json,
            q.note,
            q.question_type_id,
            qt.code AS question_type_code,
            qt.name AS question_type_name,
            l.legacy_file_path AS mapped_legacy_file_path,
            l.detected_chapter,
            l.detected_year,
            l.detected_source,
            l.detected_question_number
        FROM question q
        LEFT JOIN question_type qt ON qt.question_type_id = q.question_type_id
        LEFT JOIN legacy_question_map l ON l.question_id = q.question_id
        ORDER BY q.question_id
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_papers(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT paper_id, year, paper_series, track, paper_name, source_name, description
        FROM paper
        ORDER BY year, paper_series, paper_name, track
        """
    ).fetchall()
    return [dict(row) for row in rows]


def fetch_paper_question_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
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
            p.paper_name,
            p.source_name,
            l.legacy_file_path,
            l.detected_question_number
        FROM paper_question pq
        JOIN paper p ON p.paper_id = pq.paper_id
        LEFT JOIN legacy_question_map l ON l.question_id = pq.question_id
        ORDER BY p.year, p.paper_name, CAST(pq.question_number AS INTEGER), pq.question_number, pq.sub_number
        """
    ).fetchall()
    return [dict(row) for row in rows]


def count_table(conn: sqlite3.Connection, table: str) -> int:
    if not table_exists(conn, table):
        return 0
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def build_exact_duplicate_groups(questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for question in questions:
        normalized = normalize_tex_for_compare(question.get("stem_tex") or "")
        if not normalized:
            continue
        key = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        groups[key].append(question)

    result: list[dict[str, Any]] = []
    for fingerprint, items in groups.items():
        if len(items) <= 1:
            continue
        result.append(
            {
                "fingerprint": fingerprint,
                "count": len(items),
                "items": [
                    {
                        "question_id": item.get("question_id"),
                        "legacy_id": item.get("legacy_id"),
                        "legacy_file_path": item.get("legacy_file_path") or item.get("mapped_legacy_file_path"),
                        "detected_chapter": item.get("detected_chapter"),
                        "stem_preview": short_text(item.get("stem_tex") or ""),
                    }
                    for item in items
                ],
            }
        )
    result.sort(key=lambda row: (-row["count"], row["fingerprint"]))
    return result


def build_near_duplicate_pairs(
    questions: list[dict[str, Any]],
    *,
    threshold: float,
    min_length: int,
) -> list[dict[str, Any]]:
    compact: list[tuple[dict[str, Any], str]] = []
    for question in questions:
        normalized = normalize_tex_for_compare(question.get("stem_tex") or "")
        if len(normalized) >= min_length:
            compact.append((question, normalized))

    pairs: list[dict[str, Any]] = []
    for left_index, (left, left_text) in enumerate(compact):
        for right, right_text in compact[left_index + 1 :]:
            max_length = max(len(left_text), len(right_text))
            if not max_length:
                continue
            if abs(len(left_text) - len(right_text)) / max_length > 0.18:
                continue
            ratio = SequenceMatcher(None, left_text, right_text).ratio()
            if threshold <= ratio < 1:
                pairs.append(
                    {
                        "similarity": round(ratio, 4),
                        "left_question_id": left.get("question_id"),
                        "left_legacy_file_path": left.get("legacy_file_path") or left.get("mapped_legacy_file_path"),
                        "right_question_id": right.get("question_id"),
                        "right_legacy_file_path": right.get("legacy_file_path") or right.get("mapped_legacy_file_path"),
                        "left_preview": short_text(left.get("stem_tex") or ""),
                        "right_preview": short_text(right.get("stem_tex") or ""),
                    }
                )
    pairs.sort(key=lambda row: (-float(row["similarity"]), str(row["left_question_id"])))
    return pairs


def build_track_issues(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    allowed_tracks = {"文科", "理科", "新高考", "综合", ""}
    issues: list[dict[str, Any]] = []
    for paper in papers:
        track = str(paper.get("track") or "").strip()
        text = f"{paper.get('paper_name') or ''} {paper.get('source_name') or ''}"
        expected = infer_track_from_text(text)
        if track not in allowed_tracks:
            issues.append({**paper, "issue": "非标准 track", "expected_tracks": sorted(expected)})
            continue
        if expected and track not in expected:
            issues.append({**paper, "issue": "名称暗示的文理/新高考与 track 不一致", "expected_tracks": sorted(expected)})
    return issues


def build_paper_naming_issues(papers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    logical_groups: dict[tuple[Any, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for paper in papers:
        paper_name = str(paper.get("paper_name") or "")
        source_name = str(paper.get("source_name") or "")
        stripped_name = strip_track_suffix(paper_name)
        stripped_source = strip_track_suffix(source_name)
        if stripped_name != paper_name:
            issues.append({**paper, "issue": "paper_name 仍带文/理后缀", "suggested_paper_name": stripped_name})
        if stripped_source and stripped_source != source_name and str(paper.get("track") or "") not in {"文科", "理科", "综合"}:
            issues.append({**paper, "issue": "source_name 带文/理后缀但 track 未承接", "suggested_source_name": stripped_source})
        logical_groups[
            (
                paper.get("year"),
                str(paper.get("paper_series") or ""),
                str(paper.get("track") or ""),
                stripped_name,
            )
        ].append(paper)

    for group_key, items in logical_groups.items():
        if len(items) > 1:
            issues.append(
                {
                    "issue": "清洗后试卷逻辑键重复",
                    "logical_key": group_key,
                    "paper_ids": [item.get("paper_id") for item in items],
                    "paper_names": [item.get("paper_name") for item in items],
                    "source_names": [item.get("source_name") for item in items],
                }
            )
    return issues


def build_relation_issues(conn: sqlite3.Connection, paper_question_rows: list[dict[str, Any]]) -> dict[str, Any]:
    questions_without_paper = [
        dict(row)
        for row in conn.execute(
            """
            SELECT q.question_id, q.legacy_id, q.legacy_file_path, substr(q.stem_tex, 1, 120) AS stem_preview
            FROM question q
            LEFT JOIN paper_question pq ON pq.question_id = q.question_id
            WHERE pq.question_id IS NULL
            ORDER BY q.question_id
            """
        ).fetchall()
    ]
    papers_without_questions = [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.paper_id, p.year, p.paper_series, p.track, p.paper_name, p.source_name
            FROM paper p
            LEFT JOIN paper_question pq ON pq.paper_id = p.paper_id
            WHERE pq.paper_id IS NULL
            ORDER BY p.year, p.paper_name
            """
        ).fetchall()
    ]
    question_without_knowledge = [
        dict(row)
        for row in conn.execute(
            """
            SELECT q.question_id, q.legacy_id, q.legacy_file_path
            FROM question q
            LEFT JOIN question_knowledge_area qka ON qka.question_id = q.question_id
            WHERE qka.question_id IS NULL
            ORDER BY q.question_id
            """
        ).fetchall()
    ]

    duplicate_positions = [
        dict(row)
        for row in conn.execute(
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
    ]

    number_mismatches: list[dict[str, Any]] = []
    for row in paper_question_rows:
        expected = str(row.get("detected_question_number") or "").strip()
        current = str(row.get("question_number") or "").strip()
        if expected and current and expected != current:
            number_mismatches.append(
                {
                    "question_id": row.get("question_id"),
                    "paper_question_id": row.get("paper_question_id"),
                    "paper": f"{row.get('year')} {row.get('paper_name')} {row.get('track')}",
                    "question_number": current,
                    "detected_question_number": expected,
                    "legacy_file_path": row.get("legacy_file_path"),
                }
            )

    return {
        "questions_without_paper": questions_without_paper,
        "papers_without_questions": papers_without_questions,
        "questions_without_knowledge": question_without_knowledge,
        "duplicate_positions": duplicate_positions,
        "number_mismatches": number_mismatches,
    }


def build_field_issues(questions: list[dict[str, Any]]) -> dict[str, Any]:
    invalid_choices: list[dict[str, Any]] = []
    wrapped_choice_rows: list[dict[str, Any]] = []
    missing_difficulty: list[dict[str, Any]] = []
    missing_answer: list[dict[str, Any]] = []
    missing_solution: list[dict[str, Any]] = []
    empty_tags: list[dict[str, Any]] = []

    wrapped_pattern = re.compile(r"^\s*\\choice\s*\{")
    for question in questions:
        question_id = question.get("question_id")
        choices_raw = str(question.get("choices_json") or "[]")
        try:
            choices = json.loads(choices_raw)
            if not isinstance(choices, list):
                raise ValueError("choices_json 不是数组")
        except Exception as exc:
            invalid_choices.append(
                {
                    "question_id": question_id,
                    "legacy_file_path": question.get("legacy_file_path"),
                    "error": str(exc),
                }
            )
            choices = []
        if any(wrapped_pattern.search(str(choice or "")) for choice in choices):
            wrapped_choice_rows.append(
                {
                    "question_id": question_id,
                    "legacy_file_path": question.get("legacy_file_path"),
                    "choices_preview": short_text(json.dumps(choices, ensure_ascii=False), 160),
                }
            )
        if question.get("difficulty") is None:
            missing_difficulty.append({"question_id": question_id, "legacy_file_path": question.get("legacy_file_path")})
        if not str(question.get("answer_tex") or "").strip():
            missing_answer.append({"question_id": question_id, "legacy_file_path": question.get("legacy_file_path")})
        if not str(question.get("solution_tex") or "").strip():
            missing_solution.append({"question_id": question_id, "legacy_file_path": question.get("legacy_file_path")})
        try:
            tags = json.loads(str(question.get("tags_json") or "[]"))
        except json.JSONDecodeError:
            tags = []
        if not tags:
            empty_tags.append({"question_id": question_id, "legacy_file_path": question.get("legacy_file_path")})

    return {
        "invalid_choices": invalid_choices,
        "wrapped_choice_rows": wrapped_choice_rows,
        "missing_difficulty": missing_difficulty,
        "missing_answer": missing_answer,
        "missing_solution": missing_solution,
        "empty_tags": empty_tags,
    }


def top_rows(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    return rows[: max(0, limit)]


def markdown_list_dicts(rows: list[dict[str, Any]], columns: list[str], limit: int) -> str:
    selected = top_rows(rows, limit)
    if not selected:
        return "无"
    header = "| " + " | ".join(columns) + " |\n"
    divider = "| " + " | ".join("---" for _ in columns) + " |\n"
    lines = []
    for row in selected:
        lines.append("| " + " | ".join(markdown_escape(row.get(column)) for column in columns) + " |")
    suffix = ""
    if len(rows) > limit:
        suffix = f"\n\n> 仅展示前 {limit} 条，完整数据见同名 JSON。"
    return header + divider + "\n".join(lines) + suffix


def build_report(db_path: Path, *, near_threshold: float, min_length: int) -> dict[str, Any]:
    with connect_readonly(db_path) as conn:
        questions = fetch_questions(conn)
        papers = fetch_papers(conn)
        paper_question_rows = fetch_paper_question_rows(conn)
        counts = {
            "question": count_table(conn, "question"),
            "paper": count_table(conn, "paper"),
            "paper_question": count_table(conn, "paper_question"),
            "knowledge_area": count_table(conn, "knowledge_area"),
            "question_knowledge_area": count_table(conn, "question_knowledge_area"),
            "question_asset": count_table(conn, "question_asset"),
            "question_revision": count_table(conn, "question_revision"),
            "book": count_table(conn, "book"),
            "book_exercise_question": count_table(conn, "book_exercise_question"),
            "topic": count_table(conn, "topic"),
            "topic_question": count_table(conn, "topic_question"),
        }
        field_issues = build_field_issues(questions)
        relation_issues = build_relation_issues(conn, paper_question_rows)

    exact_duplicate_groups = build_exact_duplicate_groups(questions)
    near_duplicate_pairs = build_near_duplicate_pairs(questions, threshold=near_threshold, min_length=min_length)
    track_issues = build_track_issues(papers)
    paper_naming_issues = build_paper_naming_issues(papers)

    return {
        "database": relative_to_root(db_path),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "parameters": {
            "near_duplicate_threshold": near_threshold,
            "near_duplicate_min_length": min_length,
        },
        "counts": counts,
        "summary": {
            "exact_duplicate_groups": len(exact_duplicate_groups),
            "exact_duplicate_items": sum(int(group["count"]) for group in exact_duplicate_groups),
            "near_duplicate_pairs": len(near_duplicate_pairs),
            "track_issues": len(track_issues),
            "paper_naming_issues": len(paper_naming_issues),
            "questions_without_paper": len(relation_issues["questions_without_paper"]),
            "papers_without_questions": len(relation_issues["papers_without_questions"]),
            "questions_without_knowledge": len(relation_issues["questions_without_knowledge"]),
            "duplicate_positions": len(relation_issues["duplicate_positions"]),
            "number_mismatches": len(relation_issues["number_mismatches"]),
            "invalid_choices": len(field_issues["invalid_choices"]),
            "wrapped_choice_rows": len(field_issues["wrapped_choice_rows"]),
            "missing_difficulty": len(field_issues["missing_difficulty"]),
            "missing_answer": len(field_issues["missing_answer"]),
            "missing_solution": len(field_issues["missing_solution"]),
            "empty_tags": len(field_issues["empty_tags"]),
        },
        "exact_duplicate_groups": exact_duplicate_groups,
        "near_duplicate_pairs": near_duplicate_pairs,
        "track_issues": track_issues,
        "paper_naming_issues": paper_naming_issues,
        "relation_issues": relation_issues,
        "field_issues": field_issues,
    }


def write_markdown(report: dict[str, Any], path: Path, *, sample_limit: int) -> None:
    summary = report["summary"]
    counts = report["counts"]
    exact_rows = []
    for group in report["exact_duplicate_groups"]:
        exact_rows.append(
            {
                "count": group["count"],
                "question_ids": ", ".join(str(item["question_id"]) for item in group["items"]),
                "legacy_paths": "<br>".join(str(item["legacy_file_path"]) for item in group["items"]),
                "preview": group["items"][0]["stem_preview"] if group["items"] else "",
            }
        )

    content = f"""# 数据清洗候选审计报告

> 生成时间：{report['generated_at']}  
> 数据库：`{report['database']}`  
> 性质：只读审计报告，不修改 SQLite、不修改旧 `.tex`。

## 结论摘要

| 项目 | 数量 |
| --- | ---: |
| 题目总数 | {counts['question']} |
| 试卷总数 | {counts['paper']} |
| 试卷-题目关系 | {counts['paper_question']} |
| 题目图片资源 | {counts['question_asset']} |
| 精确重复题干组 | {summary['exact_duplicate_groups']} |
| 高相似题干候选对 | {summary['near_duplicate_pairs']} |
| 文理/新高考标注疑似异常 | {summary['track_issues']} |
| 试卷命名疑似异常 | {summary['paper_naming_issues']} |
| 没有试卷关系的题目 | {summary['questions_without_paper']} |
| 同一试卷同一题位重复 | {summary['duplicate_positions']} |
| 题号与旧路径解析不一致 | {summary['number_mismatches']} |
| 难度为空 | {summary['missing_difficulty']} |
| 标签为空 | {summary['empty_tags']} |

## 优先处理建议

1. 先人工复核精确重复和高相似题干：不要直接删题，优先写入 `question_equivalence` 或补充多来源关系。
2. 再处理没有 `paper_question` 的题：这些题会影响试卷反查和组卷来源展示。
3. 文理/新高考标注目前未发现明显冲突，但仍建议以后以 `paper.track` 为准，不再从题目 TeX 头部推断。
4. 难度目前 {summary['missing_difficulty']} 题为空，属于下一轮批量标注任务，不应和去重混在一次提交里处理。
5. 答案/解析为空数量较多，说明旧库本身大量题只存题干或未结构化拆解，清洗时不要误判为程序错误。

## 精确重复题干候选

{markdown_list_dicts(exact_rows, ['count', 'question_ids', 'legacy_paths', 'preview'], sample_limit)}

## 高相似题干候选

{markdown_list_dicts(report['near_duplicate_pairs'], ['similarity', 'left_question_id', 'left_legacy_file_path', 'right_question_id', 'right_legacy_file_path'], sample_limit)}

## 没有试卷关系的题目

{markdown_list_dicts(report['relation_issues']['questions_without_paper'], ['question_id', 'legacy_id', 'legacy_file_path', 'stem_preview'], sample_limit)}

## 题号与旧路径解析不一致

{markdown_list_dicts(report['relation_issues']['number_mismatches'], ['question_id', 'paper', 'question_number', 'detected_question_number', 'legacy_file_path'], sample_limit)}

## 文理/新高考标注疑似异常

{markdown_list_dicts(report['track_issues'], ['paper_id', 'year', 'paper_series', 'track', 'paper_name', 'source_name', 'issue'], sample_limit)}

## 试卷命名疑似异常

{markdown_list_dicts(report['paper_naming_issues'], ['paper_id', 'year', 'paper_series', 'track', 'paper_name', 'source_name', 'issue'], sample_limit)}

## 字段完整性

| 字段问题 | 数量 | 处理建议 |
| --- | ---: | --- |
| choices_json 非法 | {summary['invalid_choices']} | 必须先修，避免前端选项渲染失败 |
| choices_json 仍包着 `\\choice` | {summary['wrapped_choice_rows']} | 可用现有选项归一化脚本处理 |
| answer_tex 为空 | {summary['missing_answer']} | 后续结合 AI/OCR 或人工补齐 |
| solution_tex 为空 | {summary['missing_solution']} | 后续结合 AI/OCR 或人工补齐 |
| difficulty 为空 | {summary['missing_difficulty']} | 建议单独做批量难度标注 |
| tags_json 为空 | {summary['empty_tags']} | 建议从知识点/来源/AI 标签逐步补齐 |

## 后续清洗批次建议

- 批次 A：只处理重复题干与等价关系，不删除题目。
- 批次 B：只处理 `paper_question` 缺失和题号不一致。
- 批次 C：只处理试卷命名、文理/新高考标准化。
- 批次 D：只处理难度、标签、备注等人工/AI 辅助字段。
- 批次 E：只处理答案、解析、图片资源补全。
"""
    path.write_text(content, encoding="utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读审计 SQLite 题库的数据清洗候选项。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    parser.add_argument("--near-threshold", type=float, default=0.965, help="高相似题干阈值。")
    parser.add_argument("--near-min-length", type=int, default=30, help="参与高相似比较的最短归一化题干长度。")
    parser.add_argument("--sample-limit", type=int, default=30, help="Markdown 中每类最多展示多少条。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    db_path = db_path.resolve()
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    report = build_report(
        db_path,
        near_threshold=args.near_threshold,
        min_length=args.near_min_length,
    )

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / f"data_cleanup_candidates_{args.stamp}.md"
    json_path = REPORTS_DIR / f"data_cleanup_candidates_{args.stamp}.json"
    write_markdown(report, md_path, sample_limit=args.sample_limit)
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    summary = report["summary"]
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")
    print(
        "summary="
        f"questions={report['counts']['question']}, "
        f"exact_duplicate_groups={summary['exact_duplicate_groups']}, "
        f"near_duplicate_pairs={summary['near_duplicate_pairs']}, "
        f"track_issues={summary['track_issues']}, "
        f"questions_without_paper={summary['questions_without_paper']}, "
        f"missing_difficulty={summary['missing_difficulty']}"
    )


if __name__ == "__main__":
    main()
