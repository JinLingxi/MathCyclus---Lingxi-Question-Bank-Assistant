"""Append only completed visual paper modules to an isolated draft DB, then install with fingerprint guard."""
import argparse
import hashlib
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.import_service import create_import_batch,insert_draft_question,normalize_draft_question,stable_id
from services.asset_service import collect_asset_reference_issues


def fingerprint(conn,table):
    rows=sorted(json.dumps(list(r),ensure_ascii=False,default=lambda v:{"blob_hex":v.hex()} if isinstance(v,bytes) else str(v)) for r in conn.execute('SELECT * FROM "'+table+'"'))
    return hashlib.sha256("\n".join(rows).encode()).hexdigest()


def backup(source,target):
    s=sqlite3.connect(source.resolve().as_uri()+"?mode=ro",uri=True);t=sqlite3.connect(target)
    s.backup(t);t.close();s.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--year",type=int,required=True);p.add_argument("--apply",action="store_true")
    p.add_argument("--batch",default="third",help="Unique batch name; preserves earlier staged plans")
    a=p.parse_args()
    if not a.batch.replace("_", "").isalnum():p.error("batch must contain only letters, numbers, or underscores")
    work=ROOT/f"data/imports/codex_{a.year}_restart";live=ROOT/"data/mathcyclus.sqlite3"
    stage=work/f"prepared_visual_additions_{a.batch}.sqlite3";plan_path=work/f"additions_{a.batch}_plan.json"
    if a.apply:
        plan=json.loads(plan_path.read_text(encoding="utf8"))
        browser=json.loads((work/"preview_browser_checks.json").read_text(encoding="utf8"))
        assert browser["status"]=="ok" and browser["payload_sha256"]==plan["payload_sha256"]
        assert hashlib.sha256((work/"visual_payloads.json").read_bytes()).hexdigest()==plan["payload_sha256"]
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S")
        recover=ROOT/"data/backups"/f"before_{a.year}_visual_additions_{stamp}.sqlite3";backup(live,recover)
        src=sqlite3.connect(stage);src.row_factory=sqlite3.Row
        dst=sqlite3.connect(live);dst.row_factory=sqlite3.Row
        try:
            dst.execute("PRAGMA foreign_keys=ON");dst.execute("BEGIN IMMEDIATE")
            for table,digest in plan["live_fingerprints"].items():
                assert fingerprint(dst,table)==digest,("live_changed",table)
            for table,rows in plan["additions"].items():
                for identifier in rows:
                    pk={"import_batch":"batch_id","question_import_draft":"draft_id","question_import_draft_asset":"draft_asset_id","draft_review_event":"event_id"}[table]
                    row=src.execute('SELECT * FROM "'+table+'" WHERE '+pk+'=?',(identifier,)).fetchone()
                    columns=row.keys()
                    dst.execute('INSERT INTO "'+table+'" ('+','.join(columns)+') VALUES ('+','.join('?' for _ in columns)+')',tuple(row))
            for bid,summary in plan["summaries"].items():
                dst.execute("UPDATE import_batch SET summary=? WHERE batch_id=?",(summary,bid))
            assert not dst.execute("PRAGMA foreign_key_check").fetchall()
            dst.commit()
        except Exception:dst.rollback();raise
        finally:src.close();dst.close()
        report={"year":a.year,"status":"partial_ready_for_human_review","papers":plan["paper_count"],
                "questions":len(plan["additions"]["question_import_draft"]),"images":len(plan["additions"]["question_import_draft_asset"]),
                "backup":str(recover.relative_to(ROOT)),"formal_questions_unchanged":True,"year_complete":False}
        (work/"delivery.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf8")
        print(json.dumps(report,ensure_ascii=False));return
    checks=json.loads((work/"visual_compile_checks.json").read_text(encoding="utf8"))
    assert all(c["compile_passed"] and not c["overfull_boxes"] and not c["missing_characters"] for c in checks["compile_checks"])
    payload=json.loads((work/"visual_payloads.json").read_text(encoding="utf8"))
    inventory_file=("1997_1999_ingestion_inventory.json" if 1997<=a.year<=1999
                    else "2000_2004_ingestion_inventory.json" if 2000<=a.year<=2004
                    else "2005_2008_ingestion_inventory.json")
    inventory=json.loads((ROOT/"reports"/inventory_file).read_text(encoding="utf8"))
    root_id=inventory["root_batch_id"]
    if stage.exists():raise FileExistsError(stage)
    backup(live,stage)
    with sqlite3.connect(live) as c:
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        fingerprints={table:fingerprint(c,table) for table in tables}
        nodes=list(c.execute("SELECT batch_id,subset_key,subset_label FROM import_batch WHERE parent_batch_id=? AND hierarchy_level=1",(root_id,)))
        papers={label:bid for bid,key,label in nodes if key.startswith(str(a.year)+"|")}
        existing={r[0] for r in c.execute("SELECT source_item_id FROM question_import_draft WHERE source_item_id LIKE ?",(f"{a.year}-visual-%",))}
        payload=[item for item in payload if item["source_item_id"] not in existing]
        assert payload,"No new drafts"
    additions={"import_batch":[],"question_import_draft":[],"question_import_draft_asset":[],"draft_review_event":[]}
    leafs={};counts={};summaries={}
    for item in payload:
        name=item["extra"]["transcription_paper_name"];paper=papers[name];kind=item["question_type_id"]
        if (paper,kind) not in leafs:
            leaf=create_import_batch(str(stage),"codex_subset",inventory["source"],"subset",
                f"{a.year}-visual-{paper}-type-{kind}",task_id=root_id,parent_batch_id=paper,hierarchy_level=2,
                subset_key=f"type-{kind}",subset_label={1:"单选题",2:"多选题",3:"填空题",4:"解答题"}[kind])
            leafs[paper,kind]=leaf;additions["import_batch"].append(leaf)
        did,validation=insert_draft_question(str(stage),leafs[paper,kind],normalize_draft_question(item),
                                             int(item["source_item_id"].rsplit("q",1)[1]))
        assert not validation["errors"] and not validation["warnings"]
        additions["question_import_draft"].append(did);counts[name]=counts.get(name,0)+1
    with sqlite3.connect(stage) as c:
        c.row_factory=sqlite3.Row
        for name,count in counts.items():
            summary=json.dumps({"year":a.year,"paper_name":name,"stage":"ready_for_review",
                "transcription_complete":True,"question_count":count},ensure_ascii=False)
            summaries[papers[name]]=summary
            c.execute("UPDATE import_batch SET summary=? WHERE batch_id=?",(summary,papers[name]))
        for table,pk in [("question_import_draft_asset","draft_asset_id"),("draft_review_event","event_id")]:
            ids=additions["question_import_draft"];marks=",".join("?" for _ in ids)
            additions[table]=[r[0] for r in c.execute(f"SELECT {pk} FROM {table} WHERE draft_id IN ({marks})",ids)]
        assert not c.execute("PRAGMA foreign_key_check").fetchall()
    plan={"year":a.year,"payload_sha256":hashlib.sha256((work/"visual_payloads.json").read_bytes()).hexdigest(),
          "live_fingerprints":fingerprints,"additions":additions,"summaries":summaries,"paper_count":len(counts)}
    plan_path.write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding="utf8")
    print(json.dumps({"status":"isolated_drafts_staged","papers":len(counts),"questions":len(payload),"images":len(additions["question_import_draft_asset"])},ensure_ascii=False))


if __name__=="__main__":main()
