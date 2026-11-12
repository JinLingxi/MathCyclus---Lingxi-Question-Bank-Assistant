"""Audit the five exam-ingestion task trees; normalize only explicit fill-blank punctuation."""

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.question_text_format_service import normalize_fill_blank_stop
from services.import_service import (
    _get_draft_question_from_conn, _draft_content_hash_from_conn, _record_draft_review_event_conn,
)


def table_digest(conn,table):
    rows=[tuple(row) for row in conn.execute('SELECT * FROM "'+table+'" ORDER BY rowid')]
    return hashlib.sha256(json.dumps(rows,ensure_ascii=False).encode("utf-8")).hexdigest()


def audit(conn):
    conn.row_factory = sqlite3.Row
    nodes = [dict(row) for row in conn.execute("SELECT * FROM import_batch")]
    roots = {row["batch_id"] for row in nodes if row["import_type"] == "codex_task"}
    owners = {root: root for root in roots}
    while True:
        previous = len(owners)
        for row in nodes:
            if row.get("parent_batch_id") in owners:
                owners[row["batch_id"]] = owners[row["parent_batch_id"]]
        if len(owners) == previous:
            break
    changes, findings, papers = [], [], defaultdict(list)
    statuses, counts, warnings = Counter(), Counter(), Counter()
    for row in conn.execute("SELECT * FROM question_import_draft ORDER BY draft_id"):
        record = dict(row)
        if record["batch_id"] not in owners:
            continue
        extra = json.loads(record["extra_json"] or "{}")
        year = str(extra.get("detected_year") or "")
        statuses[record["review_status"]] += 1
        counts[year] += 1
        if record["review_status"] != "needs_review":
            continue
        choices = json.loads(record["choices_json"] or "[]")
        fields = [("stem_tex",record["stem_tex"]), ("answer_tex",record["answer_tex"]),
                  ("solution_tex",record["solution_tex"])] + [
                      (f"choices[{index+1}]",text) for index,text in enumerate(choices)]
        reasons = []
        new_stem = normalize_fill_blank_stop(record["stem_tex"])
        if new_stem != record["stem_tex"]:
            changes.append({"draft_id":record["draft_id"],"before":record["stem_tex"],"after":new_stem,
                            "year":year,"source":extra.get("detected_source"),
                            "number":extra.get("detected_question_number")})
        for field,text in fields:
            if re.search(r"\\par(?![A-Za-z])",text):
                reasons.append({"kind":"par_command","field":field})
            if "\ufffd" in text or re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]",text):
                reasons.append({"kind":"replacement_or_control_character","field":field})
            if re.search(r"(?<!\\)\\n(?![A-Za-z])",text):
                reasons.append({"kind":"literal_newline_escape","field":field})
            if len(re.findall(r"(?<!\\)\$",text)) % 2:
                reasons.append({"kind":"unpaired_math_dollar","field":field})
            balance = 0
            for index,char in enumerate(text):
                if char not in "{}":continue
                slash_count=0
                previous=index-1
                while previous>=0 and text[previous]=="\\":
                    slash_count+=1;previous-=1
                if slash_count%2:continue
                balance += 1 if char == "{" else -1
                if balance < 0: break
            if balance:
                reasons.append({"kind":"unbalanced_braces","field":field})
        if record["question_type_id"] in (1,2) and len(choices) != 4:
            reasons.append({"kind":"choice_count_review","count":len(choices)})
        for key in ("source_recheck_required","needs_manual_asset_review"):
            if extra.get(key): reasons.append({"kind":key})
        if extra.get("source_warning"):
            reasons.append({"kind":"source_warning","detail":extra["source_warning"]})
        if not extra.get("source_pages"):
            reasons.append({"kind":"source_pages_missing"})
        if not record["stem_tex"].strip():
            reasons.append({"kind":"empty_stem"})
        if reasons:
            findings.append({"draft_id":record["draft_id"],"year":year,"source":extra.get("detected_source"),
                             "number":extra.get("detected_question_number"),"findings":reasons})
            warnings.update(reason["kind"] for reason in reasons)
        key = (year,str(extra.get("detected_source") or ""),str(extra.get("detected_question_number") or ""))
        papers[key].append(record["draft_id"])
    collisions = [{"year":key[0],"source":key[1],"number":key[2],"draft_ids":ids}
                  for key,ids in papers.items() if len(ids)>1]
    return {"created_at":datetime.now().astimezone().isoformat(),"scope":"codex_task_descendants",
            "year_counts":dict(counts),"statuses":dict(statuses),"punctuation_changes":changes,
            "finding_counts":dict(warnings),"findings":findings,"same_position_groups":collisions,
            "limitations":["Static TeX checks do not establish source fidelity or image semantics.",
                           "Blank answers and solutions are allowed; not counted as defects.",
                           "Root task summary fields are not assumed authoritative."]}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    db=ROOT/"data/mathcyclus.sqlite3"
    conn=sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True)
    report=audit(conn);conn.close()
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.apply and report["punctuation_changes"]:
        args.output.with_suffix(".dryrun.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup=ROOT/"data/backups"/("fill_blank_punctuation_"+stamp+".sqlite3")
        source=sqlite3.connect(db);target=sqlite3.connect(backup)
        source.backup(target);target.close()
        source.row_factory=sqlite3.Row
        try:
            source.execute("BEGIN IMMEDIATE")
            current=audit(source)
            if current["punctuation_changes"]!=report["punctuation_changes"]:
                raise ValueError("预演后草稿范围发生变化")
            protected=("question","question_asset","paper_question","book_exercise_question",
                       "topic_question","question_import_draft_asset","import_batch")
            protected_before={table:table_digest(source,table) for table in protected}
            rows_before={row["draft_id"]:dict(row) for row in source.execute("SELECT * FROM question_import_draft")}
            modified_ids=set()
            for change in report["punctuation_changes"]:
                draft=_get_draft_question_from_conn(source,change["draft_id"])
                if draft["stem_tex"]!=change["before"] or draft["review_status"]!="needs_review" or draft["approved_content_hash"]:
                    raise ValueError("草稿已变化或存在审批，停止修正")
                # Preserve the stored preview; only the same punctuation pattern changes.
                preview=normalize_fill_blank_stop(draft["normalized_tex"] or "")
                source.execute("UPDATE question_import_draft SET stem_tex=?,normalized_tex=?,updated_at=CURRENT_TIMESTAMP WHERE draft_id=?",
                               (change["after"],preview,change["draft_id"]))
                updated=_get_draft_question_from_conn(source,change["draft_id"])
                digest=_draft_content_hash_from_conn(source,updated)
                source.execute("UPDATE question_import_draft SET content_hash=? WHERE draft_id=?",(digest,change["draft_id"]))
                _record_draft_review_event_conn(source,updated,stage="content_edit",
                    from_status="needs_review",to_status="needs_review",decision="edit",content_hash=digest,
                    operator="fill_blank_punctuation",reason="按用户要求将指定填空横线后的中文句号改为英文句点")
                modified_ids.add(change["draft_id"])
            for row in source.execute("SELECT * FROM question_import_draft"):
                before=rows_before[row["draft_id"]];after=dict(row)
                allowed={"stem_tex","normalized_tex","content_hash","updated_at"} if row["draft_id"] in modified_ids else set()
                if any(before[key]!=after[key] for key in before if key not in allowed):
                    raise ValueError("非目标字段发生变化")
            if any(table_digest(source,table)!=protected_before[table] for table in protected):
                raise ValueError("受保护表发生变化")
            if source.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("外键检查失败")
            source.commit()
            report["protected_tables_unchanged"]=list(protected)
            report["non_target_draft_fields_unchanged"]=True
        except Exception:source.rollback();raise
        finally:source.close()
        report["backup"]=backup.relative_to(ROOT).as_posix()
        report["applied"]=len(report["punctuation_changes"])
    with args.output.open("x",encoding="utf-8") as output:json.dump(report,output,ensure_ascii=False,indent=2)
    lines=["# 归档前原始来源疑点清单","",
           "以下为草稿保留的原页疑点，请人工对照；不是自动修复清单。","",
           "| 年份 | 试卷 | 题号 | 草稿ID | 原始备注 |",
           "| --- | --- | --- | --- | --- |"]
    for item in sorted(report["findings"],key=lambda x:(x["year"],str(x["source"]),str(x["number"]))):
        for finding in item["findings"]:
            if finding["kind"]=="source_warning":
                values=[item["year"],item["source"],item["number"],item["draft_id"],finding["detail"]]
                lines.append("| "+" | ".join(str(value).replace("|","／").replace("\n"," ") for value in values)+" |")
    args.output.with_suffix(".warnings.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    print(json.dumps({key:report[key] for key in ("year_counts","statuses","finding_counts")},ensure_ascii=False))
    print("punctuation_changes="+str(len(report["punctuation_changes"]))+" same_position_groups="+str(len(report["same_position_groups"])))


if __name__=="__main__":main()
