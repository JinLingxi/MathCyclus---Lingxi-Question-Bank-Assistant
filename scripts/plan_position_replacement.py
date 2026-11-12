"""Read-only answer/solution routing plan before replacing trusted-source drafts."""
import argparse
import json
import re
import sqlite3
import sys
from collections import Counter,defaultdict
from difflib import SequenceMatcher
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.response_matching_service import canonical,numeric,score


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output",required=True,type=Path);a=p.parse_args()
    if a.output.exists():raise FileExistsError(a.output)
    conn=sqlite3.connect((ROOT/"data/mathcyclus.sqlite3").as_uri()+"?mode=ro",uri=True);conn.row_factory=sqlite3.Row
    skipped=json.loads((ROOT/"reports/skipped_duplicate_conflicts_20261103.json").read_text(encoding="utf8"))
    conflicts=[x for x in skipped["rows"] if x["original_skip"]=="position_conflict"]
    scoped=json.loads((ROOT/"reports/nonduplicate_applied_20261103.json").read_text(encoding="utf8"))
    ids={x["draft_id"] for x in scoped["events"]}
    draft_rows={r["draft_id"]:dict(r) for r in conn.execute("SELECT * FROM question_import_draft") if r["draft_id"] in ids}
    formal_for_draft={x["draft_id"]:x["question_id"] for x in scoped["events"] if x["status"]=="committed"}
    conflict_targets={x["draft_id"]:x["candidates"][0]["question_id"] for x in conflicts}
    formal_for_draft.update(conflict_targets)
    normalized={i:canonical(d["stem_tex"]) for i,d in draft_rows.items()}
    index=defaultdict(set)
    for i,text in normalized.items():
        for gram in {text[k:k+3] for k in range(len(text)-2)}:index[gram].add(i)
    entries=[]
    for conflict in conflicts:
        did=conflict["draft_id"];draft=draft_rows[did];qid=conflict_targets[did]
        old=dict(conn.execute("SELECT * FROM question WHERE question_id=?",(qid,)).fetchone())
        answer=bool(old["answer_tex"].strip());solution=bool(old["solution_tex"].strip())
        entry={"draft_id":did,"question_id":qid,"year":conflict["year"],"paper":conflict["source"],
               "number":conflict["number"],"old":old,"draft_before":draft,"answer_present":answer,
               "solution_present":solution,"same_position_text_score":round(score(old["stem_tex"],draft["stem_tex"]),5)}
        if answer or solution:
            grams={canonical(old["stem_tex"])[k:k+3] for k in range(len(canonical(old["stem_tex"]))-2)}
            hits=Counter(i for gram in grams for i in index.get(gram,()))
            candidates=set(i for i,_ in hits.most_common(40));candidates.add(did)
            ranked=[]
            for target in candidates:
                d=draft_rows[target]
                ratio=score(old["stem_tex"],d["stem_tex"])
                old_choices=json.loads(old["choices_json"] or "[]");new_choices=json.loads(d["choices_json"] or "[]")
                choice_scores=[score(x,y) for x,y in zip(old_choices,new_choices)]
                rank={"draft_id":target,"formal_question_id":formal_for_draft.get(target),
                      "score":round(ratio,5),"numbers_equal":numeric(old["stem_tex"])==numeric(d["stem_tex"]),
                      "type_equal":old["question_type_id"]==d["question_type_id"],
                      "choices_equal":len(old_choices)==len(new_choices) and all(canonical(x)==canonical(y) for x,y in zip(old_choices,new_choices)),
                      "choice_scores":[round(s,4) for s in choice_scores]}
                ranked.append(rank)
            ranked.sort(key=lambda x:(x["score"],x["numbers_equal"],x["choices_equal"]),reverse=True)
            entry["candidates"]=ranked[:5]
            best=ranked[0]
            # Text alignment alone never decides changed numeric conditions/options.
            reliable=(best["score"]>=.97 and best["numbers_equal"] and best["type_equal"] and best["choices_equal"])
            # Near ties to identical/new shared-paper questions are listed explicitly;
            # choose the source-position target if its own evidence is equally strong.
            own=next((x for x in ranked if x["draft_id"]==did),None)
            if own and own["score"]>=.97 and own["numbers_equal"] and own["type_equal"] and own["choices_equal"]:
                best=own;reliable=True
            entry["route"]=best if reliable else None
            entry["routing_status"]="matched_same_position" if reliable and best["draft_id"]==did else (
                "matched_other_draft" if reliable else "requires_review")
        else:entry["routing_status"]="no_answer_or_solution"
        entries.append(entry)
    result={"mode":"read_only","entries":entries,"counts":dict(Counter(x["routing_status"] for x in entries)),
            "modified_records":0}
    with a.output.open("x",encoding="utf8") as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result["counts"],ensure_ascii=False));conn.close()

if __name__=="__main__":main()
