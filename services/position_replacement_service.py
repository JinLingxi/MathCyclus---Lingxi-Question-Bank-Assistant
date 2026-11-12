"""Trusted draft replacement with explicit answer routing and recovery preservation."""
from __future__ import annotations

import json
import re
from collections import Counter

from services.import_service import (
    _get_draft_question_from_conn,_draft_content_hash_from_conn,_record_draft_review_event_conn,
    _draft_row_to_input,validate_draft_question,_commit_draft_to_question_conn,
    _draft_preview_question,stable_id,compact_json,
)
from services.revision_service import insert_question_revision_from_conn

OPERATOR="user_requested_position_replacement"


def merge_response(existing,incoming):
    """Never silently replace an existing answer or analysis."""
    if not incoming.strip():return existing,"empty_source"
    if not existing.strip():return incoming,"copied"
    if existing.strip()==incoming.strip():return existing,"already_same"
    return existing,"conflict"


def execute_replacement(conn,plan,*,copy_assets=True):
    """Caller owns a single transaction and an independent pre-operation backup."""
    entries=plan["entries"]
    targets={e["draft_id"]:e["question_id"] for e in entries}
    if len(targets)!=651 and not plan.get("test_fixture"):
        raise ValueError("覆盖范围不是已确认的651道")
    old_question_ids={e["question_id"] for e in entries}
    if len(old_question_ids)!=len(entries):raise ValueError("同一正式题存在多个覆盖目标")
    for entry in entries:
        old=conn.execute("SELECT * FROM question WHERE question_id=?",(entry["question_id"],)).fetchone()
        if old is None or dict(old)!=entry["old"]:raise ValueError("旧题在预演后发生变化")
        d=_get_draft_question_from_conn(conn,entry["draft_id"])
        expected=entry["draft_before"]
        if any(d[k]!=v for k,v in expected.items()) or d["review_status"]!="needs_review":
            raise ValueError("草稿在预演后发生变化")
        if conn.execute("SELECT COUNT(*) FROM paper_question WHERE question_id=?",(entry["question_id"],)).fetchone()[0]!=1:
            raise ValueError("旧题存在多个来源关联，需独立处理")
    recovery_batch=stable_id("IB","position_answer_recovery",plan.get("created_at") or "20261103")
    recovery=[];routes=[];updates={};original_drafts={}
    def response_target(draft_id):
        if draft_id not in updates:
            d=_get_draft_question_from_conn(conn,draft_id)
            if not d:raise ValueError("解析归属草稿不存在")
            original_drafts[draft_id]=d
            updates[draft_id]={"answer_tex":d["answer_tex"],"solution_tex":d["solution_tex"]}
        return updates[draft_id]
    for entry in entries:
        old=entry["old"];route=entry.get("route")
        if not old["answer_tex"].strip() and not old["solution_tex"].strip():continue
        if not route:
            recovery.append((entry,"未找到可可靠对应的题目；保留原题及答案解析待核对"))
            continue
        target=route["draft_id"];values=response_target(target)
        outcome={}
        for field in ("answer_tex","solution_tex"):
            merged,status=merge_response(values[field],old[field])
            outcome[field]=status;values[field]=merged
        routes.append({"source_question_id":entry["question_id"],"target_draft_id":target,
                       "target_question_id":targets.get(target) or route.get("formal_question_id"),
                       "evidence":entry["routing_status"],"inspection_reason":entry.get("inspection_reason",""),
                       "fields":outcome})
        if "conflict" in outcome.values():
            recovery.append((entry,"目标已有不同答案或解析；保留全部旧版，不覆盖目标已有内容"))
    # Preserve uncertain content as explicit unapproved recovery drafts, not
    # attached to a guessed paper position or silently buried in a log.
    if recovery:
        conn.execute("INSERT INTO import_batch(batch_id,import_type,source_path,mode,summary) VALUES (?,?,?,?,?)",
            (recovery_batch,"answer_recovery","position_replacement","recovery_drafts",
             "覆盖旧题时保全未能可靠归属或有冲突的旧答案解析；需人工核对，不自动录入"))
    recovered=[]
    for index,(entry,reason) in enumerate(recovery,1):
        old=entry["old"];did=stable_id("D",recovery_batch,entry["question_id"])
        extra={"source_kind":"旧答案解析待核对","recovered_from_question_id":entry["question_id"],
               "replacement_draft_id":entry["draft_id"],"routing_candidates":entry.get("candidates",[]),
               "source_warning":reason,"old_paper_metadata":{"year":entry.get("year"),
                    "source":entry.get("paper"),"number":entry.get("number")}}
        conn.execute("""INSERT INTO question_import_draft(
            draft_id,batch_id,source_item_id,source_label,review_status,question_type_id,
            stem_tex,choices_json,answer_tex,solution_tex,difficulty,tags_json,note,raw_source_text,extra_json)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (did,recovery_batch,entry["question_id"],"旧题答案保全 "+entry["question_id"],"needs_review",
             old["question_type_id"],old["stem_tex"],old["choices_json"],old["answer_tex"],old["solution_tex"],
             old["difficulty"],old["tags_json"],reason,old.get("raw_source_tex") or "",compact_json(extra)))
        for asset in conn.execute("SELECT * FROM question_asset WHERE question_id=? ORDER BY sort_order,asset_id",
                                  (entry["question_id"],)).fetchall():
            conn.execute("""INSERT INTO question_import_draft_asset(
                draft_asset_id,draft_id,role,source_path,original_file_name,mime_type,file_hash,caption,sort_order,extra_json)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (stable_id("DA",did,asset["asset_id"]),did,asset["role"],asset["file_path"],
                 asset["original_file_name"],asset["mime_type"],asset["file_hash"],asset["caption"],
                 asset["sort_order"],compact_json({"original_asset_id":asset["asset_id"]})))
        d=_get_draft_question_from_conn(conn,did)
        conn.execute("UPDATE question_import_draft SET content_hash=? WHERE draft_id=?",
                     (_draft_content_hash_from_conn(conn,d),did))
        recovered.append({"source_question_id":entry["question_id"],"recovery_draft_id":did,"reason":reason})
    # Route responses before replacing any old question. Committed target drafts
    # are updated together with their exact new formal question.
    updated_existing=[]
    for did,values in updates.items():
        before=original_drafts[did]
        if all(values[field]==before[field] for field in values):continue
        conn.execute("UPDATE question_import_draft SET answer_tex=?,solution_tex=?,updated_at=CURRENT_TIMESTAMP WHERE draft_id=?",
                     (values["answer_tex"],values["solution_tex"],did))
        d=_get_draft_question_from_conn(conn,did)
        preview=_draft_preview_question("DRAFT",d)
        conn.execute("UPDATE question_import_draft SET normalized_tex=? WHERE draft_id=?",(preview["canonical_tex"],did))
        d=_get_draft_question_from_conn(conn,did);digest=_draft_content_hash_from_conn(conn,d)
        if before["review_status"]=="approved" and did not in targets:
            raise ValueError("解析目标已获批但尚未入库，需重新审查")
        conn.execute("UPDATE question_import_draft SET content_hash=? WHERE draft_id=?",(digest,did))
        _record_draft_review_event_conn(conn,d,stage="answer_relocation",from_status=before["review_status"],
            to_status=before["review_status"],decision="copy_response",content_hash=digest,operator=OPERATOR,
            reason="按用户指令从旧题迁移已匹配的答案解析，保留归属证据")
        if before["review_status"]=="committed":
            qids={r["target_question_id"] for r in routes if r["target_draft_id"]==did and r["target_question_id"]}
            if len(qids)!=1:raise ValueError("已录入解析目标的正式题ID不唯一")
            qid=next(iter(qids))
            if qid in old_question_ids:raise ValueError("跨题解析目标将被不相干覆盖")
            old=dict(conn.execute("SELECT * FROM question WHERE question_id=?",(qid,)).fetchone())
            if old["stem_tex"]!=before["stem_tex"] or old["choices_json"]!=before["choices_json"]:
                raise ValueError("目标正式题与新草稿内容不一致")
            for field in values:
                if old[field]!=before[field]:raise ValueError("目标正式题答案已独立修改")
            q={**old,**values}
            q["canonical_tex"]=_draft_preview_question(qid,d,base=q)["canonical_tex"]
            conn.execute("UPDATE question SET answer_tex=?,solution_tex=?,canonical_tex=?,updated_at=CURRENT_TIMESTAMP WHERE question_id=?",
                         (q["answer_tex"],q["solution_tex"],q["canonical_tex"],qid))
            after=dict(conn.execute("SELECT * FROM question WHERE question_id=?",(qid,)).fetchone())
            insert_question_revision_from_conn(conn,qid,"answer_relocation",old,after,operator=OPERATOR,
                                               note="匹配旧题答案解析归入新题；draft_id="+did)
            updated_existing.append(qid)
    replaced=[]
    related_before={"knowledge":[],"equivalence":[]}
    from services.equivalence_service import record_equivalence_event_from_conn
    # Replaced identities keep their stable question IDs, but old mathematical
    # classifications must not describe a newly corrected, unrelated stem.
    for index,entry in enumerate(entries,1):
        did,qid=entry["draft_id"],entry["question_id"]
        conn.execute("UPDATE question_import_draft SET proposed_action='update',target_question_id=? WHERE draft_id=?",(qid,did))
        d=_get_draft_question_from_conn(conn,did)
        validation=validate_draft_question(_draft_row_to_input(d))
        if validation["errors"] or validation["warnings"]:raise ValueError("替换草稿未通过校验："+did+str(validation))
        digest=_draft_content_hash_from_conn(conn,d)
        conn.execute("""UPDATE question_import_draft SET review_status='approved',content_hash=?,
            approved_content_hash=?,approved_by=?,approved_at=CURRENT_TIMESTAMP WHERE draft_id=?""",
            (digest,digest,OPERATOR,did))
        d=_get_draft_question_from_conn(conn,did)
        _record_draft_review_event_conn(conn,d,stage="human_review",from_status="needs_review",to_status="approved",
            decision="approve",content_hash=digest,operator=OPERATOR,
            reason="用户确认草稿正确，授权覆盖同位置旧题并保全旧答案解析")
        old_assets=[dict(row) for row in conn.execute("SELECT * FROM question_asset WHERE question_id=?",(qid,))]
        # Only replace asset registrations for this overwritten question. The
        # files remain for rollback/recovery, old aliases must not win lookup.
        conn.execute("DELETE FROM question_asset WHERE question_id=?",(qid,))
        result=_commit_draft_to_question_conn(conn,d,operator=OPERATOR,copy_assets=copy_assets,report_index=index)
        if result.get("asset_skipped_count"):raise ValueError("覆盖时图片复制不完整")
        related_before["knowledge"].extend(dict(row) for row in conn.execute(
            "SELECT * FROM question_knowledge_area WHERE question_id=?",(qid,)))
        topics=[value.strip() for value in re.split("[，,]",json.loads(d["extra_json"] or "{}").get("detected_topic") or "") if value.strip()]
        if topics:
            conn.execute("DELETE FROM question_knowledge_area WHERE question_id=?",(qid,))
            for order,name in enumerate(dict.fromkeys(topics)):
                area=conn.execute("SELECT knowledge_area_id FROM knowledge_area WHERE name=?",(name,)).fetchone()
                area_id=area["knowledge_area_id"] if area else stable_id("KA",name)
                if not area:conn.execute("INSERT INTO knowledge_area(knowledge_area_id,name) VALUES (?,?)",(area_id,name))
                conn.execute("""INSERT INTO question_knowledge_area(
                    question_id,knowledge_area_id,source,is_primary) VALUES (?,?,?,?)""",
                    (qid,area_id,"trusted_draft_replacement",int(order==0)))
        replaced.append({"draft_id":did,"question_id":qid,"old_assets":old_assets,"commit":result})
    changed_ids=set()
    from services.response_matching_service import canonical,score
    for entry in entries:
        old=entry["old"];new=entry["draft_before"]
        same=(score(old["stem_tex"],new["stem_tex"])>=.97
              and [canonical(v) for v in json.loads(old["choices_json"] or "[]")]==
                  [canonical(v) for v in json.loads(new["choices_json"] or "[]")])
        if not same:changed_ids.add(entry["question_id"])
    for relation in conn.execute("SELECT * FROM question_equivalence").fetchall():
        if relation["question_id_a"] not in changed_ids and relation["question_id_b"] not in changed_ids:continue
        if relation["review_status"]!="approved":continue
        original=dict(relation);related_before["equivalence"].append(original)
        conn.execute("UPDATE question_equivalence SET review_status='pending',updated_at=CURRENT_TIMESTAMP WHERE equivalence_id=?",
                     (relation["equivalence_id"],))
        record_equivalence_event_from_conn(conn,relation["equivalence_id"],action="replacement_requires_review",
            before_status="approved",after_status="pending",before_relation_type=relation["relation_type"],
            after_relation_type=relation["relation_type"],relation_source=OPERATOR,operator=OPERATOR,
            note="一侧题干按可信草稿覆盖，原等价关系保留并退回待核对")
    if conn.execute("PRAGMA foreign_key_check").fetchall():raise ValueError("覆盖后外键异常")
    return {"replaced":replaced,"response_routes":routes,"recovery":recovered,
            "updated_new_formal_questions":sorted(set(updated_existing)),
            "related_metadata_before":related_before,
            "routing_counts":dict(Counter(e["routing_status"] for e in entries))}
