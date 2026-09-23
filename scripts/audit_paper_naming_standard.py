from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
REPORTS_DIR = PROJECT_ROOT / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


TRACK_VALUES = {"文科", "理科", "新高考", "综合", "文", "理", "不区分", ""}
COMPREHENSIVE_LOCAL_NAMES = {
    "上海卷",
    "上海春考卷",
    "北京春考",
    "北京春考卷",
    "江苏卷",
    "八省联考",
    "港台华侨联考",
}
COMPREHENSIVE_LOCAL_YEAR_RANGES = {
    "浙江卷": ((2017, 2022),),
}
NON_GAOKAO_SOURCE_KEYWORDS = [
    "模拟",
    "一模",
    "二模",
    "三模",
    "联考",
    "调研",
    "适应",
    "诊断",
    "质检",
    "月考",
    "中学",
    "高三",
    "高二",
    "高一",
    "联盟",
    "测试",
]
LOCAL_PROVINCE_KEYWORDS = [
    "北京",
    "天津",
    "上海",
    "重庆",
    "河北",
    "山西",
    "辽宁",
    "吉林",
    "黑龙江",
    "江苏",
    "浙江",
    "安徽",
    "福建",
    "江西",
    "山东",
    "河南",
    "湖北",
    "湖南",
    "广东",
    "海南",
    "四川",
    "贵州",
    "云南",
    "陕西",
    "甘肃",
    "青海",
    "内蒙古",
    "广西",
    "宁夏",
    "新疆",
    "西藏",
]


@dataclass
class PaperSuggestion:
    paper_id: str
    year: int | None
    paper_series: str
    current_track: str
    current_paper_name: str
    current_source_name: str
    question_count: int
    suggested_paper_name: str
    suggested_source_name: str
    suggested_track: str
    risk_level: str
    issues: list[str]


def resolve_db_path(path: str | Path) -> Path:
    db_path = Path(path)
    if not db_path.is_absolute():
        db_path = PROJECT_ROOT / db_path
    return db_path.resolve()


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def connect_database(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def normalize_track_text(track: str) -> str:
    value = (track or "").strip()
    if value == "文":
        return "文科"
    if value == "理":
        return "理科"
    if value == "不区分":
        return "综合"
    return value


def strip_track_suffix(name: str) -> tuple[str, str]:
    value = (name or "").strip()
    inferred = ""
    patterns = [
        (r"[（(]\s*文\s*[）)]$", "文科"),
        (r"[（(]\s*文科\s*[）)]$", "文科"),
        (r"[（(]\s*理\s*[）)]$", "理科"),
        (r"[（(]\s*理科\s*[）)]$", "理科"),
    ]
    for pattern, track in patterns:
        if re.search(pattern, value):
            value = re.sub(pattern, "", value).strip()
            inferred = track
            break
    return value, inferred


def normalize_roman_order(name: str) -> str:
    value = (name or "").strip()
    value = value.replace("Ⅰ", "I").replace("Ⅱ", "II").replace("Ⅲ", "III").replace("Ⅳ", "IV")
    token_map = {
        "Ⅰ": "I",
        "Ⅱ": "II",
        "Ⅲ": "III",
        "Ⅳ": "IV",
        "一": "I",
        "二": "II",
        "三": "III",
    }

    def convert(match: re.Match[str], prefix: str) -> str:
        order = match.group(1)
        normalized_order = token_map.get(order, order)
        return f"{prefix}{normalized_order}卷"

    value = re.sub(r"全国卷\s*([一二三IVX]+)$", lambda m: convert(m, "全国"), value)
    value = re.sub(r"全国\s*([一二三IVX]+)卷$", lambda m: convert(m, "全国"), value)
    value = re.sub(r"新课标卷\s*([一二三IVX]+)$", lambda m: convert(m, "新课标"), value)
    value = re.sub(r"新课标\s*([一二三IVX]+)卷$", lambda m: convert(m, "新课标"), value)
    value = re.sub(r"课标全国卷\s*([一二三IVX]+)$", lambda m: convert(m, "新课标"), value)
    value = re.sub(r"课标全国\s*([一二三IVX]+)卷$", lambda m: convert(m, "新课标"), value)
    value = re.sub(r"大纲卷\s*([一二三IVX]+)$", lambda m: convert(m, "大纲"), value)
    value = re.sub(r"大纲\s*([一二三IVX]+)卷$", lambda m: convert(m, "大纲"), value)
    return value


def has_local_keyword(name: str) -> bool:
    return any(keyword in name for keyword in LOCAL_PROVINCE_KEYWORDS)


def is_likely_formal_gaokao_paper(base_name: str) -> bool:
    if any(keyword in base_name for keyword in NON_GAOKAO_SOURCE_KEYWORDS):
        return False
    if base_name.startswith(("全国", "新课标", "大纲")):
        return True
    return has_local_keyword(base_name) and base_name.endswith("卷")


def needs_pre_2023_track_review(year: int | None, base_name: str, track: str) -> bool:
    if not year or year < 2005:
        return False
    if "新高考" in base_name:
        return False
    if base_name == "江苏卷":
        return False
    if any(start <= year <= end for start, end in COMPREHENSIVE_LOCAL_YEAR_RANGES.get(base_name, ())):
        return False
    if not is_likely_formal_gaokao_paper(base_name):
        return False
    if "上海" in base_name:
        should_review = year < 2017
    elif "北京" in base_name or "天津" in base_name:
        should_review = year < 2020
    else:
        should_review = year < 2023
    return should_review and normalize_track_text(track) in {"", "综合"}


def infer_track(year: int | None, base_name: str, current_track: str, suffix_track: str) -> tuple[str, list[str]]:
    issues: list[str] = []
    current = normalize_track_text(current_track)
    if suffix_track:
        if current and current != suffix_track:
            issues.append(f"track 与名称文理标记不一致：{current} vs {suffix_track}")
        return suffix_track, issues
    if current:
        if needs_pre_2023_track_review(year, base_name, current):
            issues.append("按当前规则该卷需要确认文科或理科")
            return "待确认（文科/理科）", issues
        return current, issues
    if "新高考" in base_name:
        return "新高考", issues
    if base_name in COMPREHENSIVE_LOCAL_NAMES:
        return "综合", issues
    if base_name == "江苏卷":
        return "综合", issues
    if base_name == "辽宁卷" and year == 2005:
        return "综合", ["2005 年辽宁卷按现有数据保留综合，来源未提供文理拆分证据"]
    if any(start <= (year or 0) <= end for start, end in COMPREHENSIVE_LOCAL_YEAR_RANGES.get(base_name, ())):
        return "综合", issues
    if needs_pre_2023_track_review(year, base_name, current):
        issues.append("按当前规则该卷需要确认文科或理科")
        return "待确认（文科/理科）", issues
    if year and year >= 2005 and year < 2023 and has_local_keyword(base_name) and "新高考" not in base_name:
        issues.append("2023 年前地方卷缺少文理 track，需人工确认")
        return "待确认（文科/理科）", issues
    if year and year >= 2005 and year < 2023 and (
        base_name.startswith("全国")
        or base_name.startswith("新课标")
        or base_name.startswith("大纲")
        or "课标全国" in base_name
    ):
        issues.append("2023 年前全国/课标/大纲卷缺少文理 track，需人工确认")
        return "待确认（文科/理科）", issues
    return "综合", issues


def standard_national_name(year: int | None, base_name: str) -> tuple[str, list[str]]:
    issues: list[str] = []
    if year and year < 2005:
        return base_name, issues
    name = normalize_roman_order(base_name)

    if not year:
        return name, ["缺少年份，无法按年份分段判断全国卷命名"]

    if 2007 <= year <= 2013:
        if name.startswith("课标全国"):
            name = name.replace("课标全国", "新课标", 1)
        if re.fullmatch(r"课标全国[IVX]+卷", name):
            name = name.replace("课标全国", "新课标", 1)
        if re.fullmatch(r"全国[IVX]+卷", name):
            issues.append("2007-2013 年全国*卷需确认是否应为新课标*卷或大纲*卷")
        return name, issues

    if 2017 <= year <= 2019:
        if re.fullmatch(r"全国[IVX]+卷", name):
            name = name.replace("全国", "新课标", 1)
        if name.startswith("课标全国"):
            name = name.replace("课标全国", "新课标", 1)
        return name, issues

    if 2023 <= year <= 2024:
        if re.fullmatch(r"全国[IVX]+卷", name):
            name = name.replace("全国", "新课标", 1)
        return name, issues

    if year >= 2025:
        if re.fullmatch(r"新课标[IVX]+卷", name):
            name = name.replace("新课标", "全国", 1)
        return name, issues

    if 2014 <= year <= 2016:
        if name.startswith("课标全国"):
            name = name.replace("课标全国", "全国", 1)
        if re.fullmatch(r"新课标[IVX]+卷", name):
            name = name.replace("新课标", "全国", 1)
        return name, issues

    return name, issues


def suggest_paper(row: sqlite3.Row) -> PaperSuggestion:
    year = row["year"]
    paper_name = (row["paper_name"] or "").strip()
    source_name = (row["source_name"] or "").strip()
    current_track = (row["track"] or "").strip()
    display_name = source_name or paper_name
    base_name, suffix_track = strip_track_suffix(display_name)
    normalized_name, name_issues = standard_national_name(year, base_name)
    suggested_track, track_issues = infer_track(year, normalized_name, current_track, suffix_track)
    issues = []

    if current_track not in TRACK_VALUES:
        issues.append(f"track 值不在建议枚举内：{current_track}")
    issues.extend(name_issues)
    issues.extend(track_issues)

    # Preserve non-standard source names such as "全国乙卷（文）改" or
    # "广东卷（文）改" instead of appending a second track suffix.
    has_track_marker = bool(re.search(r"[（(]\s*(?:文|文科|理|理科)\s*[）)]", display_name))
    if has_track_marker:
        suggested_source = display_name
    else:
        suggested_source = normalized_name
        if suggested_track == "文科":
            suggested_source = f"{normalized_name}（文）"
        elif suggested_track == "理科":
            suggested_source = f"{normalized_name}（理）"

    current_normalized_track = normalize_track_text(current_track)
    if normalized_name != paper_name:
        issues.append("paper_name 建议标准化")
    if suggested_track and suggested_track != current_normalized_track:
        issues.append("track 建议标准化")
    if suggested_source != source_name:
        issues.append("source_name 建议标准化")

    risk_level = "ok"
    if any(
        "需人工确认" in issue
        or "需确认" in issue
        or "需要确认" in issue
        or "不一致" in issue
        or "缺少" in issue
        for issue in issues
    ):
        risk_level = "review"
    elif issues:
        risk_level = "auto_candidate"

    return PaperSuggestion(
        paper_id=row["paper_id"],
        year=year,
        paper_series=row["paper_series"] or "",
        current_track=current_track,
        current_paper_name=paper_name,
        current_source_name=source_name,
        question_count=row["question_count"] or 0,
        suggested_paper_name=normalized_name,
        suggested_source_name=suggested_source,
        suggested_track=suggested_track,
        risk_level=risk_level,
        issues=issues,
    )


def fetch_papers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            p.paper_id,
            p.year,
            p.paper_series,
            p.track,
            p.paper_name,
            p.source_name,
            COUNT(pq.question_id) AS question_count
        FROM paper p
        LEFT JOIN paper_question pq ON pq.paper_id = p.paper_id
        GROUP BY p.paper_id
        ORDER BY p.year, p.paper_series, p.paper_name, p.track, p.paper_id
        """
    ).fetchall()


def duplicate_target_groups(suggestions: list[PaperSuggestion]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[PaperSuggestion]] = defaultdict(list)
    for item in suggestions:
        key = (item.year, item.paper_series, item.suggested_track, item.suggested_paper_name)
        grouped[key].append(item)
    duplicates = []
    for key, items in grouped.items():
        if len(items) <= 1:
            continue
        duplicates.append(
            {
                "target": {
                    "year": key[0],
                    "paper_series": key[1],
                    "track": key[2],
                    "paper_name": key[3],
                },
                "paper_ids": [item.paper_id for item in items],
                "source_names": [item.current_source_name or item.current_paper_name for item in items],
                "question_count": sum(int(item.question_count or 0) for item in items),
            }
        )
    duplicates.sort(key=lambda row: (-row["question_count"], str(row["target"])))
    return duplicates


def markdown_table(items: list[PaperSuggestion], limit: int) -> str:
    if not items:
        return "无"
    lines = [
        "| paper_id | 年份 | 当前 track | 当前名称 | 题数 | 建议 track | 建议名称 | 风险 | 问题 |",
        "| --- | ---: | --- | --- | ---: | --- | --- | --- | --- |",
    ]
    for item in items[:limit]:
        current_name = item.current_source_name or item.current_paper_name
        issues = "<br>".join(item.issues) if item.issues else ""
        lines.append(
            f"| `{item.paper_id}` | {item.year or ''} | {item.current_track} | {current_name} | "
            f"{item.question_count} | {item.suggested_track} | {item.suggested_source_name} | "
            f"{item.risk_level} | {issues} |"
        )
    return "\n".join(lines)


def duplicate_markdown_table(items: list[dict[str, Any]], limit: int) -> str:
    if not items:
        return "无"
    lines = [
        "| 目标年份 | 目标 track | 目标名称 | 合并后题数 | 原 paper_id | 原名称 |",
        "| ---: | --- | --- | ---: | --- | --- |",
    ]
    for row in items[:limit]:
        target = row["target"]
        lines.append(
            f"| {target['year'] or ''} | {target['track']} | {target['paper_name']} | "
            f"{row['question_count']} | {'<br>'.join('`'+pid+'`' for pid in row['paper_ids'])} | "
            f"{'<br>'.join(row['source_names'])} |"
        )
    return "\n".join(lines)


def write_reports(
    suggestions: list[PaperSuggestion],
    duplicates: list[dict[str, Any]],
    *,
    db_path: Path,
    stamp: str,
    limit: int,
) -> tuple[Path, Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    md_path = REPORTS_DIR / f"paper_naming_standard_audit_{stamp}.md"
    json_path = REPORTS_DIR / f"paper_naming_standard_audit_{stamp}.json"
    csv_path = REPORTS_DIR / f"paper_naming_standard_audit_{stamp}.csv"

    duplicate_ids = {
        paper_id
        for group in duplicates
        for paper_id in group.get("paper_ids", [])
    }
    for item in suggestions:
        if item.paper_id in duplicate_ids and item.risk_level == "auto_candidate":
            item.risk_level = "review"
            item.issues.append("标准化后会与其他试卷合并，需人工确认")

    counts = Counter(item.risk_level for item in suggestions)
    changed = [item for item in suggestions if item.issues]
    review = [item for item in suggestions if item.risk_level == "review"]
    auto_candidates = [item for item in suggestions if item.risk_level == "auto_candidate"]
    review.sort(key=lambda item: (-int(item.question_count or 0), item.year or 0, item.current_source_name))
    auto_candidates.sort(key=lambda item: (-int(item.question_count or 0), item.year or 0, item.current_source_name))

    payload = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "database": relative_to_root(db_path),
        "summary": {
            "papers": len(suggestions),
            "changed_or_flagged": len(changed),
            "review": len(review),
            "auto_candidate": len(auto_candidates),
            "ok": counts.get("ok", 0),
            "duplicate_target_groups": len(duplicates),
        },
        "suggestions": [asdict(item) for item in suggestions],
        "duplicate_target_groups": duplicates,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with csv_path.open("w", encoding="utf-8-sig", newline="") as file:
        fieldnames = [
            "paper_id",
            "year",
            "paper_series",
            "current_track",
            "current_paper_name",
            "current_source_name",
            "question_count",
            "suggested_track",
            "suggested_paper_name",
            "suggested_source_name",
            "risk_level",
            "issues",
            "review_decision",
            "review_note",
        ]
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        for item in suggestions:
            writer.writerow(
                {
                    "paper_id": item.paper_id,
                    "year": item.year or "",
                    "paper_series": item.paper_series,
                    "current_track": item.current_track,
                    "current_paper_name": item.current_paper_name,
                    "current_source_name": item.current_source_name,
                    "question_count": item.question_count,
                    "suggested_track": item.suggested_track,
                    "suggested_paper_name": item.suggested_paper_name,
                    "suggested_source_name": item.suggested_source_name,
                    "risk_level": item.risk_level,
                    "issues": "；".join(item.issues),
                    "review_decision": "",
                    "review_note": "",
                }
            )

    md_path.write_text(
        f"""# 试卷命名标准审计报告

> 生成时间：{payload['generated_at']}  
> 数据库：`{payload['database']}`  
> 性质：只读审计，不修改 SQLite、不修改旧 TeX。

## 总览

| 指标 | 数量 |
| --- | ---: |
| 试卷记录 | {len(suggestions)} |
| 需要调整或复核 | {len(changed)} |
| 必须人工复核 | {len(review)} |
| 可自动标准化候选 | {len(auto_candidates)} |
| 暂无问题 | {counts.get('ok', 0)} |
| 标准化后可能合并的试卷组 | {len(duplicates)} |

## 必须人工复核

{markdown_table(review, limit)}

## 可自动标准化候选

{markdown_table(auto_candidates, limit)}

## 标准化后可能合并的试卷组

{duplicate_markdown_table(duplicates, limit)}

## 建议处理顺序

1. 先人工确认“必须人工复核”表，尤其是 2023 年前缺少文理 track 的全国卷和地方卷。
2. 再确认标准化后可能合并的试卷组，避免把不同真实试卷误合并。
3. 确认后生成映射表副本，不直接覆盖正式库。
4. 最后再批量同步 `paper`、旧 TeX 文件名、`problem` 头和 `legacy_question_map`。
""",
        encoding="utf-8",
    )
    return md_path, json_path, csv_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="只读审计 SQLite 试卷命名是否符合当前标准化规则。")
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 数据库路径。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    parser.add_argument("--limit", type=int, default=80, help="Markdown 每组最多展示条数。")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db_path = resolve_db_path(args.db)
    if not db_path.exists():
        raise SystemExit(f"数据库不存在：{db_path}")

    with connect_database(db_path) as conn:
        suggestions = [suggest_paper(row) for row in fetch_papers(conn)]
    duplicates = duplicate_target_groups(suggestions)
    md_path, json_path, csv_path = write_reports(
        suggestions,
        duplicates,
        db_path=db_path,
        stamp=args.stamp,
        limit=max(1, args.limit),
    )
    counts = Counter(item.risk_level for item in suggestions)
    changed = sum(1 for item in suggestions if item.issues)
    print(f"papers={len(suggestions)}")
    print(f"changed_or_flagged={changed}")
    print(f"review={counts.get('review', 0)}")
    print(f"auto_candidate={counts.get('auto_candidate', 0)}")
    print(f"ok={counts.get('ok', 0)}")
    print(f"duplicate_target_groups={len(duplicates)}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")
    print(f"csv={relative_to_root(csv_path)}")


if __name__ == "__main__":
    main()
