"""Read-only SQLite candidate retrieval and explicit exam constraints."""
from __future__ import annotations

import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass, replace

from services.database_service import readonly_database_connection
from services.question_db_service import QuestionListFilters, _build_where
from services.exam_selection_service import build_exam_intent_profile
from services.asset_service import preferred_asset_alias

TYPE_LABELS = {"single_choice": "单选题", "multiple_choice": "多选题",
               "fill_blank": "填空题", "solution": "解答题", "other": "其他"}
SAME_RELATIONS = {"same_question", "same_stem", "duplicate", "exact"}
REF_PREFIX = "sqlite:"


def question_ref(question_id):
    return REF_PREFIX + str(question_id)


def ref_question_id(ref):
    return str(ref)[len(REF_PREFIX):] if str(ref).startswith(REF_PREFIX) else ""


@dataclass(frozen=True)
class CandidateOptions:
    subjects: tuple[str, ...] = ()
    primary_only: bool = False
    minimum_difficulty: float = 0
    maximum_difficulty: float = 6
    include_unknown: bool = True
    target_difficulty: float = 3
    intent: str = ""
    seed: int = 42


def row_fingerprint(row):
    keys = ("question_id", "question_type_id", "type_code", "stem_tex", "choices_json", "difficulty",
            "tags_json", "note", "asset_fingerprint", "answer_tex", "solution_tex",
            "knowledge", "primary_knowledge", "source", "year", "paper_number")
    return hashlib.sha256(json.dumps({k: row.get(k) for k in keys},
        ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def load_exam_rows(db_path, filters=None, options=None, question_ids=None):
    """Filter the whole bank before imposing any candidate budget."""
    filters, options = filters or QuestionListFilters(), options or CandidateOptions()
    inherited_chapter = filters.chapter
    where, params = _build_where(replace(filters, chapter=""))
    clauses = [where.removeprefix("WHERE ")] if where else []
    if question_ids is not None:
        ids = list(dict.fromkeys(question_ids))
        if not ids:
            return []
        if len(ids) > 200:
            raise ValueError("一次最多读取 200 道手选题")
        clauses.append("q.question_id IN (" + ",".join("?" for _ in ids) + ")")
        params.extend(ids)
    else:
        if options.minimum_difficulty > options.maximum_difficulty:
            raise ValueError("难度范围无效")
        difficulty = "q.difficulty BETWEEN ? AND ?"
        if options.include_unknown:
            difficulty = "(" + difficulty + " OR q.difficulty IS NULL)"
        clauses.append(difficulty)
        params.extend([options.minimum_difficulty, options.maximum_difficulty])
        for subjects in ([inherited_chapter] if inherited_chapter else [], list(options.subjects)):
            if not subjects:
                continue
            names = ",".join("?" for _ in subjects)
            primary = "AND qka.is_primary=1" if options.primary_only else ""
            fallback = "l.detected_chapter IN (" + names + ")"
            fallback_params = list(subjects)
            if not options.primary_only:
                fallback += " OR " + " OR ".join(
                    "instr('，'||replace(COALESCE(l.detected_topic,''),',','，')||'，', '，'||?||'，')>0" for _ in subjects)
                fallback_params += subjects
            clauses.append(f"""(EXISTS (SELECT 1 FROM question_knowledge_area qka
                JOIN knowledge_area ka ON ka.knowledge_area_id=qka.knowledge_area_id
                WHERE qka.question_id=q.question_id {primary} AND ka.name IN ({names}))
                OR (NOT EXISTS (SELECT 1 FROM question_knowledge_area qa WHERE qa.question_id=q.question_id)
                AND ({fallback})))""")
            params.extend(subjects)
            params.extend(fallback_params)
    sql = """SELECT q.question_id,q.question_type_id,q.stem_tex,q.choices_json,q.difficulty,
        q.tags_json,q.note,q.usage_count,q.answer_tex,q.solution_tex,
        qt.code AS type_code,qt.name AS type_name,l.detected_year AS year,
        l.detected_source AS source,l.detected_question_number AS paper_number,
        l.detected_chapter,l.detected_topic
        FROM question q LEFT JOIN question_type qt ON qt.question_type_id=q.question_type_id
        LEFT JOIN legacy_question_map l ON l.question_id=q.question_id"""
    with readonly_database_connection(db_path) as conn:
        conn.execute("BEGIN")
        rows = [dict(r) for r in conn.execute(sql + (" WHERE " + " AND ".join(clauses) if clauses else "") +
                                            " ORDER BY q.question_id", params)]
        knowledge = defaultdict(list)
        for r in conn.execute("""SELECT qka.question_id,ka.name,qka.is_primary FROM question_knowledge_area qka
            JOIN knowledge_area ka ON ka.knowledge_area_id=qka.knowledge_area_id ORDER BY ka.name"""):
            knowledge[r["question_id"]].append((r["name"], bool(r["is_primary"])))
        assets = defaultdict(list)
        for r in conn.execute("SELECT * FROM question_asset ORDER BY asset_id"):
            asset = dict(r)
            assets[r["question_id"]].append({"alias": preferred_asset_alias(asset),
                "role": asset["role"], "bytes": asset["file_hash"] or asset["file_path"],
                "order": asset.get("sort_order") or 0})
    for row in rows:
        row["type_code"] = row["type_code"] if row["type_code"] in TYPE_LABELS else "other"
        associations = knowledge[row["question_id"]]
        row["knowledge"] = [name for name, _ in associations] or [
            s for s in str(row.get("detected_topic") or row.get("detected_chapter") or "").replace(",", "，").split("，") if s]
        row["primary_knowledge"] = [name for name, primary in associations if primary]
        if not row["primary_knowledge"] and row.get("detected_chapter"):
            row["primary_knowledge"] = [row["detected_chapter"]]
        row["asset_fingerprint"] = sorted(assets[row["question_id"]],
            key=lambda a: (a["alias"], a["role"], a["order"], a["bytes"]))
        # Exact bytes and asset identities only. Do not collapse formulas by
        # deleting commands, numbers, option order, or figure references.
        signature = [row["stem_tex"], row["choices_json"], row["question_type_id"], row["asset_fingerprint"]]
        if not row["asset_fingerprint"] and any(s in row["stem_tex"] + row["choices_json"] for s in ("\\questionasset", "\\includegraphics")):
            signature.append(row["question_id"])
        row["exact_signature"] = hashlib.sha256(json.dumps(signature, ensure_ascii=False).encode()).hexdigest()
        row["fingerprint"] = row_fingerprint(row)
    return rows


def build_candidate_pool(db_path, *, filters=None, options=None, limit=500, quotas=None, pinned_ids=()):
    options = options or CandidateOptions()
    rows = load_exam_rows(db_path, filters, options)
    rng = random.Random(options.seed)
    rng.shuffle(rows)
    parent = {}
    def find(qid):
        parent.setdefault(qid, qid)
        if parent[qid] != qid:
            parent[qid] = find(parent[qid])
        return parent[qid]
    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)
    with readonly_database_connection(db_path) as conn:
        relations = [dict(r) for r in conn.execute("SELECT question_id_a,question_id_b,relation_type,review_status FROM question_equivalence")]
    for relation in relations:
        if relation["review_status"] == "approved" and relation["relation_type"] in SAME_RELATIONS:
            union(relation["question_id_a"], relation["question_id_b"])
    exact = {}
    for row in rows:
        qid = row["question_id"]
        if row["exact_signature"] in exact:
            union(qid, exact[row["exact_signature"]])
        exact[row["exact_signature"]] = qid
    all_subjects = sorted({name for row in rows for name in row["knowledge"]})
    profile = build_exam_intent_profile(options.intent, all_subjects)
    for row in rows:
        haystack = row["stem_tex"] + row["tags_json"] + row["note"]
        hits = [token for token in profile["tokens"] if token in haystack]
        row["intent_score"] = sum(min(8, len(token)) for token in hits)
        row["group"] = find(row["question_id"])
        row["reason"] = "、".join(filter(None, [
            "命中所选板块" if options.subjects else "",
            f"意图词命中 {len(hits)} 项" if hits else "",
            "难度未知" if row["difficulty"] is None else f"已标注 {row['difficulty']} 星",
        ]))
    pinned = set(pinned_ids)
    rows.sort(key=lambda r: (r["question_id"] in pinned, r["difficulty"] is not None,
        r["intent_score"], -abs((r["difficulty"] if r["difficulty"] is not None else options.target_difficulty) - options.target_difficulty),
        -int(r["usage_count"] or 0)), reverse=True)
    unique, seen = [], set()
    for row in rows:
        if row["group"] not in seen:
            seen.add(row["group"])
            unique.append(row)
    if limit and limit < sum((quotas or {}).values()):
        raise ValueError("候选池规模不能小于题型配额总数")
    if limit and len(unique) > limit:
        # Reserve requested type quotas before filling the rest of the budget.
        chosen, used = [], set()
        for code, count in (quotas or {}).items():
            for row in [r for r in unique if r["type_code"] == code][:count]:
                chosen.append(row); used.add(row["question_id"])
        chosen += [r for r in unique if r["question_id"] not in used][:max(0, limit - len(chosen))]
        unique = chosen
    return {"rows": unique, "matched_count": len(rows), "distinct_count": len(seen),
        "type_counts": dict(Counter(r["type_code"] for r in rows)),
        "unknown_count": sum(r["difficulty"] is None for r in rows),
        "eligible_ids": [r["question_id"] for r in rows], "groups": {qid: find(qid) for qid in parent},
        "relations": relations, "intent_profile": profile}


def plan_selection(pool, *, target_count, pinned_rows=(), quotas=None, excluded_ids=(), unknown_limit=200):
    if not 1 <= target_count <= 200:
        raise ValueError("本次题量须为 1—200")
    if unknown_limit < 0 or (quotas and any(code not in TYPE_LABELS for code in quotas)):
        raise ValueError("未知难度上限或题型配额无效")
    if quotas and (any(int(v) < 0 for v in quotas.values()) or sum(quotas.values()) != target_count):
        raise ValueError("题型配额总数必须等于目标题量")
    selected = list(pinned_rows)
    errors, warnings = [], []
    if len(selected) > target_count:
        errors.append("手选题已超过目标题量，请增加目标题量或调整试题篮。")
    unknown = sum(r["difficulty"] is None for r in selected)
    if unknown > unknown_limit:
        errors.append("手选题中的未知难度题数已超过本次上限。")
    groups, signatures, ids = set(), set(), set()
    for row in selected:
        qid = row["question_id"]
        group = pool["groups"].get(qid, qid)
        if group in groups or row["exact_signature"] in signatures:
            errors.append("手选题含已确认的同题或完全相同内容，请先核对试题篮。")
        groups.add(group); signatures.add(row["exact_signature"]); ids.add(qid)
        if qid not in pool["eligible_ids"]:
            warnings.append(qid + " 是范围外手选题，按锁定题保留。")
    excluded = set(excluded_ids)
    pinned_counts = Counter(r["type_code"] for r in selected)
    for code, count in (quotas or {}).items():
        if pinned_counts[code] > count:
            errors.append(TYPE_LABELS[code] + "手选题数超过配额。")
    if quotas:
        for code in pinned_counts:
            if code not in quotas:
                errors.append(TYPE_LABELS[code] + "手选题不在本次配额内。")
    requirements = [(code, max(0, count - pinned_counts[code])) for code, count in (quotas or {}).items()] if quotas else [(None, max(0, target_count - len(selected)))]
    shortages = []
    for code, need in requirements:
        got = 0
        for row in pool["rows"]:
            qid = row["question_id"]
            group = pool["groups"].get(qid, qid)
            if got >= need:
                break
            if qid in excluded or qid in ids or group in groups or row["exact_signature"] in signatures:
                continue
            if code and row["type_code"] != code:
                continue
            if row["difficulty"] is None and unknown >= unknown_limit:
                continue
            selected.append(row); ids.add(qid); groups.add(group); signatures.add(row["exact_signature"])
            unknown += row["difficulty"] is None
            got += 1
        if got < need:
            shortages.append({"type": TYPE_LABELS.get(code, "题目"), "missing": need - got})
    for relation in pool["relations"]:
        if relation["question_id_a"] in ids and relation["question_id_b"] in ids and not (
            relation["review_status"] == "approved" and relation["relation_type"] in SAME_RELATIONS):
            warnings.append(f"{relation['question_id_a']} 与 {relation['question_id_b']} 有{relation['relation_type']}关系，请核对。")
    stems = {}
    for row in selected:
        stem = row["stem_tex"]
        if stem in stems and row["exact_signature"] != stems[stem]["exact_signature"]:
            warnings.append(stems[stem]["question_id"] + " 与 " + row["question_id"] + " 题干相同、选项或图片不同，请核对。")
        stems[stem] = row
    return {"ready": not errors and not shortages and len(selected) == target_count,
            "rows": selected, "errors": errors, "shortages": shortages,
            "warnings": warnings, "unknown_count": unknown, "kept_count": len(pinned_rows)}


def ensure_plan_current(db_path, rows):
    current = {r["question_id"]: r for r in load_exam_rows(db_path, question_ids=[r["question_id"] for r in rows])}
    changed = [r["question_id"] for r in rows if r["question_id"] not in current or
               current[r["question_id"]]["fingerprint"] != r["fingerprint"]]
    if changed:
        raise ValueError("以下题目已变化或被移除，请重新生成候选池：" + "、".join(changed))
    parent = {}
    def find(qid):
        parent.setdefault(qid, qid)
        if parent[qid] != qid:
            parent[qid] = find(parent[qid])
        return parent[qid]
    with readonly_database_connection(db_path) as conn:
        for r in conn.execute("SELECT question_id_a,question_id_b,relation_type FROM question_equivalence WHERE review_status='approved'"):
            if r["relation_type"] in SAME_RELATIONS:
                a,b=find(r["question_id_a"]),find(r["question_id_b"])
                parent[a]=b
    groups=[find(r["question_id"]) for r in rows]
    if len(set(groups)) != len(groups):
        raise ValueError("初选题目之间的同题关系已变化，请重新生成候选池。")
