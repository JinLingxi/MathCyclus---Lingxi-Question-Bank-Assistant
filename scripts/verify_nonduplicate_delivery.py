"""Verify a journaled non-duplicate commit against its exact pre-operation backup."""
import argparse
import json
import sqlite3
import sys
from collections import Counter,defaultdict
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.asset_service import file_hash


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report",required=True,type=Path)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    report=json.loads(args.report.read_text(encoding="utf-8"))
    before=sqlite3.connect((ROOT/report["backup"]).resolve().as_uri()+"?mode=ro",uri=True)
    current=sqlite3.connect((ROOT/"data/mathcyclus.sqlite3").as_uri()+"?mode=ro",uri=True)
    before.row_factory=current.row_factory=sqlite3.Row
    old_questions={r["question_id"]:dict(r) for r in before.execute("SELECT * FROM question")}
    for qid,record in old_questions.items():
        assert dict(current.execute("SELECT * FROM question WHERE question_id=?",(qid,)).fetchone())==record, qid
    old_assets={r["asset_id"]:dict(r) for r in before.execute("SELECT * FROM question_asset")}
    for aid,record in old_assets.items():
        assert dict(current.execute("SELECT * FROM question_asset WHERE asset_id=?",(aid,)).fetchone())==record,aid
    assert [tuple(row) for row in before.execute("SELECT * FROM question_import_draft_asset ORDER BY draft_asset_id")]==[
        tuple(row) for row in current.execute("SELECT * FROM question_import_draft_asset ORDER BY draft_asset_id")]
    committed=[e for e in report["events"] if e["status"]=="committed"]
    old_drafts={r["draft_id"]:dict(r) for r in before.execute("SELECT * FROM question_import_draft")}
    ids={e["draft_id"] for e in committed}
    for row in current.execute("SELECT * FROM question_import_draft"):
        original=old_drafts[row["draft_id"]]
        if row["draft_id"] not in ids:
            assert dict(row)==original,row["draft_id"]
    checked_assets=0
    by_year=defaultdict(Counter)
    for event in report["events"]:
        extra=json.loads(old_drafts[event["draft_id"]]["extra_json"] or "{}")
        by_year[str(extra.get("detected_year") or "unknown")][event["status"]]+=1
    for e in committed:
        q=current.execute("SELECT * FROM question WHERE question_id=?",(e["question_id"],)).fetchone()
        d=current.execute("SELECT * FROM question_import_draft WHERE draft_id=?",(e["draft_id"],)).fetchone()
        assert d["review_status"]=="committed"
        for field in ("stem_tex","choices_json","answer_tex","solution_tex"):
            assert q[field]==old_drafts[e["draft_id"]][field],(e["draft_id"],field)
        assets=list(current.execute("SELECT * FROM question_asset WHERE question_id=?",(e["question_id"],)))
        originals=list(before.execute("SELECT * FROM question_import_draft_asset WHERE draft_id=?",(e["draft_id"],)))
        assert len(assets)==len(originals),(e["draft_id"],"asset_count")
        assert sorted(file_hash(ROOT/a["file_path"]) for a in assets)==sorted(file_hash(ROOT/a["source_path"]) for a in originals)
        checked_assets+=len(assets)
    assert current.execute("SELECT COUNT(*) FROM question").fetchone()[0]==len(old_questions)+len(committed)
    assert current.execute("PRAGMA quick_check").fetchone()[0]=="ok"
    assert not current.execute("PRAGMA foreign_key_check").fetchall()
    result={"status":"ok","existing_questions_preserved":len(old_questions),
            "existing_assets_preserved":len(old_assets),"new_questions":len(committed),
            "new_assets_verified":checked_assets,"untouched_drafts_preserved":len(old_drafts)-len(ids),
            "counts":report["counts"],"draft_statuses":dict(current.execute("SELECT review_status,COUNT(*) FROM question_import_draft GROUP BY review_status")),
            "by_year":{year:dict(counts) for year,counts in sorted(by_year.items())},
            "database_integrity":"ok","foreign_key_issues":0}
    before.close();current.close()
    with args.output.open("x",encoding="utf-8") as output:json.dump(result,output,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False))


if __name__=="__main__":main()
