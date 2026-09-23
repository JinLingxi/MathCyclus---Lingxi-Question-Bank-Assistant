from __future__ import annotations

# 只读对照 G 类旧 TeX、SQLite 与试卷标准名录。
import argparse
import csv
import re
import sqlite3
import unicodedata
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from scan_tex_library import extract_problem_header, iter_question_tex_files, read_text, relative_to_root

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "试卷标准名录.xlsx"
DEFAULT_DB = ROOT / "data" / "mathcyclus.sqlite3"
DEFAULT_CHAPTERS = ROOT / "chapters"
DEFAULT_REPORTS = ROOT / "reports"
MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
YEAR_RE = re.compile(r"(?:19|20)\d{2}")
VOLUME_RE = re.compile(r"(?P<prefix>全国|新课标|新高考|课标|全国卷|新课标卷|新高考卷)(?P<marker>[一二三123])(?=卷|$)")
AFTER_ROLL_RE = re.compile(r"(?P<prefix>全国|新课标|新高考|课标)卷(?P<marker>I{1,3})(?=$|（)")

COLUMNS = [
    "\u5ba1\u6838\u5e8f\u53f7", "\u95ee\u9898\u7c7b\u578b", "\u6570\u636e\u6765\u6e90", "\u5f53\u524d\u5e74\u4efd", "\u8bd5\u5377\u7c7b\u578b", "\u5f53\u524d\u8bd5\u5377\u540d", "\u5f52\u4e00\u5316\u540d\u79f0",
    "SQLite paper_id", "SQLite\u5173\u8054\u9898\u76ee\u6570", "\u65e7TeX\u6587\u4ef6\u6570", "\u65e7\u6587\u4ef6\u793a\u4f8b",
    "\u540c\u5e74\u5019\u90091", "\u5019\u90091\u76f8\u4f3c\u5ea6", "\u540c\u5e74\u5019\u90092", "\u5019\u90092\u76f8\u4f3c\u5ea6", "\u540c\u5e74\u5019\u90093", "\u5019\u90093\u76f8\u4f3c\u5ea6",
    "\u5efa\u8bae\u64cd\u4f5c", "\u4eba\u5de5\u786e\u8ba4", "\u6700\u7ec8\u5e74\u4efd", "\u6700\u7ec8\u8bd5\u5377\u540d", "\u5ba1\u6838\u5907\u6ce8",
]


@dataclass(frozen=True)
class CatalogEntry:
    year: int
    name: str
    normalized: str


@dataclass
class Observation:
    year: int | None
    name: str
    normalized: str
    paper_ids: set[str] = field(default_factory=set)
    question_ids: set[str] = field(default_factory=set)
    legacy_paths: list[str] = field(default_factory=list)

    @property
    def sources(self) -> str:
        return "+".join(name for name, present in (("SQLite", self.paper_ids), ("旧TeX", self.legacy_paths)) if present)


@dataclass(frozen=True)
class Match:
    status: str
    issues: tuple[str, ...]
    candidates: tuple[tuple[str, float], ...]
    cross_years: tuple[int, ...]
    action: str
    review: bool


def resolve(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else ROOT / path


def parse_year(value: object) -> int | None:
    match = YEAR_RE.search(str(value or ""))
    return int(match.group()) if match else None


def normalize_name(value: object) -> str:
    name = unicodedata.normalize("NFKC", str(value or "")).strip()
    name = name.translate(str.maketrans({"Ⅰ": "I", "Ⅱ": "II", "Ⅲ": "III"}))
    name = re.sub(r"\s+", "", name).replace("(", "（").replace(")", "）")
    name = name.replace("文科", "文").replace("理科", "理")
    markers = {"一": "I", "二": "II", "三": "III", "1": "I", "2": "II", "3": "III"}
    name = VOLUME_RE.sub(lambda match: f"{match.group('prefix')}{markers[match.group('marker')]}", name)
    name = AFTER_ROLL_RE.sub(lambda match: f"{match.group('prefix')}{match.group('marker')}卷", name)
    return "上海春考卷" if name in {"上海春季高考", "上海春季卷", "上海春考"} else name


def column_index(reference: str) -> int:
    result = 0
    for char in filter(str.isalpha, reference.upper()):
        result = result * 26 + ord(char) - 64
    return result - 1


def read_xlsx(path: Path, sheet_name: str) -> list[list[str]]:
    with zipfile.ZipFile(path) as archive:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        targets = {item.attrib["Id"]: item.attrib["Target"] for item in rels.findall(f"{{{PKG_REL_NS}}}Relationship")}
        sheet = next((item for item in workbook.findall(f".//{{{MAIN_NS}}}sheet") if item.attrib.get("name") == sheet_name), None)
        if sheet is None:
            raise ValueError(f"工作表不存在：{sheet_name}")
        target = targets[sheet.attrib[f"{{{DOC_REL_NS}}}id"]].lstrip("/")
        target = target if target.startswith("xl/") else f"xl/{target}"
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            shared = ["".join(node.text or "" for node in item.iter(f"{{{MAIN_NS}}}t")) for item in root.findall(f"{{{MAIN_NS}}}si")]
        root = ET.fromstring(archive.read(target))
        rows: list[list[str]] = []
        for row in root.findall(f".//{{{MAIN_NS}}}row"):
            values: dict[int, str] = {}
            for item in row.findall(f"{{{MAIN_NS}}}c"):
                index, kind = column_index(item.attrib.get("r", "A1")), item.attrib.get("t", "")
                if kind == "inlineStr":
                    node = item.find(f"{{{MAIN_NS}}}is")
                    value = "" if node is None else "".join(text.text or "" for text in node.iter(f"{{{MAIN_NS}}}t"))
                else:
                    node = item.find(f"{{{MAIN_NS}}}v")
                    raw = "" if node is None else node.text or ""
                    value = shared[int(raw)] if kind == "s" and raw else raw
                values[index] = value
            if values:
                rows.append([values.get(index, "") for index in range(max(values) + 1)])
        return rows


def load_catalog(path: Path) -> list[CatalogEntry]:
    rows = read_xlsx(path, "试卷标准名录")
    headers = {str(value).strip(): index for index, value in enumerate(rows[0])}
    missing = {"年份", "试卷类型", "试卷名"} - headers.keys()
    if missing:
        raise ValueError(f"试卷标准名录缺少列：{', '.join(sorted(missing))}")
    result, seen = [], set()
    for row in rows[1:]:
        get = lambda name: row[headers[name]] if headers[name] < len(row) else ""
        year, paper_type, name = parse_year(get("年份")), str(get("试卷类型")).strip().upper(), str(get("试卷名")).strip()
        if year is not None and paper_type == "G" and name and (year, name) not in seen:
            seen.add((year, name))
            result.append(CatalogEntry(year, name, normalize_name(name)))
    return result


def observation(store: dict[tuple[int | None, str], Observation], year: int | None, name: str) -> Observation:
    name = name.strip() or "（空试卷名）"
    return store.setdefault((year, name), Observation(year, name, normalize_name(name)))


def load_sqlite(path: Path, store: dict[tuple[int | None, str], Observation]) -> None:
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        for row in connection.execute("""SELECT p.paper_id,p.year,p.paper_name,p.source_name,pq.question_id
            FROM paper p LEFT JOIN paper_question pq ON pq.paper_id=p.paper_id
            WHERE UPPER(TRIM(COALESCE(p.paper_series,'')))='G' ORDER BY p.year,p.source_name,p.paper_id"""):
            item = observation(store, parse_year(row["year"]), row["source_name"] or row["paper_name"] or "")
            item.paper_ids.add(row["paper_id"])
            if row["question_id"]:
                item.question_ids.add(row["question_id"])
    finally:
        connection.close()


def load_legacy(path: Path, store: dict[tuple[int | None, str], Observation]) -> None:
    for tex_path in iter_question_tex_files(path):
        header = extract_problem_header(read_text(tex_path))
        if header.get("category", "").strip().upper() != "G" and not re.search(r"(?:^|-)G(?:-|$)", tex_path.stem, re.I):
            continue
        year = parse_year(header.get("year")) or parse_year(tex_path.parent.name) or parse_year(tex_path.name)
        name = header.get("source", "").strip()
        if not name:
            parts = tex_path.stem.split("-")
            name = parts[2] if len(parts) >= 3 else ""
        observation(store, year, name).legacy_paths.append(relative_to_root(tex_path))


def match_item(item: Observation, by_year: dict[int, list[CatalogEntry]], years_by_name: dict[str, set[int]]) -> Match:
    entries = by_year.get(item.year or -1, [])
    exact = [entry for entry in entries if entry.name == item.name]
    normalized = [entry for entry in entries if entry.normalized == item.normalized]
    candidates = sorted(((entry.name, SequenceMatcher(None, item.normalized, entry.normalized).ratio()) for entry in entries), key=lambda value: (-value[1], value[0]))[:3]
    issues: list[str] = []
    if exact:
        status, action, review = "规范名称完全匹配", "无需改名；仅处理附加问题（如有）", False
    elif len(normalized) == 1:
        status, action, review = "归一化后唯一匹配", f"可统一为：{normalized[0].name}", False
        candidates = [(normalized[0].name, 1.0)] + [value for value in candidates if value[0] != normalized[0].name]
    elif len(normalized) > 1:
        status, action, review, issues = "同年多个归一化候选", "人工选择同年标准名称", True, ["同年多个候选"]
    elif candidates and candidates[0][1] >= 0.72:
        status, action, review, issues = "同年高相似候选", "核对后填写最终试卷名", True, ["同年高相似候选"]
    else:
        status, action, review, issues = "\u672c\u5e74\u540d\u5f55\u672a\u5339\u914d", "\u6838\u5bf9\u5f53\u524d\u540d\u79f0\uff1b\u786e\u8ba4\u540e\u586b\u5199\u6700\u7ec8\u8bd5\u5377\u540d", True, ["\u672c\u5e74\u540d\u5f55\u672a\u5339\u914d"]
    if len(item.paper_ids) > 1:
        issues.append("同一名称对应多个paper_id")
        action, review = "确认后合并重复 paper 记录及关系", True
    if item.year is None:
        issues.append("缺少年份")
        action, review = "人工补充年份和最终试卷名", True
    if item.name == "（空试卷名）":
        issues.append("缺少试卷名")
        action, review = "人工补充最终试卷名", True
    return Match(status, tuple(issues or [status]), tuple(candidates[:3]), tuple(), action, review)


def make_row(index: int, item: Observation, result: Match) -> dict[str, object]:
    candidates = list(result.candidates) + [("", 0.0)] * (3 - len(result.candidates))
    examples = item.legacy_paths[:3]
    return {
        "审核序号": index, "问题类型": "；".join(result.issues), "数据来源": item.sources, "当前年份": item.year or "",
        "试卷类型": "G", "当前试卷名": item.name, "归一化名称": item.normalized, "SQLite paper_id": "；".join(sorted(item.paper_ids)),
        "SQLite关联题目数": len(item.question_ids), "旧TeX文件数": len(item.legacy_paths), "旧文件示例": " | ".join(examples),
        "同年候选2": candidates[1][0], "候选2相似度": f"{candidates[1][1]:.1%}" if candidates[1][0] else "",
        "同年候选3": candidates[2][0], "候选3相似度": f"{candidates[2][1]:.1%}" if candidates[2][0] else "",
        "人工确认": "", "最终年份": "", "最终试卷名": "", "审核备注": "",
    }


def write_csv(rows: list[dict[str, object]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def col_name(number: int) -> str:
    result = ""
    while number:
        number, remainder = divmod(number - 1, 26)
        result = chr(65 + remainder) + result
    return result


def cell(reference: str, value: object, style: int) -> str:
    return f'<c r="{reference}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{escape(str(value or ""))}</t></is></c>'


def sheet_xml(headers: list[str], rows: list[dict[str, object]], widths: dict[str, int]) -> str:
    columns = "".join(
        f'<col min="{index}" max="{index}" width="{widths.get(header, 18)}" customWidth="1"/>'
        for index, header in enumerate(headers, 1)
    )
    xml_rows = [
        '<row r="1" ht="30" customHeight="1">'
        + "".join(cell(f"{col_name(index)}1", header, 1) for index, header in enumerate(headers, 1))
        + "</row>"
    ]
    for row_number, row in enumerate(rows, 2):
        xml_rows.append(
            f'<row r="{row_number}">'
            + "".join(cell(f"{col_name(index)}{row_number}", row.get(header, ""), 2) for index, header in enumerate(headers, 1))
            + "</row>"
        )
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><worksheet xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}"><sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews><cols>{columns}</cols><sheetData>{''.join(xml_rows)}</sheetData><autoFilter ref="A1:{col_name(len(headers))}{max(1, len(rows) + 1)}"/></worksheet>'''


def write_xlsx(review: list[dict[str, object]], all_rows: list[dict[str, object]], notes: list[dict[str, object]], path: Path) -> None:
    sheets = [("待人工审核", COLUMNS, review), ("全部对照", COLUMNS, all_rows), ("审核说明", ["项目", "说明"], notes)]
    widths = {header: 18 for header in COLUMNS}
    widths.update({"问题类型": 28, "当前试卷名": 25, "归一化名称": 25, "SQLite paper_id": 28, "旧文件示例": 75, "建议操作": 40, "最终试卷名": 28, "审核备注": 45, "项目": 25, "说明": 100})
    content_types = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/><Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>']
    content_types += [f'<Override PartName="/xl/worksheets/sheet{index}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for index in range(1, 4)]
    content_types.append("</Types>")
    workbook_sheets = "".join(f'<sheet name="{escape(name)}" sheetId="{index}" r:id="rId{index}"/>' for index, (name, _, _) in enumerate(sheets, 1))
    workbook_rels = "".join(f'<Relationship Id="rId{index}" Type="{DOC_REL_NS}/worksheet" Target="worksheets/sheet{index}.xml"/>' for index in range(1, 4)) + f'<Relationship Id="rId4" Type="{DOC_REL_NS}/styles" Target="styles.xml"/>'
    styles = f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?><styleSheet xmlns="{MAIN_NS}"><fonts count="2"><font><sz val="11"/><name val="Microsoft YaHei"/></font><font><b/><color rgb="FFFFFFFF"/><sz val="11"/><name val="Microsoft YaHei"/></font></fonts><fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF5B4B8A"/></patternFill></fill></fills><borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders><cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs><cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/><xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0"><alignment horizontal="center" vertical="center" wrapText="1"/></xf><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"><alignment vertical="top" wrapText="1"/></xf></cellXfs><cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>'''
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "".join(content_types))
        archive.writestr("_rels/.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG_REL_NS}"><Relationship Id="rId1" Type="{DOC_REL_NS}/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        archive.writestr("xl/workbook.xml", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><workbook xmlns="{MAIN_NS}" xmlns:r="{DOC_REL_NS}"><sheets>{workbook_sheets}</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{PKG_REL_NS}">{workbook_rels}</Relationships>')
        archive.writestr("xl/styles.xml", styles)
        for index, (_, headers, rows) in enumerate(sheets, 1):
            archive.writestr(f"xl/worksheets/sheet{index}.xml", sheet_xml(headers, rows, widths))


def main() -> None:
    parser = argparse.ArgumentParser(description="只读生成 G 类试卷名称人工审核表。")
    parser.add_argument("--catalog", default=str(DEFAULT_CATALOG))
    parser.add_argument("--db", default=str(DEFAULT_DB))
    parser.add_argument("--chapters", default=str(DEFAULT_CHAPTERS))
    parser.add_argument("--reports", default=str(DEFAULT_REPORTS))
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d"))
    args = parser.parse_args()
    catalog_path, db_path, chapters, reports = map(resolve, (args.catalog, args.db, args.chapters, args.reports))
    for path, label in ((catalog_path, "标准名录"), (db_path, "SQLite 数据库"), (chapters, "旧 TeX 目录")):
        if not path.exists():
            raise SystemExit(f"{label}不存在：{path}")
    catalog = load_catalog(catalog_path)
    by_year: dict[int, list[CatalogEntry]] = defaultdict(list)
    years_by_name: dict[str, set[int]] = defaultdict(set)
    for entry in catalog:
        by_year[entry.year].append(entry)
        years_by_name[entry.normalized].add(entry.year)
    store: dict[tuple[int | None, str], Observation] = {}
    load_sqlite(db_path, store)
    load_legacy(chapters, store)
    results = [(item, match_item(item, by_year, years_by_name)) for item in sorted(store.values(), key=lambda value: (value.year or 0, value.name))]
    review_items = [(item, result) for item, result in results if result.review]
    review = [make_row(index, item, result) for index, (item, result) in enumerate(review_items, 1)]
    all_rows = [make_row(index, item, result) for index, (item, result) in enumerate(results, 1)]
    counts = Counter(issue for _, result in review_items for issue in result.issues)
    notes = [
        {"项目": "报告性质", "说明": "只读审核；未修改 SQLite、旧 TeX、目录结构或标准名录。"},
        {"项目": "审核范围", "说明": "仅试卷类型 G；其他类型不参与历史清洗。"},
        {"项目": "标准名录记录", "说明": len(catalog)},
        {"项目": "现有名称组合", "说明": len(results)},
        {"项目": "待人工审核", "说明": len(review)},
        {"项目": "需要填写", "说明": "请填写人工确认、最终年份、最终试卷名、审核备注。"},
        {"项目": "人工确认可填", "说明": "采用候选1/2/3、新增标准名、修正年份、暂不处理。"},
    ] + [{"项目": f"问题统计：{issue}", "说明": count} for issue, count in counts.most_common()]
    csv_path = reports / f"g_paper_catalog_manual_review_{args.stamp}.csv"
    xlsx_path = reports / f"g_paper_catalog_manual_review_{args.stamp}.xlsx"
    write_csv(review, csv_path)
    write_xlsx(review, all_rows, notes, xlsx_path)
    print(f"catalog_g={len(catalog)}\nobserved_g_name_groups={len(results)}\nmanual_review={len(review)}")
    for issue, count in counts.most_common():
        print(f"issue[{issue}]={count}")
    print(f"csv={relative_to_root(csv_path)}\nxlsx={relative_to_root(xlsx_path)}\nread_only=true")


if __name__ == "__main__":
    main()
