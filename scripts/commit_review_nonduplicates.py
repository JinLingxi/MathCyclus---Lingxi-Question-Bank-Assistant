"""Execute the review UI non_duplicate policy with backup and per-item journal."""
import argparse
import json
import sqlite3
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from collections import Counter,defaultdict

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.ingestion_review_service import task_tree,descendants,paper_drafts,metadata
from services.import_service import (get_draft_question,find_paper_position_conflict,
    normalize_draft_question,validate_draft_question,approve_draft_for_commit,commit_draft_to_question)
from services.question_similarity_service import extract_similarity_payload,score_question_pair


def scope(db,task_ids=None):
    nodes,roots=task_tree(db)
    if task_ids:
        requested=set(task_ids)
        known={root['batch_id'] for root in roots}
        if requested-known:
            raise ValueError(f'Unknown task roots: {sorted(requested-known)}')
        roots=[root for root in roots if root['batch_id'] in requested]
    rows=[];seen=set()
    for root in roots:
        tree=descendants(nodes,root["batch_id"])
        papers=[node for node in nodes if node["batch_id"] in tree and node.get("hierarchy_level")==1]
        papers.sort(key=lambda p:(str(metadata(p.get("metadata_json")).get("year") or ""),p.get("subset_key") or "",p["batch_id"]))
        for paper in papers:
            for row in paper_drafts(db,nodes,paper["batch_id"]):
                if row["draft_id"] not in seen:
                    seen.add(row["draft_id"]);rows.append(row["draft_id"])
    return rows


def run(db,ids,journal,*,copy_assets):
    exact_index=defaultdict(list)
    with sqlite3.connect(db) as conn:
        conn.row_factory=sqlite3.Row
        for row in conn.execute("SELECT question_id,stem_tex,choices_json,question_type_id FROM question"):
            value=dict(row)
            payload=extract_similarity_payload(value["stem_tex"],value["choices_json"],value["question_type_id"])
            exact_index[payload["stem_norm"]].append(value)
    counts=Counter();events=[]
    with journal.open("x",encoding="utf-8") as output:
        for index,draft_id in enumerate(ids):
            draft=get_draft_question(db,draft_id)
            event={"draft_id":draft_id,"ordinal":index+1}
            if draft["review_status"] in {"committed","rejected"}:
                event["status"]="already_processed"
            else:
                extra=metadata(draft.get("extra_json"))
                conflicts=find_paper_position_conflict(db,extra)
                payload=extract_similarity_payload(draft["stem_tex"],draft["choices_json"],draft["question_type_id"])
                # Exact classification requires equal stem_norm. Unlike the UI's
                # ranking query, similar candidates need not be ranked: this mode
                # never excludes them. Reuse the actual pair classifier unchanged.
                exact=[]
                for candidate in exact_index[payload["stem_norm"]]:
                    detail=score_question_pair(draft["stem_tex"],candidate["stem_tex"],
                        left_choices=draft["choices_json"],right_choices=candidate["choices_json"],
                        left_question_type_id=draft["question_type_id"],right_question_type_id=candidate["question_type_id"])
                    if detail["kind"]=="exact":exact.append(candidate["question_id"])
                if conflicts:
                    event.update(status="position_conflict",matches=[r["question_id"] for r in conflicts])
                elif exact:
                    event.update(status="exact_duplicate",matches=exact)
                else:
                    validation=validate_draft_question(normalize_draft_question(draft))
                    if validation.get("errors") or validation.get("warnings"):
                        event.update(status="validation_reminder",validation=validation)
                    else:
                        try:
                            approve_draft_for_commit(db,draft_id,operator="user_requested_non_duplicate",
                                note="用户明确要求按录入本批非重复题目批量审核录入")
                            result=commit_draft_to_question(db,draft_id,operator="user_requested_non_duplicate",copy_assets=copy_assets)
                            event.update(status="committed",question_id=result["question_id"])
                            exact_index[payload["stem_norm"]].append({
                                "question_id":result["question_id"],"stem_tex":draft["stem_tex"],
                                "choices_json":draft["choices_json"],"question_type_id":draft["question_type_id"]})
                        except (ValueError,KeyError,sqlite3.IntegrityError) as exc:
                            event.update(status="commit_error",error=str(exc))
            counts[event["status"]]+=1;events.append(event)
            output.write(json.dumps(event,ensure_ascii=False)+"\n");output.flush()
            if (index+1)%500==0:print(json.dumps({"processed":index+1,"total":len(ids),"counts":dict(counts)}),flush=True)
    return {"counts":dict(counts),"events":events}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply",action="store_true")
    parser.add_argument("--output",required=True,type=Path)
    parser.add_argument("--max-year",type=int,help="Restrict task drafts by detected source year (inclusive)")
    parser.add_argument("--task-id",action="append",help="Limit scope to this root task; repeat for multiple tasks")
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    db=ROOT/"data/mathcyclus.sqlite3"
    ids=scope(str(db),args.task_id)
    if args.max_year is not None:
        with sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True) as conn:
            allowed=set()
            for draft_id,extra_json in conn.execute("SELECT draft_id,extra_json FROM question_import_draft"):
                year=metadata(extra_json).get("detected_year")
                if str(year).isdigit() and 0<int(year)<=args.max_year:
                    allowed.add(draft_id)
        ids=[draft_id for draft_id in ids if draft_id in allowed]
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.apply:
        stamp=datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup=ROOT/"data/backups"/f"before_nonduplicate_commit_{stamp}.sqlite3"
        with sqlite3.connect(db) as source,sqlite3.connect(backup) as target:source.backup(target)
        source.close();target.close()
        result=run(str(db),ids,args.output.with_suffix(".journal.jsonl"),copy_assets=True)
        result["backup"]=backup.relative_to(ROOT).as_posix()
    else:
        with tempfile.TemporaryDirectory(prefix="nonduplicate_rehearsal_",ignore_cleanup_errors=True) as directory:
            clone=Path(directory)/"review.sqlite3"
            with sqlite3.connect(db.resolve().as_uri()+"?mode=ro",uri=True) as source,sqlite3.connect(clone) as target:source.backup(target)
            source.close();target.close()
            result=run(str(clone),ids,args.output.with_suffix(".journal.jsonl"),copy_assets=False)
    result.update(mode="apply" if args.apply else "temporary_database_rehearsal",scoped_drafts=len(ids),max_year=args.max_year,task_ids=args.task_id)
    with args.output.open("x",encoding="utf-8") as output:json.dump(result,output,ensure_ascii=False,indent=2)
    print(json.dumps({k:v for k,v in result.items() if k!="events"},ensure_ascii=False),flush=True)


if __name__=="__main__":main()
