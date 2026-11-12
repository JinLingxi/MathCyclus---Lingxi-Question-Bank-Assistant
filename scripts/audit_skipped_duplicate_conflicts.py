"""Explain skipped duplicate/position-conflict drafts without changing any records."""

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.import_service import find_paper_position_conflict
from services.asset_service import resolve_asset_record_path,file_hash
from services.question_similarity_service import score_question_pair,normalize_similarity_text


def presentation(text):
    text=re.sub(r"\\(?:questionasset|includegraphics)(?:\[[^\]]*\])?\{[^{}]*\}"," IMAGE ",text)
    text=re.sub(r"\\(?:dfrac|tfrac)\b",lambda m:r"\frac",text)
    text=re.sub(r"\\(?:left|right)\b","",text)
    text=re.sub(r"\\hspace\s*\{[^{}]*\}"," BLANK ",text)
    text=re.sub(r"\\(?:par)\b","",text)
    return re.sub(r"[\s$，,。．.；;：:（()）]","",text)


def choices(value):
    parsed=json.loads(value or "[]")
    return [str(v) for v in parsed] if isinstance(parsed,list) else []


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",required=True,type=Path)
    args=parser.parse_args()
    if args.output.exists():raise FileExistsError(args.output)
    report=json.loads((ROOT/"reports/nonduplicate_applied_20261103.json").read_text(encoding="utf-8"))
    db=ROOT/"data/mathcyclus.sqlite3"
    conn=sqlite3.connect(db.as_uri()+"?mode=ro",uri=True);conn.row_factory=sqlite3.Row
    pair_rows=[];rows=[]
    for event in report["events"]:
        if event["status"] not in {"position_conflict","exact_duplicate"}:continue
        d=dict(conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?",(event["draft_id"],)).fetchone())
        extra=json.loads(d["extra_json"] or "{}")
        conflicts=find_paper_position_conflict(str(db),extra)
        position_ids={r["question_id"] for r in conflicts}
        assets=[dict(a) for a in conn.execute("SELECT * FROM question_import_draft_asset WHERE draft_id=? ORDER BY role,sort_order,draft_asset_id",(d["draft_id"],))]
        def hashes(items):
            values=[]
            for asset in items:
                path=resolve_asset_record_path(asset,project_root=ROOT)
                values.append({"role":asset.get("role"),"sha256":file_hash(path) if path else "MISSING"})
            return values
        draft_images=hashes(assets)
        candidates=[]
        for qid in event.get("matches",[]):
            q=dict(conn.execute("SELECT * FROM question WHERE question_id=?",(qid,)).fetchone())
            qassets=[dict(a) for a in conn.execute("SELECT * FROM question_asset WHERE question_id=? ORDER BY role,sort_order,asset_id",(qid,))]
            formal_images=hashes(qassets)
            detail=score_question_pair(d["stem_tex"],q["stem_tex"],left_choices=d["choices_json"],
                right_choices=q["choices_json"],left_question_type_id=d["question_type_id"],
                right_question_type_id=q["question_type_id"])
            same_choices=choices(d["choices_json"])==choices(q["choices_json"])
            same_text=d["stem_tex"]==q["stem_tex"] and same_choices
            presentation_equal=(presentation(d["stem_tex"])==presentation(q["stem_tex"])
                and [presentation(v) for v in choices(d["choices_json"])]==[presentation(v) for v in choices(q["choices_json"])])
            images_equal=draft_images==formal_images
            type_equal=d["question_type_id"]==q["question_type_id"]
            if same_text and images_equal and type_equal:category="text_choices_images_identical"
            elif presentation_equal and images_equal and type_equal:category="presentation_difference_only_candidate"
            elif (same_text or presentation_equal) and not images_equal:category="text_close_images_different_review"
            elif normalize_similarity_text(d["stem_tex"])[0]==normalize_similarity_text(q["stem_tex"])[0]:
                category="normalized_stem_same_options_or_details_differ"
            else:category="content_differs_requires_source_review"
            candidate={"question_id":qid,"same_position_now":qid in position_ids,"category":category,
                "type_equal":type_equal,"choices_equal":same_choices,"image_bytes_equal":images_equal,
                "draft_images":draft_images,"formal_images":formal_images,
                "stem_text_ratio":round(SequenceMatcher(None,presentation(d["stem_tex"]),presentation(q["stem_tex"]),autojunk=False).ratio(),4),
                "classifier_kind":detail["kind"],"score":detail.get("score"),"differences":detail.get("differences",[]),
                "formal_stem":q["stem_tex"],"formal_choices":choices(q["choices_json"]),
                "formal_answer_present":bool(q["answer_tex"]),"formal_solution_present":bool(q["solution_tex"])}
            candidates.append(candidate)
            pair_rows.append({"draft_id":d["draft_id"],"original_skip":event["status"],"year":extra.get("detected_year"),
                "source":extra.get("detected_source"),"number":extra.get("detected_question_number"),
                **{k:candidate[k] for k in ("question_id","same_position_now","category","type_equal",
                    "choices_equal","image_bytes_equal","stem_text_ratio","classifier_kind")}})
        priority=["text_choices_images_identical","presentation_difference_only_candidate",
                  "text_close_images_different_review","normalized_stem_same_options_or_details_differ",
                  "content_differs_requires_source_review"]
        best=min((c["category"] for c in candidates),key=priority.index)
        rows.append({"draft_id":d["draft_id"],"original_skip":event["status"],"year":extra.get("detected_year"),
            "source":extra.get("detected_source"),"number":extra.get("detected_question_number"),
            "best_category":best,"current_position_ids":sorted(position_ids),
            "overlap_with_position":bool(position_ids.intersection(event.get("matches",[]))),
            "draft_stem":d["stem_tex"],"draft_choices":choices(d["choices_json"]),
            "source_warning":extra.get("source_warning") or "","candidates":candidates})
    summary={}
    for status in ("position_conflict","exact_duplicate"):
        subset=[r for r in rows if r["original_skip"]==status]
        summary[status]={"drafts":len(subset),"categories":dict(Counter(r["best_category"] for r in subset)),
                         "same_matched_question_in_position_now":sum(r["overlap_with_position"] for r in subset)}
    output={"mode":"read_only","summary":summary,"rows":rows,"modified_records":0,
            "limitations":["Presentation comparison is a review heuristic, not mathematical equivalence.",
                           "Image byte differences require source inspection; identical bytes alone do not prove correct placement.",
                           "Original skip groups are disjoint; position conflicts were checked before exact content duplicates."]}
    with args.output.open("x",encoding="utf-8") as target:json.dump(output,target,ensure_ascii=False,indent=2)
    with args.output.with_suffix(".csv").open("x",encoding="utf-8-sig",newline="") as target:
        writer=csv.DictWriter(target,fieldnames=list(pair_rows[0]));writer.writeheader();writer.writerows(pair_rows)
    print(json.dumps(summary,ensure_ascii=False))
    conn.close()


if __name__=="__main__":main()
