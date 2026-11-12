"""Candidate inspection before committing an initial exam to the session basket."""
import hashlib
import json
from collections import Counter
from dataclasses import asdict

import streamlit as st

from services.database_service import DEFAULT_DATABASE_PATH
from services.knowledge_service import list_knowledge_areas
from services.question_db_service import QuestionListFilters
from services.smart_exam_service import (CandidateOptions, TYPE_LABELS, build_candidate_pool,
    plan_selection, ensure_plan_current, load_exam_rows, ref_question_id, question_ref)
from services.exam_selection_service import expand_selected_subjects


def inherited_filters(state):
    def text(key):
        value = str(state.get(key) or "")
        return "" if value.startswith("全部") else value
    def number(key):
        value = state.get(key)
        return int(value) if str(value).isdigit() else None
    return QuestionListFilters(keyword=str(state.get("db_browse_keyword") or ""),
        year=number("db_browse_year"), chapter=text("db_browse_chapter"),
        source_kind=text("db_browse_source_kind"), paper_series=text("db_browse_paper_series"),
        source=text("db_browse_source"), question_number=str(state.get("db_browse_source_question_number") or ""),
        question_type_id=number("db_browse_type_id"), difficulty=number("db_browse_difficulty"))


def render(theme, target_count, *, preview_question, sync_blocks, polish_intent):
    from html import escape
    from utils.smart_exam_layout import SMART_EXAM_CSS

    db = DEFAULT_DATABASE_PATH
    current_refs = list(st.session_state.get("exam_selected_qs", []))
    paper = "试卷" in str(theme)
    st.markdown(SMART_EXAM_CSS, unsafe_allow_html=True)
    presets = {"不限": ((0, 6), 3.0), "基础为主": ((0, 2), 1.5),
               "适中为主": ((2, 4), 3.0), "提升为主": ((4, 6), 5.0)}

    def apply_preset():
        selected = st.session_state["smart_exam_difficulty_preset"]
        if selected in presets:
            bounds, goal = presets[selected]
            st.session_state["smart_exam_range"] = bounds
            st.session_state["smart_exam_difficulty"] = goal

    def use_custom_range():
        st.session_state["smart_exam_difficulty_preset"] = "自定义范围"

    def reshuffle():
        st.session_state["smart_exam_seed"] = (int(st.session_state.get("smart_exam_seed", 42)) + 1) % 1000000
        st.session_state["smart_exam_refresh"] = True

    def request_candidates():
        st.session_state["smart_exam_generate_requested"] = True

    def request_plan():
        st.session_state["smart_exam_plan_requested"] = True

    def sync_target_count():
        value = int(st.session_state["smart_exam_target_count"])
        st.session_state["exam_q_count_input"] = value
        st.session_state["_count_widget"] = value

    if "smart_exam_difficulty_preset" not in st.session_state:
        st.session_state["smart_exam_difficulty_preset"] = (
            "不限" if tuple(st.session_state.get("smart_exam_range", (0, 6))) == (0, 6) else "自定义范围")

    with st.container(border=True):
        st.markdown('<span class="mc-smart-exam-root"></span>', unsafe_allow_html=True)
        header = st.empty()
        available = [r["name"] for r in list_knowledge_areas(db)]
        quota_mode = st.session_state.get("smart_exam_use_quotas", paper)
        common_columns = st.columns([2, 1], gap="medium") if quota_mode else st.columns([2, 1, .8], gap="medium")
        col_subjects, col_difficulty = common_columns[:2]
        with col_subjects:
            subjects = st.multiselect("知识板块", ["高考范围"] + available,
                placeholder="选择板块，留空表示全部", key="smart_exam_subjects")
        with col_difficulty:
            preset = st.selectbox("难度偏好", list(presets) + ["自定义范围"],
                key="smart_exam_difficulty_preset", on_change=apply_preset)
        if not quota_mode:
            with common_columns[2]:
                target_count = st.number_input("目标题数", min_value=1, value=int(target_count),
                    key="smart_exam_target_count", on_change=sync_target_count)
        inherit = st.checkbox("沿用左侧当前筛选", value=True, key="smart_exam_inherit")
        filters = inherited_filters(st.session_state) if inherit else QuestionListFilters()
        active = {k: v for k, v in asdict(filters).items() if k not in {"offset", "limit"} and v not in ("", None)}
        labels = {"keyword":"关键词", "year":"年份", "chapter":"板块", "source_kind":"来源类型",
                  "paper_series":"卷别", "source":"试卷来源", "question_number":"题号",
                  "question_type_id":"题型编号", "difficulty":"难度"}
        if active:
            st.caption("当前筛选：" + "；".join(f"{labels.get(k,k)}：{v}" for k, v in active.items()))
        if current_refs:
            operation = st.radio("已有选题", ["补足当前试题篮", "重新生成整套"],
                format_func=lambda value: "保留手选并补足" if value == "补足当前试题篮" else "重新生成整套",
                key="smart_exam_operation", horizontal=True)
            replace_confirmed = operation != "重新生成整套" or st.checkbox(
                f"确认替换当前 {len(current_refs)} 道手选题", key="smart_exam_confirm_replace")
        else:
            operation, replace_confirmed = "补足当前试题篮", True
        quotas_on = st.checkbox("指定题型数量", value=paper, key="smart_exam_use_quotas",
            help="可分别设置单选、多选、填空和解答题数量；不勾选时使用页面上方的总题量。")
        quotas = None
        if quotas_on:
            quotas = {}
            defaults = {"single_choice": 8, "multiple_choice": 3, "fill_blank": 3, "solution": 5, "other": 0} if paper else {
                "single_choice": int(target_count), "multiple_choice": 0, "fill_blank": 0, "solution": 0, "other": 0}
            for code, col in zip(TYPE_LABELS, st.columns(5)):
                with col:
                    quotas[code] = int(st.number_input(TYPE_LABELS[code], 0, 200, defaults[code], key="smart_exam_quota_" + code))
            requested = sum(quotas.values())
            st.caption(f"本次目标 {requested} 题，以以上题型配额为准。")
        else:
            requested = int(target_count)
        with st.expander("补充选题想法（选填）"):
            intent = st.text_area("组卷意图（用于排序）", key="smart_exam_intent",
                placeholder="例如：侧重函数与导数，适合作为巩固练习。", height=80, label_visibility="collapsed")
            st.caption("文字帮助排序；题型数量、年份等必须满足的条件，请通过筛选项设置。")
            if st.button("AI 润色想法", key="smart_exam_polish"):
                if intent.strip():
                    result = polish_intent(intent)
                    if result.startswith("❌"):
                        st.error(result)
                    else:
                        st.session_state["smart_exam_polished"] = result
                else:
                    st.info("请先填写选题想法。")
            if st.session_state.get("smart_exam_polished"):
                st.write(st.session_state["smart_exam_polished"])
                def adopt():
                    st.session_state["smart_exam_intent"] = st.session_state["smart_exam_polished"]
                st.button("采用润色建议", key="smart_exam_adopt", on_click=adopt)
        with st.expander("高级设置", expanded=preset == "自定义范围"):
            unknown = st.checkbox("包含未标注难度的题目", value=True, key="smart_exam_unknown",
                help="未标注的题目保持未知，不会被当成低难度题。")
            col_match, col_unknown_limit = st.columns(2)
            with col_match:
                primary = st.selectbox("板块匹配口径", ["全部关联板块", "仅主板块"], key="smart_exam_basis") == "仅主板块"
            with col_unknown_limit:
                unknown_limit = st.number_input("未标注难度题的数量上限", 0, 200, min(int(target_count), 200),
                    key="smart_exam_unknown_limit") if unknown else 0
                if not unknown:
                    st.caption("本次已排除未标注难度的题目。")
            col_range, col_goal = st.columns(2)
            with col_range:
                difficulty = st.slider("已标注难度范围", 0, 6, (0, 6), key="smart_exam_range",
                    on_change=use_custom_range)
            with col_goal:
                target_difficulty = st.number_input("优先接近的星级", 0.0, 6.0, 3.0, .5, key="smart_exam_difficulty")
                st.caption("用于排序，不作为整卷平均难度保证。")
            col_budget, col_seed = st.columns(2)
            with col_budget:
                limit = st.selectbox("候选题数量", [200, 500, 1000, "全部"], index=1, key="smart_exam_limit")
            with col_seed:
                seed = st.number_input("抽题编号", 0, 999999, 42, key="smart_exam_seed",
                    help="相同条件与编号可复现选题；生成候选池后也可点击“换一批候选”。")
        options = CandidateOptions(tuple(expand_selected_subjects(subjects)), primary, difficulty[0],
            difficulty[1], unknown, float(target_difficulty), intent, int(seed))
        signature = hashlib.sha256(json.dumps([asdict(filters), asdict(options), quotas, requested, limit, int(unknown_limit)],
            ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        refresh_requested = st.session_state.pop("smart_exam_refresh", False)
        generate_requested = st.session_state.pop("smart_exam_generate_requested", False)
        if generate_requested or refresh_requested:
            try:
                if not 1 <= requested <= 200:
                    raise ValueError("本次目标题量须为 1—200。")
                with st.spinner("正在按条件检索全库并检查同题关系…"):
                    pool = build_candidate_pool(db, filters=filters, options=options,
                        limit=0 if limit == "全部" else int(limit), quotas=quotas,
                        pinned_ids=[ref_question_id(r) for r in current_refs if ref_question_id(r)])
                st.session_state["smart_exam_pool"] = {"signature": signature, "pool": pool}
                st.session_state.pop("smart_exam_plan", None)
                st.session_state.pop("smart_exam_excluded", None)
                st.session_state.pop("smart_exam_preview", None)
            except (ValueError, OSError) as exc:
                st.error(str(exc))
        def paint_progress():
            existing_pool = st.session_state.get("smart_exam_pool")
            pool_current = bool(existing_pool and existing_pool["signature"] == signature)
            existing_plan = st.session_state.get("smart_exam_plan")
            plan_current = bool(existing_plan and existing_plan["signature"] == signature and
                existing_plan["refs"] == current_refs and existing_plan["operation"] == operation and
                existing_plan["excluded"] == list(st.session_state.get("smart_exam_excluded", [])))
            stage = 3 if plan_current else 2 if pool_current else 1
            steps = []
            for index, title in enumerate(("设置条件", "候选池", "初选确认"), 1):
                if steps:
                    steps.append('<span aria-hidden="true">›</span>')
                steps.append(f'<span class="{"current" if index == stage else "complete" if index < stage else ""}">{title}</span>')
            header.markdown(
                '<div class="mc-smart-exam-header"><div><h3>组卷条件</h3><div class="mc-smart-exam-progress">'
                + ''.join(steps) + '</div></div>'
                + f'<div class="mc-smart-exam-target"><strong>{requested}</strong>题'
                + f'<small>已手选 {len(current_refs)} 题</small></div></div>', unsafe_allow_html=True)
            return pool_current, plan_current

        pool_current, plan_current = paint_progress()
        summary = ("沿用当前筛选" if active else "全库") + " · " + (
            "、".join(subjects[:3]) + ("等" if len(subjects) > 3 else "") if subjects else "全部板块")
        summary += f" · {'难度不限' if difficulty == (0, 6) else str(difficulty[0])+'—'+str(difficulty[1])+'星'}"
        if unknown:
            summary += " · 包含未标注难度" if unknown_limit else " · 不使用未标注难度"
        col_summary, col_generate = st.columns([2.2, 1], gap="medium")
        with col_summary:
            st.markdown(f'<div class="mc-smart-exam-summary">{escape(summary)}</div>', unsafe_allow_html=True)
        with col_generate:
            st.button("生成候选池", type="secondary" if pool_current else "primary",
                key="smart_exam_candidates", use_container_width=True, on_click=request_candidates)
        stored = st.session_state.get("smart_exam_pool")
        if not stored:
            return
        if stored["signature"] != signature:
            st.info("条件已变化，请重新生成候选池。")
            return
        pool = stored["pool"]
        st.markdown(
            '<div class="mc-smart-exam-result"><h3>候选池</h3>'
            + f"<p>全库匹配 {pool['matched_count']:,} 题 · 同题去重后 {pool['distinct_count']:,} 题 · 本池 {len(pool['rows']):,} 题</p></div>",
            unsafe_allow_html=True)
        st.caption("全库匹配题型：" + "；".join(f"{TYPE_LABELS[k]} {v}" for k, v in pool["type_counts"].items()) +
                   f"。其中难度未知 {pool['unknown_count']:,} 题。")
        st.caption("先查看题目，再生成初选。需要其他候选时，可以换一批。")
        st.button("换一批候选", key="smart_exam_reshuffle", on_click=reshuffle)
        rows_by_id = {r["question_id"]: r for r in pool["rows"]}
        def label(qid):
            row = rows_by_id[qid]
            return f"{qid} · {row.get('year') or ''} {row.get('source') or ''} 第{row.get('paper_number') or ''}题"
        with st.expander("查看候选题与入选依据"):
            excluded = st.multiselect("排除不想使用的题目", list(rows_by_id), format_func=label,
                placeholder="选择要排除的题目", key="smart_exam_excluded")
            st.dataframe([{"题目ID": r["question_id"], "题型": TYPE_LABELS[r["type_code"]],
                "板块": "、".join(r["knowledge"]), "难度": str(r["difficulty"]) if r["difficulty"] is not None else "未知",
                "来源": f"{r.get('year') or ''} {r.get('source') or ''}", "依据": r["reason"]} for r in pool["rows"]],
                use_container_width=True, hide_index=True, height=260)
            if rows_by_id:
                preview_id = st.selectbox("预览候选题", ["__none__"] + list(rows_by_id),
                    format_func=lambda qid: "选择题目后显示预览" if qid == "__none__" else label(qid),
                    key="smart_exam_preview")
                if preview_id != "__none__":
                    preview_question(preview_id)
        if st.session_state.pop("smart_exam_plan_requested", False):
            try:
                kept = current_refs if operation == "补足当前试题篮" else []
                if any(not ref_question_id(r) for r in kept):
                    raise ValueError("试题篮含无法映射到正式题ID的旧文件题，请先核对该题，或明确选择重新生成整套。")
                pinned = load_exam_rows(db, question_ids=[ref_question_id(r) for r in kept])
                if len(pinned) != len(kept):
                    raise ValueError("部分手选题已不在正式库中，请先检查试题篮。")
                by_id = {r["question_id"]: r for r in pinned}
                pinned = [by_id[ref_question_id(ref)] for ref in kept]
                result = plan_selection(pool, target_count=requested, pinned_rows=pinned, quotas=quotas,
                    excluded_ids=excluded, unknown_limit=int(unknown_limit))
                st.session_state["smart_exam_plan"] = {"result": result, "refs": current_refs,
                    "excluded": list(excluded), "operation": operation, "signature": signature}
            except ValueError as exc:
                st.error(str(exc))
        pool_current, plan_current = paint_progress()
        col_pool_summary, col_plan_action = st.columns([2.2, 1], gap="medium")
        with col_pool_summary:
            st.caption(f"已排除 {len(excluded)} 题 · 本次目标 {requested} 题")
        col_plan_action.button("生成初选方案", key="smart_exam_plan_button",
            type="secondary" if plan_current else "primary", on_click=request_plan,
            use_container_width=True)
        plan = st.session_state.get("smart_exam_plan")
        if not plan:
            return
        if (plan["refs"] != current_refs or plan["excluded"] != list(excluded) or
                plan["operation"] != operation or plan["signature"] != signature):
            st.info("试题篮、排除项或条件已变化，请重新生成初选方案。")
            return
        result = plan["result"]
        st.markdown('<div class="mc-smart-exam-result"><h3>初选确认</h3><p>核对题型与提醒，确认后再写入试题篮。</p></div>', unsafe_allow_html=True)
        for error in result["errors"]:
            st.error(error)
        for shortage in result["shortages"]:
            st.warning(f"{shortage['type']}还缺 {shortage['missing']} 道。请扩大范围、增加候选池规模或明确调整限制后重新生成。")
        for warning in result["warnings"]:
            st.warning(warning)
        st.write(f"初选 {len(result['rows'])} / {requested} 题 · 保留手选 {result['kept_count']} 题 · 难度未知 {result['unknown_count']} 题")
        st.caption("题型：" + "；".join(f"{TYPE_LABELS[k]} {v}" for k, v in Counter(r["type_code"] for r in result["rows"]).items()))
        if paper:
            st.caption("手选题顺序继续保留；分节位置、章节文字及分值请在排版台核对。")
        with st.expander("查看初选题目"):
            st.dataframe([{"题目ID": row["question_id"], "题型": TYPE_LABELS[row["type_code"]],
                "板块": "、".join(row["knowledge"]), "依据": row.get("reason") or "手选题（保留）"}
                for row in result["rows"]], use_container_width=True, hide_index=True, height=220)
        if result["warnings"]:
            acknowledgement = hashlib.sha256(json.dumps([result["warnings"], [r["question_id"] for r in result["rows"]]],ensure_ascii=False).encode()).hexdigest()[:12]
            accepted = st.checkbox("已核对上述范围或相似关系提醒", key="smart_exam_acknowledge_"+acknowledgement)
        else:
            accepted = True
        col_apply_summary, col_apply_action = st.columns([2.2, 1], gap="medium")
        with col_apply_summary:
            if operation == "补足当前试题篮":
                st.caption(f"保留手选 {result['kept_count']} 题，补入 {max(0, len(result['rows']) - result['kept_count'])} 题。")
            else:
                st.caption(f"确认后将用这 {len(result['rows'])} 题替换当前试题篮。")
        if col_apply_action.button("确认放入试题篮", type="primary", key="smart_exam_apply",
                     disabled=not (result["ready"] and replace_confirmed and accepted),
                     use_container_width=True):
            try:
                ensure_plan_current(db, result["rows"])
                refs = [question_ref(r["question_id"]) for r in result["rows"]]
                st.session_state["exam_selected_qs"] = refs
                st.session_state["exam_expanded_q"] = refs[0]
                st.session_state["exam_basket_open"] = True
                st.session_state["exam_q_count_input"] = len(refs)
                st.session_state["exam_pending_count"] = len(refs)
                sync_blocks(refs)
                st.session_state.pop("smart_exam_plan", None)
                st.rerun()
            except ValueError as exc:
                st.error(str(exc))
