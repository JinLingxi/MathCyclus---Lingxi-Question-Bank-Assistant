"""Rehearse or apply the explicitly reviewed 651-position replacement atomically."""
import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.database_service import connect_existing_database
from services.position_replacement_service import execute_replacement


def snapshot_database(source,target):
    src=sqlite3.connect(Path(source).resolve().as_uri()+"?mode=ro",uri=True)
    dst=sqlite3.connect(target)
    try:src.backup(dst)
    finally:src.close();dst.close()


def check_result(conn,baseline,plan,result):
    old=sqlite3.connect(Path(baseline).resolve().as_uri()+"?mode=ro",uri=True);old.row_factory=sqlite3.Row
    replacements={x["question_id"] for x in result["replaced"]}
    response_ids=set(result["updated_new_formal_questions"])
    for row in old.execute("SELECT * FROM question"):
        after=dict(conn.execute("SELECT * FROM question WHERE question_id=?",(row["question_id"],)).fetchone())
        if row["question_id"] not in replacements|response_ids:
            if after!=dict(row):raise ValueError("范围外正式题变化")
        elif row["question_id"] in response_ids:
            if any(after[k]!=row[k] for k in row.keys() if k not in
                   {"answer_tex","solution_tex","canonical_tex","updated_at"}):
                raise ValueError("答案迁移目标非答案字段变化")
    for entry in plan["entries"]:
        q=conn.execute("SELECT * FROM question WHERE question_id=?",(entry["question_id"],)).fetchone()
        d=conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?",(entry["draft_id"],)).fetchone()
        if q["stem_tex"]!=entry["draft_before"]["stem_tex"] or q["choices_json"]!=entry["draft_before"]["choices_json"]:
            raise ValueError("覆盖后题干选项与可信草稿不一致")
        if d["review_status"]!="committed":raise ValueError("覆盖草稿未完成")
        for field in ("answer_tex","solution_tex"):
            if q[field]!=d[field]:raise ValueError("覆盖后的答案与草稿不同")
    recovery_by_old={r["source_question_id"]:r["recovery_draft_id"] for r in result["recovery"]}
    routes_by_old={r["source_question_id"]:r for r in result["response_routes"]}
    preserved=0
    for entry in plan["entries"]:
        for field in ("answer_tex","solution_tex"):
            original=entry["old"][field]
            if not original.strip():continue
            if entry["question_id"] in recovery_by_old:
                recovered=conn.execute(f"SELECT {field} FROM question_import_draft WHERE draft_id=?",
                                       (recovery_by_old[entry["question_id"]],)).fetchone()[0]
                if recovered!=original:raise ValueError("旧答案保全不完整")
            else:
                route=routes_by_old[entry["question_id"]]
                value=conn.execute(f"SELECT {field} FROM question_import_draft WHERE draft_id=?",
                                  (route["target_draft_id"],)).fetchone()[0]
                if value.strip()!=original.strip():raise ValueError("旧答案未复制到指定归属")
            preserved+=1
    if conn.execute("SELECT COUNT(*) FROM question").fetchone()[0]!=old.execute("SELECT COUNT(*) FROM question").fetchone()[0]:
        raise ValueError("覆盖不应改变正式题数量")
    if conn.execute("PRAGMA quick_check").fetchone()[0]!="ok":raise ValueError("数据库检查失败")
    old.close()
    return {"status":"ok","replacement_count":len(replacements),"new_answer_destinations":len(response_ids),
            "recovery_drafts":len(result["recovery"]),"original_nonempty_response_fields_preserved":preserved,
            "unrelated_formal_questions_unchanged":True,"question_count_unchanged":True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--plan",required=True,type=Path);p.add_argument("--output",required=True,type=Path)
    p.add_argument("--apply",action="store_true");a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    plan=json.loads(a.plan.read_text(encoding="utf8"))
    stamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    db=ROOT/"data/mathcyclus.sqlite3"
    with tempfile.TemporaryDirectory(prefix="position_replacement_",ignore_cleanup_errors=True) as directory:
        backup=(ROOT/"data/backups"/f"before_position_replacement_{stamp}.sqlite3") if a.apply else Path(directory)/"before.sqlite3"
        snapshot_database(db,backup)
        working=db if a.apply else Path(directory)/"working.sqlite3"
        if not a.apply:snapshot_database(backup,working)
        asset_root=(ROOT/"assets/questions"/("position_replacement_"+stamp)) if a.apply else Path(directory)/"assets"
        conn=connect_existing_database(str(working))
        try:
            conn.execute("BEGIN IMMEDIATE")
            with patch("services.asset_service.ASSET_ROOT",asset_root):
                result=execute_replacement(conn,plan,copy_assets=True)
            validation=check_result(conn,backup,plan,result)
            conn.commit()
            result.update(mode="apply" if a.apply else "isolated_rehearsal",validation=validation,
                          backup=str(backup) if a.apply else "isolated_temp_backup",
                          asset_root=str(asset_root) if a.apply else "isolated_temp_assets")
        except Exception:
            conn.rollback()
            raise
        finally:conn.close()
    a.output.parent.mkdir(parents=True,exist_ok=True)
    with a.output.open("x",encoding="utf8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({"mode":result["mode"],"validation":validation,"routing_counts":result["routing_counts"]},ensure_ascii=False))

if __name__=="__main__":main()
