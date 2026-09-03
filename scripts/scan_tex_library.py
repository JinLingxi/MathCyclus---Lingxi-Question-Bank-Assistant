from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHAPTERS_DIR = PROJECT_ROOT / "chapters"
REPORTS_DIR = PROJECT_ROOT / "reports"


META_PATTERN = re.compile(
    r"%(?: === Meta Data ===| === Begin Label Data ===)\r?\n"
    r"(?P<body>[\s\S]*?)"
    r"%(?: === End Meta ===| === End\s+Label Data ===)\r?\n?",
    re.MULTILINE,
)
PROBLEM_HEADER_PATTERN = re.compile(
    r"\\begin\{problem\}"
    r"(?:\{(?P<year>[^{}]*)\})?"
    r"(?:\{(?P<category>[^{}]*)\})?"
    r"(?:\{(?P<source>[^{}]*)\})?"
    r"(?:\{(?P<number>[^{}]*)\})?"
    r"(?:\{(?P<topic>[^{}]*)\})?",
    re.MULTILINE,
)
ENV_PATTERN_TEMPLATE = r"\\begin\{{{name}\}}(?P<body>[\s\S]*?)\\end\{{{name}\}}"
CHOICE_PATTERN = re.compile(r"\\choice\s*\{", re.MULTILINE)
INCLUDE_GRAPHICS_PATTERN = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^{}]+)\}",
    re.MULTILINE,
)
COMMON_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".pdf", ".svg", ".bmp", ".webp"}


@dataclass
class ScanRecord:
    relative_path: str
    file_name: str
    chapter: str
    year_dir: str
    legacy_id: str
    difficulty: str
    tags: str
    note: str
    usage_count: str
    detected_year: str
    detected_category: str
    detected_source: str
    detected_question_number: str
    detected_topic: str
    has_problem: bool
    has_answer: bool
    has_solutions: bool
    choice_count: int
    has_tikz: bool
    includegraphics_count: int
    sibling_image_count: int
    missing_image_refs: str
    content_hash: str
    status: str
    warnings: str


def is_auxiliary_tex(path: Path) -> bool:
    parts = path.parts
    return any(part.endswith("相关图") for part in parts) or "相关图" in path.parent.name


def read_text(path: Path) -> str:
    raw = path.read_bytes()
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_meta(text: str) -> tuple[dict[str, str], str]:
    match = META_PATTERN.search(text)
    if not match:
        return {}, text

    meta: dict[str, str] = {}
    for line in match.group("body").splitlines():
        stripped = line.strip()
        if not stripped.startswith("%"):
            continue
        item = stripped[1:].strip()
        if ":" not in item:
            continue
        key, value = item.split(":", 1)
        meta[key.strip()] = value.strip()

    clean_text = META_PATTERN.sub("", text, count=1).lstrip()
    return meta, clean_text


def extract_env(text: str, name: str) -> str:
    pattern = re.compile(ENV_PATTERN_TEMPLATE.format(name=re.escape(name)), re.MULTILINE)
    match = pattern.search(text)
    return match.group("body").strip() if match else ""


def extract_problem_header(text: str) -> dict[str, str]:
    match = PROBLEM_HEADER_PATTERN.search(text)
    if not match:
        return {}
    return {key: (value or "").strip() for key, value in match.groupdict().items()}


def relative_to_root(path: Path) -> str:
    return path.resolve().relative_to(PROJECT_ROOT).as_posix()


def iter_question_tex_files(root: Path) -> Iterable[Path]:
    for path in root.rglob("*.tex"):
        if path.name.startswith("content_"):
            continue
        if is_auxiliary_tex(path):
            continue
        yield path


def sibling_image_count(path: Path) -> int:
    return sum(
        1
        for item in path.parent.iterdir()
        if item.is_file() and item.suffix.lower() in COMMON_IMAGE_EXTENSIONS
    )


def find_missing_image_refs(path: Path, text: str) -> list[str]:
    missing: list[str] = []
    for match in INCLUDE_GRAPHICS_PATTERN.finditer(text):
        raw_ref = match.group("path").strip()
        candidates = []
        ref_path = Path(raw_ref)
        if ref_path.is_absolute():
            candidates.append(ref_path)
        else:
            candidates.append(path.parent / raw_ref)
            candidates.append(PROJECT_ROOT / raw_ref)
        if not any(candidate.exists() for candidate in candidates):
            missing.append(raw_ref)
    return missing


def status_from_warnings(warnings: list[str]) -> str:
    if not warnings:
        return "ok"
    if any(item.startswith("missing_problem") or item.startswith("missing_meta") for item in warnings):
        return "needs_review"
    return "warning"


def scan_file(path: Path) -> ScanRecord:
    text = read_text(path)
    meta, clean_text = parse_meta(text)
    header = extract_problem_header(clean_text)
    answer = extract_env(clean_text, "answer")
    solutions = extract_env(clean_text, "solutions")
    missing_images = find_missing_image_refs(path, clean_text)

    warnings: list[str] = []
    if not meta:
        warnings.append("missing_meta")
    if "ID" not in meta or not meta.get("ID", "").strip():
        warnings.append("missing_legacy_id")
    if "\\begin{problem}" not in clean_text:
        warnings.append("missing_problem")
    if "\\end{problem}" not in clean_text:
        warnings.append("missing_problem_end")
    if missing_images:
        warnings.append("missing_image_refs")

    parts = path.relative_to(CHAPTERS_DIR).parts
    chapter = parts[0] if len(parts) >= 1 else ""
    year_dir = parts[1] if len(parts) >= 2 else ""
    content_hash = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:16]

    return ScanRecord(
        relative_path=relative_to_root(path),
        file_name=path.name,
        chapter=chapter,
        year_dir=year_dir,
        legacy_id=meta.get("ID", ""),
        difficulty=meta.get("难度星级", ""),
        tags=meta.get("标签", ""),
        note=meta.get("备注", ""),
        usage_count=meta.get("组卷引用次数", ""),
        detected_year=header.get("year", ""),
        detected_category=header.get("category", ""),
        detected_source=header.get("source", ""),
        detected_question_number=header.get("number", ""),
        detected_topic=header.get("topic", ""),
        has_problem=bool(header),
        has_answer=bool(answer),
        has_solutions=bool(solutions),
        choice_count=len(CHOICE_PATTERN.findall(clean_text)),
        has_tikz="\\begin{tikzpicture}" in clean_text,
        includegraphics_count=len(INCLUDE_GRAPHICS_PATTERN.findall(clean_text)),
        sibling_image_count=sibling_image_count(path),
        missing_image_refs="; ".join(missing_images),
        content_hash=content_hash,
        status=status_from_warnings(warnings),
        warnings="; ".join(warnings),
    )


def write_csv(records: list[ScanRecord], path: Path) -> None:
    if not records:
        path.write_text("", encoding="utf-8-sig")
        return
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(asdict(records[0]).keys()))
        writer.writeheader()
        for record in records:
            writer.writerow(asdict(record))


def make_markdown_report(records: list[ScanRecord], csv_path: Path, root: Path) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    status_counter = Counter(record.status for record in records)
    chapter_counter = Counter(record.chapter for record in records)
    year_counter = Counter(record.year_dir for record in records)
    legacy_counter = Counter(record.legacy_id for record in records if record.legacy_id)
    duplicate_legacy_ids = {key: value for key, value in legacy_counter.items() if value > 1}

    missing_meta = [record for record in records if "missing_meta" in record.warnings]
    missing_legacy_id = [record for record in records if "missing_legacy_id" in record.warnings]
    missing_problem = [record for record in records if "missing_problem" in record.warnings]
    missing_image_refs = [record for record in records if record.missing_image_refs]
    with_sibling_images = [record for record in records if record.sibling_image_count > 0]
    auxiliary_tex_count = sum(1 for path in root.rglob("*.tex") if is_auxiliary_tex(path))

    def sample_rows(items: list[ScanRecord], limit: int = 20) -> str:
        if not items:
            return "无\n"
        lines = []
        for item in items[:limit]:
            lines.append(
                f"- `{item.relative_path}`"
                f"：ID `{item.legacy_id or '空'}`，状态 `{item.status}`，警告 `{item.warnings or '无'}`"
            )
        if len(items) > limit:
            lines.append(f"- 另有 {len(items) - limit} 条未在此处展开，详见 CSV。")
        return "\n".join(lines) + "\n"

    top_chapters = "\n".join(f"- {name or '未知'}：{count}" for name, count in chapter_counter.most_common())
    top_years = "\n".join(f"- {name or '未知'}：{count}" for name, count in year_counter.most_common())
    duplicate_lines = "\n".join(
        f"- `{legacy_id}`：{count} 次" for legacy_id, count in sorted(duplicate_legacy_ids.items())
    ) or "无"

    return f"""# TeX 题库扫描报告

> 生成时间：{now}  
> 扫描目录：`{root.relative_to(PROJECT_ROOT).as_posix()}`  
> 输出明细：`{csv_path.relative_to(PROJECT_ROOT).as_posix()}`  
> 扫描方式：只读扫描，不修改任何题库文件。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 题目 TeX 文件数 | {len(records)} |
| 状态 ok | {status_counter.get('ok', 0)} |
| 状态 warning | {status_counter.get('warning', 0)} |
| 状态 needs_review | {status_counter.get('needs_review', 0)} |
| 缺失元数据块 | {len(missing_meta)} |
| 缺失旧 ID | {len(missing_legacy_id)} |
| 缺失 problem 环境 | {len(missing_problem)} |
| 重复旧 ID 数 | {len(duplicate_legacy_ids)} |
| 含 TikZ 题目 | {sum(1 for record in records if record.has_tikz)} |
| 含 includegraphics 题目 | {sum(1 for record in records if record.includegraphics_count > 0)} |
| 同目录存在图片资源的题目 | {len(with_sibling_images)} |
| 图片引用缺失题目 | {len(missing_image_refs)} |
| 已排除相关图 TeX 源文件 | {auxiliary_tex_count} |

## 按知识板块统计

{top_chapters or '无'}

## 按年份目录统计

{top_years or '无'}

## 重复旧 ID

{duplicate_lines}

## 缺失元数据样例

{sample_rows(missing_meta)}
## 缺失旧 ID 样例

{sample_rows(missing_legacy_id)}
## 缺失 problem 环境样例

{sample_rows(missing_problem)}
## 图片引用缺失样例

{sample_rows(missing_image_refs)}
## 后续处理建议

- 先人工检查 `needs_review` 项，不要直接迁移为正式题目。
- 重复旧 ID 需要在生成稳定 `question_id` 时保留 `legacy_id`，但不能继续作为唯一主键。
- 同目录图片资源应在图片系统阶段迁移到 `assets/questions/<question_id>/`。
- `includegraphics` 路径缺失的题目要进入待确认报告，避免导出后 LaTeX 编译失败。
- 迁移脚本第一版应继续 dry-run，只写报告，不覆盖原 `.tex`。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读扫描 chapters 题库，输出迁移前质量报告。")
    parser.add_argument(
        "--root",
        default=str(CHAPTERS_DIR),
        help="要扫描的题库目录，默认 chapters。",
    )
    parser.add_argument(
        "--stamp",
        default=datetime.now().strftime("%Y%m%d_%H%M%S"),
        help="报告文件时间戳，默认当前时间。",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(args.root)
    if not root.is_absolute():
        root = PROJECT_ROOT / root
    root = root.resolve()

    if not root.exists():
        raise SystemExit(f"扫描目录不存在：{root}")

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    records = [scan_file(path) for path in sorted(iter_question_tex_files(root))]

    csv_path = REPORTS_DIR / f"tex_scan_{args.stamp}.csv"
    md_path = REPORTS_DIR / f"tex_scan_{args.stamp}.md"
    json_path = REPORTS_DIR / f"tex_scan_{args.stamp}.summary.json"

    write_csv(records, csv_path)
    md_path.write_text(make_markdown_report(records, csv_path, root), encoding="utf-8")

    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "root": relative_to_root(root),
        "records": len(records),
        "csv": relative_to_root(csv_path),
        "markdown": relative_to_root(md_path),
    }
    json_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"scanned={len(records)}")
    print(f"markdown={relative_to_root(md_path)}")
    print(f"csv={relative_to_root(csv_path)}")
    print(f"summary={relative_to_root(json_path)}")


if __name__ == "__main__":
    main()
