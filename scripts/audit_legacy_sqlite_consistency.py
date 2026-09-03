"""Audit consistency between legacy TeX files, optional CSV index, and SQLite rows.

This script is intentionally read-only for:

- legacy question ``.tex`` files under ``chapters/``;
- the derived CSV index, when it exists;
- the structured SQLite question database.

It checks whether the transitional SQLite rows still point to the same legacy
question files and whether the identity/source fields agree with the TeX
source of truth.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHAPTERS_DIR = PROJECT_ROOT / "chapters"
CSV_INDEX_PATH = PROJECT_ROOT / "utils" / "题库索引表.csv"
REPORTS_DIR = PROJECT_ROOT / "reports"

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(PROJECT_ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "scripts"))

from scan_tex_library import extract_problem_header, iter_question_tex_files, parse_meta, read_text, relative_to_root
from services.question_db_service import QuestionListFilters, count_questions
from services.sqlite_legacy_adapter import list_sqlite_legacy_rows
from utils.csv_ops import _parse_tex_content


COMPARE_FIELDS = [
    "题目ID",
    "文件名称",
    "相对文件路径",
    "年份",
    "试卷类型",
    "试卷名称",
    "原卷题号",
    "知识板块",
    "题型",
    "难度星级",
    "标签",
    "备注",
    "包含TikZ绘图",
    "包含解析",
    "组卷引用次数",
]

BLOCKING_FIELDS = {
    "题目ID",
    "文件名称",
    "相对文件路径",
}

TAG_SPLIT_RE = re.compile(r"[，,、;；\s]+")
SPACE_RE = re.compile(r"\s+")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="审计旧 TeX 题源与 SQLite 过渡题卡的一致性。")
    parser.add_argument("--db", default="data/mathcyclus.sqlite3", help="SQLite 数据库路径。")
    parser.add_argument("--root", default=str(CHAPTERS_DIR), help="旧 TeX 题库目录，默认 chapters。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    parser.add_argument("--sample-size", type=int, default=40, help="报告中每类样例最多展示数量。")
    parser.add_argument("--no-report", action="store_true", help="只打印摘要，不写 reports。")
    return parser.parse_args()


def normalize_project_path(value: Any) -> str:
    text = str(value or "").strip().replace("\\", "/")
    if not text:
        return ""

    path = Path(text)
    if path.is_absolute():
        try:
            return path.resolve().relative_to(PROJECT_ROOT).as_posix()
        except ValueError:
            return path.as_posix()

    while text.startswith("./"):
        text = text[2:]
    if text.startswith("chapters/"):
        return text
    return f"chapters/{text}"


def normalize_tags(value: Any) -> str:
    tags = [item.strip() for item in TAG_SPLIT_RE.split(str(value or "")) if item.strip()]
    return "；".join(sorted(dict.fromkeys(tags)))


def normalize_integer_text(value: Any) -> str:
    text = str(value or "").strip()
    if not text or text.lower() == "none":
        return ""
    try:
        number = float(text)
    except ValueError:
        return text
    if number.is_integer():
        return str(int(number))
    return str(number)


def normalize_field(field: str, value: Any) -> str:
    if field == "相对文件路径":
        return normalize_project_path(value)
    if field == "标签":
        return normalize_tags(value)
    if field in {"年份", "难度星级", "组卷引用次数"}:
        return normalize_integer_text(value)
    return SPACE_RE.sub(" ", str(value or "").strip())


def natural_key(value: str) -> list[object]:
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", value)]


def build_legacy_row_from_tex(path: Path) -> dict[str, str] | None:
    text = read_text(path)
    if r"\begin{problem}" not in text:
        return None

    meta, clean_text = parse_meta(text)
    header = extract_problem_header(clean_text)
    source_name = header.get("source", "")
    has_tikz, question_type, has_solution, stem_tex, answer_tex, solution_tex, parsed_meta = _parse_tex_content(
        text,
        source_name,
    )
    if parsed_meta:
        meta = parsed_meta

    return {
        "题目ID": str(meta.get("ID", "") or ""),
        "文件名称": path.stem,
        "相对文件路径": relative_to_root(path),
        "年份": str(header.get("year", "") or ""),
        "试卷类型": str(header.get("category", "") or ""),
        "试卷名称": str(source_name or ""),
        "原卷题号": str(header.get("number", "") or ""),
        "知识板块": str(header.get("topic", "") or path.parent.parent.name),
        "标签": str(meta.get("标签", "") or ""),
        "包含TikZ绘图": has_tikz,
        "题型": question_type,
        "难度星级": str(meta.get("难度星级", "") or ""),
        "包含解析": has_solution,
        "组卷引用次数": str(meta.get("组卷引用次数", "") or "0"),
        "备注": str(meta.get("备注", "") or ""),
        "题干": stem_tex,
        "答案": answer_tex,
        "解析": solution_tex,
    }


def load_legacy_tex_rows(root: Path) -> tuple[list[dict[str, str]], int]:
    rows: list[dict[str, str]] = []
    skipped_non_questions = 0
    for path in sorted(iter_question_tex_files(root), key=lambda item: natural_key(relative_to_root(item))):
        row = build_legacy_row_from_tex(path)
        if row is None:
            skipped_non_questions += 1
            continue
        rows.append(row)
    return rows, skipped_non_questions


def load_csv_rows_if_present() -> tuple[bool, list[dict[str, str]]]:
    if not CSV_INDEX_PATH.exists():
        return False, []
    with CSV_INDEX_PATH.open("r", encoding="utf-8-sig", newline="") as file_obj:
        return True, [dict(row) for row in csv.DictReader(file_obj)]


def map_rows_by_path(rows: list[dict[str, str]]) -> tuple[dict[str, dict[str, str]], list[str]]:
    mapped: dict[str, dict[str, str]] = {}
    duplicates: list[str] = []
    for row in rows:
        path = normalize_project_path(row.get("相对文件路径", ""))
        if not path:
            continue
        if path in mapped:
            duplicates.append(path)
            continue
        mapped[path] = row
    return mapped, sorted(duplicates, key=natural_key)


def compare_row_sets(
    left_name: str,
    left_rows: list[dict[str, str]],
    right_name: str,
    right_rows: list[dict[str, str]],
    *,
    sample_size: int,
) -> dict[str, Any]:
    left_by_path, left_duplicates = map_rows_by_path(left_rows)
    right_by_path, right_duplicates = map_rows_by_path(right_rows)

    left_paths = set(left_by_path)
    right_paths = set(right_by_path)
    left_only = sorted(left_paths - right_paths, key=natural_key)
    right_only = sorted(right_paths - left_paths, key=natural_key)
    matched_paths = sorted(left_paths & right_paths, key=natural_key)

    mismatches: list[dict[str, str]] = []
    field_counter: Counter[str] = Counter()
    blocking_mismatches: list[dict[str, str]] = []

    for path in matched_paths:
        left_row = left_by_path[path]
        right_row = right_by_path[path]
        for field in COMPARE_FIELDS:
            left_value = normalize_field(field, left_row.get(field, ""))
            right_value = normalize_field(field, right_row.get(field, ""))
            if left_value == right_value:
                continue
            item = {
                "path": path,
                "field": field,
                left_name: left_value,
                right_name: right_value,
            }
            mismatches.append(item)
            field_counter[field] += 1
            if field in BLOCKING_FIELDS:
                blocking_mismatches.append(item)

    return {
        "left_name": left_name,
        "right_name": right_name,
        "left_count": len(left_rows),
        "right_count": len(right_rows),
        "left_unique_paths": len(left_by_path),
        "right_unique_paths": len(right_by_path),
        "matched_paths": len(matched_paths),
        "left_only_count": len(left_only),
        "right_only_count": len(right_only),
        "left_only_sample": left_only[:sample_size],
        "right_only_sample": right_only[:sample_size],
        "left_duplicate_paths": left_duplicates[:sample_size],
        "right_duplicate_paths": right_duplicates[:sample_size],
        "mismatch_count": len(mismatches),
        "blocking_mismatch_count": len(blocking_mismatches),
        "field_mismatch_counts": dict(sorted(field_counter.items())),
        "mismatch_sample": mismatches[:sample_size],
        "blocking_mismatch_sample": blocking_mismatches[:sample_size],
    }


def audit(db_path: str, root: Path, *, sample_size: int) -> dict[str, Any]:
    sqlite_total = count_questions(db_path)
    sqlite_rows = list_sqlite_legacy_rows(db_path, QuestionListFilters(limit=100, offset=0), max_rows=0)
    legacy_tex_rows, skipped_non_questions = load_legacy_tex_rows(root)
    csv_present, csv_rows = load_csv_rows_if_present()

    tex_sqlite = compare_row_sets(
        "legacy_tex",
        legacy_tex_rows,
        "sqlite",
        sqlite_rows,
        sample_size=sample_size,
    )

    csv_tex: dict[str, Any] | None = None
    if csv_present:
        csv_tex = compare_row_sets(
            "csv",
            csv_rows,
            "legacy_tex",
            legacy_tex_rows,
            sample_size=sample_size,
        )

    blockers: list[str] = []
    warnings: list[str] = []
    if sqlite_total != len(sqlite_rows):
        blockers.append(f"SQLite 读取行数异常：count={sqlite_total}，rows={len(sqlite_rows)}。")
    if tex_sqlite["left_only_count"]:
        blockers.append("存在旧 TeX 题目没有进入 SQLite 过渡索引。")
    if tex_sqlite["right_only_count"]:
        blockers.append("存在 SQLite 题目无法匹配到旧 TeX 题源。")
    if tex_sqlite["left_duplicate_paths"] or tex_sqlite["right_duplicate_paths"]:
        blockers.append("存在重复题源路径，无法安全做一对一迁移核验。")
    if tex_sqlite["blocking_mismatch_count"]:
        blockers.append("旧 TeX 与 SQLite 的身份/文件路径关键字段存在差异。")
    if tex_sqlite["mismatch_count"] and not tex_sqlite["blocking_mismatch_count"]:
        warnings.append("旧 TeX 与 SQLite 存在来源/题型/标签等非阻塞字段差异，主要用于人工复核。")
    if skipped_non_questions:
        warnings.append(f"旧题源扫描跳过 {skipped_non_questions} 个非题目 TeX 文件。")
    if not csv_present:
        warnings.append("本地未生成 CSV 缓存索引；这是可重建派生文件，不影响 SQLite/TeX 一致性审计。")
    elif csv_tex and (
        csv_tex["left_only_count"]
        or csv_tex["right_only_count"]
        or csv_tex["blocking_mismatch_count"]
        or csv_tex["mismatch_count"]
    ):
        warnings.append("CSV 缓存索引与旧 TeX 扫描结果存在差异，建议提交前重建/同步索引。")

    status = "blocked" if blockers else "warning" if warnings else "ok"
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "database": db_path,
        "root": relative_to_root(root),
        "status": status,
        "blockers": blockers,
        "warnings": warnings,
        "sqlite_total": sqlite_total,
        "sqlite_rows": len(sqlite_rows),
        "legacy_tex_rows": len(legacy_tex_rows),
        "legacy_non_question_skipped": skipped_non_questions,
        "csv_present": csv_present,
        "csv_rows": len(csv_rows),
        "tex_vs_sqlite": tex_sqlite,
        "csv_vs_tex": csv_tex,
        "writes_formal_database": False,
        "writes_legacy_tex": False,
        "writes_csv_index": False,
    }


def lines_for_path_sample(title: str, paths: list[str]) -> list[str]:
    lines = [f"## {title}", ""]
    if not paths:
        lines.append("- 无")
    else:
        lines.extend(f"- `{path}`" for path in paths)
    lines.append("")
    return lines


def lines_for_mismatch_sample(title: str, mismatches: list[dict[str, str]], left_name: str, right_name: str) -> list[str]:
    lines = [f"## {title}", ""]
    if not mismatches:
        lines.append("- 无")
    else:
        for item in mismatches:
            lines.append(
                f"- `{item['path']}`：`{item['field']}` "
                f"{left_name}=`{item.get(left_name, '')}` / {right_name}=`{item.get(right_name, '')}`"
            )
    lines.append("")
    return lines


def format_compare_section(title: str, section: dict[str, Any] | None) -> list[str]:
    if not section:
        return [f"# {title}", "", "- 未执行。", ""]

    lines = [
        f"# {title}",
        "",
        "| 指标 | 数量 |",
        "| --- | ---: |",
        f"| {section['left_name']} 行数 | {section['left_count']} |",
        f"| {section['right_name']} 行数 | {section['right_count']} |",
        f"| 匹配路径数 | {section['matched_paths']} |",
        f"| {section['left_name']} 独有路径 | {section['left_only_count']} |",
        f"| {section['right_name']} 独有路径 | {section['right_only_count']} |",
        f"| 字段差异数 | {section['mismatch_count']} |",
        f"| 阻塞字段差异数 | {section['blocking_mismatch_count']} |",
        "",
        "## 字段差异分布",
        "",
    ]
    if section["field_mismatch_counts"]:
        lines.extend(f"- {field}：{count}" for field, count in section["field_mismatch_counts"].items())
    else:
        lines.append("- 无")
    lines.append("")
    lines.extend(lines_for_path_sample(f"{section['left_name']} 独有路径样例", section["left_only_sample"]))
    lines.extend(lines_for_path_sample(f"{section['right_name']} 独有路径样例", section["right_only_sample"]))
    lines.extend(
        lines_for_mismatch_sample(
            "阻塞字段差异样例",
            section["blocking_mismatch_sample"],
            section["left_name"],
            section["right_name"],
        )
    )
    lines.extend(
        lines_for_mismatch_sample(
            "字段差异样例",
            section["mismatch_sample"],
            section["left_name"],
            section["right_name"],
        )
    )
    return lines


def write_reports(report: dict[str, Any], stamp: str) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"legacy_sqlite_consistency_{stamp}.json"
    md_path = REPORTS_DIR / f"legacy_sqlite_consistency_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = [
        "# 旧 TeX / SQLite 一致性审计",
        "",
        f"> 生成时间：{report['created_at']}  ",
        f"> 状态：`{report['status']}`  ",
        f"> 数据库：`{report['database']}`  ",
        f"> 旧题源目录：`{report['root']}`  ",
        f"> 说明：只读审计，不修改 SQLite、CSV 或旧 `.tex` 文件。",
        "",
        "## 总览",
        "",
        "| 指标 | 数量 |",
        "| --- | ---: |",
        f"| SQLite count | {report['sqlite_total']} |",
        f"| SQLite 读取行数 | {report['sqlite_rows']} |",
        f"| 旧 TeX 题目数 | {report['legacy_tex_rows']} |",
        f"| 跳过非题目 TeX | {report['legacy_non_question_skipped']} |",
        f"| CSV 缓存是否存在 | {'是' if report['csv_present'] else '否'} |",
        f"| CSV 行数 | {report['csv_rows']} |",
        "",
        "## 阻塞项",
        "",
    ]
    if report["blockers"]:
        lines.extend(f"- {item}" for item in report["blockers"])
    else:
        lines.append("- 无")
    lines.extend(["", "## 警告项", ""])
    if report["warnings"]:
        lines.extend(f"- {item}" for item in report["warnings"])
    else:
        lines.append("- 无")
    lines.append("")
    lines.extend(format_compare_section("旧 TeX vs SQLite", report["tex_vs_sqlite"]))
    lines.extend(format_compare_section("CSV vs 旧 TeX", report["csv_vs_tex"]))
    lines.extend(
        [
            "## 文件管理判断",
            "",
            "- 本脚本只写入 `reports/` 下的审计报告；`reports/*` 已被 `.gitignore` 忽略。",
            "- `data/mathcyclus.sqlite3` 作为本地正式数据库仍被忽略，不应直接提交到 GitHub。",
            "- 旧 `.tex` 题源仍作为当前生成试卷的真实 payload，本审计不移动、不覆盖、不删除。",
            "- CSV 索引是可重建缓存；缺失时不阻塞，但提交前可以在工具箱重建以便本地 UI 使用。",
        ]
    )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return md_path, json_path


def main() -> int:
    args = parse_args()
    root = Path(args.root)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root = root.resolve()
    if not root.exists():
        raise SystemExit(f"旧题源目录不存在：{root}")

    report = audit(args.db, root, sample_size=max(1, args.sample_size))
    if not args.no_report:
        md_path, json_path = write_reports(report, args.stamp)
        report["report"] = relative_to_root(md_path)
        report["json"] = relative_to_root(json_path)

    print(f"status={report['status']}")
    print(f"sqlite_rows={report['sqlite_rows']}")
    print(f"legacy_tex_rows={report['legacy_tex_rows']}")
    print(f"tex_only={report['tex_vs_sqlite']['left_only_count']}")
    print(f"sqlite_only={report['tex_vs_sqlite']['right_only_count']}")
    print(f"field_mismatches={report['tex_vs_sqlite']['mismatch_count']}")
    print(f"blocking_mismatches={report['tex_vs_sqlite']['blocking_mismatch_count']}")
    if not args.no_report:
        print(f"report={report['report']}")
        print(f"json={report['json']}")
    return 0 if report["status"] != "blocked" else 1


if __name__ == "__main__":
    raise SystemExit(main())
