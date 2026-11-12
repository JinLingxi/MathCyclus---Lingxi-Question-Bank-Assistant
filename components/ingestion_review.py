"""Year / paper / full-paper review, scoped to Codex tasks."""

import json
import html
import os
import re
import streamlit as st
import streamlit.components.v1 as components

from services.ingestion_review_service import task_tree, paper_drafts, descendants, metadata
from services.question_text_format_service import question_display_note
from services.import_service import (
    get_draft_question, update_draft_question_fields, approve_draft_for_commit,
    update_draft_review_status,
    commit_draft_to_question,
    find_paper_position_conflict, find_question_content_matches, validate_draft_question,
    normalize_draft_question,
)

STATUS = {'needs_review': '待审核', 'ready': '待确认', 'blocked': '需修正',
          'approved': '已批准', 'committed': '已入库', 'rejected': '已退回'}


REVIEW_STYLE = '''<style>
.mc-review-heading {display:flex;align-items:center;justify-content:space-between;gap:12px;margin:0 0 12px;}
.mc-review-heading strong {font-size:1.12rem;color:#282035;}
.mc-review-status {font-size:.8rem;color:#5c526c;background:#f1edf8;padding:4px 9px;border-radius:6px;}
.mc-review-meta {display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:8px 0 16px;line-height:1.55;}
.mc-review-meta-label {font-size:.78rem;color:#5c526c;margin-right:2px;}
.mc-review-chip {display:inline-block;font-size:.84rem;font-weight:600;padding:4px 9px;border-radius:6px;overflow-wrap:anywhere;}
.mc-review-topic {color:#4c2785;background:#e9dff8;}
.mc-review-tag {color:#20516a;background:#e2eff4;}
.mc-review-notice {padding:10px 12px;margin:8px 0;border-radius:8px;font-size:.87rem;line-height:1.65;border:1px solid;}
.mc-review-notice.position {color:#7b4314;background:#fff5e9;border-color:#e7c49b;}
.mc-review-notice.exact {color:#7f1d1d;background:#fff0f0;border-color:#f3b4b4;}
.mc-review-notice.similar {color:#744210;background:#fff8df;border-color:#f0cf83;}
.mc-review-notice.clear {color:#41615a;background:#f2faf6;border-color:#b9dfc9;}
.mc-review-notice a {color:inherit !important;font-weight:700;text-decoration:underline;text-underline-offset:3px;margin-right:8px;}
.mc-review-notice a:focus-visible {outline:2px solid currentColor;outline-offset:3px;}
.mc-review-notice small {display:inline;opacity:1;margin-left:.35rem;}
.mc-review-notice-line {display:flex;flex-wrap:wrap;align-items:baseline;gap:3px 8px;line-height:1.55;}
.mc-review-notice-line strong {white-space:nowrap;}
.mc-review-notice-line small {color:inherit;}
div[data-testid="stExpander"]:has(.mc-review-edit-anchor) {border:1px solid var(--mc-border,#ddd5e9) !important;border-radius:8px !important;background:#fff !important;box-shadow:none !important;}
div[data-testid="stExpander"]:has(.mc-review-edit-anchor) [data-testid="stExpanderDetails"] {padding:12px !important;}
div[data-testid="stExpander"]:has(.mc-review-edit-anchor) [data-testid="stForm"] {padding:10px !important;border:1px solid var(--mc-border,#ddd5e9) !important;border-radius:8px !important;}
.mc-review-image-frame {width:100%;max-width:100%;margin:10px 0;padding:8px;box-sizing:border-box;border:1px solid rgba(148,163,184,.25);border-radius:10px;background:#f8fafc;text-align:center;}
.mc-review-image-frame a {display:block;max-width:100%;cursor:zoom-in;}
.mc-review-image-frame img {display:block;width:auto;max-width:100%;max-height:360px;height:auto;margin:0 auto;object-fit:contain;border-radius:6px;background:#fff;}
.mc-review-image-frame figcaption {margin-top:5px;color:#64748b;font-size:.76rem;line-height:1.3;}
.mc-review-choice-label {margin:8px 0 3px;font-size:.85rem;font-weight:600;color:#51465f;}
.mc-review-question-trigger {color:#282035 !important;text-decoration:underline;text-decoration-color:rgba(109,40,217,.35);text-underline-offset:4px;cursor:pointer;}
.mc-review-question-trigger:hover {color:#6d28d9 !important;}
.mc-review-duplicate-float {display:block;position:relative;width:auto;max-width:100%;max-height:none;z-index:1;overflow:visible;margin:8px 0 12px;padding:10px 12px;border:1px solid rgba(148,163,184,.35);border-radius:10px;background:#fbfaff;box-sizing:border-box;}
.mc-review-duplicate-float.mc-review-duplicate-open {display:block;}
.mc-review-duplicate-header {display:flex;align-items:center;justify-content:space-between;gap:10px;margin:-2px 0 10px;cursor:move;user-select:none;font-weight:700;color:#282035;}
.mc-review-duplicate-close {width:30px;height:30px;padding:0;border:1px solid rgba(148,163,184,.35);border-radius:8px;background:rgba(248,250,252,.9);color:#475569;cursor:pointer;font-size:18px;line-height:26px;}
div[data-testid="stVerticalBlock"]:has(> :is([data-testid="element-container"],[data-testid="stElementContainer"]) .mc-review-actions-anchor) {display:grid !important;grid-template-columns:repeat(2,minmax(0,1fr)) !important;gap:10px !important;}
div[data-testid="stVerticalBlock"]:has(> :is([data-testid="element-container"],[data-testid="stElementContainer"]) .mc-review-actions-anchor) > div {width:100% !important;min-width:0 !important;}
div[data-testid="stVerticalBlock"]:has(> :is([data-testid="element-container"],[data-testid="stElementContainer"]) .mc-review-actions-anchor) :is([data-testid="stButton"],button) {width:100% !important;max-width:100% !important;box-sizing:border-box;}
:is([data-testid="element-container"],[data-testid="stElementContainer"]):has(.mc-review-approve-anchor) + div button {color:#166534 !important;background:#f0fdf4 !important;border-color:#bbf7d0 !important;min-height:44px;white-space:normal;}
:is([data-testid="element-container"],[data-testid="stElementContainer"]):has(.mc-review-reject-anchor) + div button {color:#991b1b !important;background:#fff1f2 !important;border-color:#fecdd3 !important;min-height:44px;white-space:normal;}
:is([data-testid="element-container"],[data-testid="stElementContainer"]):has(.mc-review-actions-anchor,.mc-review-approve-anchor,.mc-review-reject-anchor) {display:none;}
div[data-testid="stVerticalBlock"]:has(>div[data-testid="stElementContainer"] .mc-review-heading) {
    padding:16px;background:var(--mc-surface,#fff);border:1px solid var(--mc-border,#ddd5e9);border-radius:10px;
}
div[data-testid="stVerticalBlock"]:has(>div[data-testid="stElementContainer"] .mc-review-heading) img {max-width:100%;height:auto;}
@media (max-width:1200px) {
    div[data-testid="stHorizontalBlock"]:has(>div[data-testid="column"] .mc-review-heading),
    div[data-testid="stHorizontalBlock"]:has(>div[data-testid="stColumn"] .mc-review-heading) {flex-wrap:wrap !important;}
    div[data-testid="stHorizontalBlock"]:has(.mc-review-heading) > div[data-testid="column"],
    div[data-testid="stHorizontalBlock"]:has(.mc-review-heading) > div[data-testid="stColumn"] {width:100% !important;flex:1 1 100% !important;min-width:0 !important;}
}
</style>'''


def _db_token(db_path):
    return tuple((os.stat(p).st_mtime_ns, os.stat(p).st_size) if os.path.exists(p) else (0, 0)
                 for p in (str(db_path), str(db_path) + '-wal'))


@st.cache_data(show_spinner=False, max_entries=256)
def _matches(db_path, token, stem, choices, kind, extra_json):
    return (
        find_paper_position_conflict(db_path, metadata(extra_json)),
        find_question_content_matches(db_path, stem, choices=list(choices), question_type_id=kind, max_results=3),
    )


def _metadata_badges(extra, draft):
    topics = [s.strip() for s in re.split('[，,]', extra.get('detected_topic') or '') if s.strip()]
    tags = json.loads(draft.get('tags_json') or '[]')
    parts = ['<div class="mc-review-meta"><span class="mc-review-meta-label">板块</span>']
    parts.extend(f'<span class="mc-review-chip mc-review-topic">{html.escape(str(t))}</span>' for t in topics or ['待标注'])
    parts.append('<span class="mc-review-meta-label">标签</span>')
    parts.extend(f'<span class="mc-review-chip mc-review-tag">{html.escape(str(t))}</span>' for t in tags or ['待标注'])
    parts.append('</div>')
    st.markdown(''.join(parts), unsafe_allow_html=True)


def _match_notices(conflicts, matches, draft_id):
    preview_ids = set()
    notices = []
    for tone, title, hint, candidates in [
        ('position', '同卷题号已有题目', '来源位置重复，请先对照已有题目。', conflicts),
        ('exact', '题干完全相同', '内容提示，不代表来源位置重复。', [m for m in matches if m.get('kind') == 'exact']),
        ('similar', '题干高度相似', '请对照条件、选项与图片，人工判断是否同题。', [m for m in matches if m.get('kind') == 'similar']),
    ]:
        if not candidates:
            continue
        links = []
        for candidate in candidates:
            qid = str(candidate.get('question_id') or '')
            if not qid:
                continue
            preview_ids.add(qid)
            label = qid
            if tone != 'position':
                label += f" · {float(candidate.get('score') or 0):.0%}"
            links.append(f'<a href="#duplicate-preview-{html.escape(qid, quote=True)}" data-duplicate-preview-id="{html.escape(qid, quote=True)}" aria-label="查看已有题目 {html.escape(qid, quote=True)}">{html.escape(label)}</a>')
            if tone == 'similar':
                detail = _similarity_difference_hint(candidate)
                if detail:
                    links.append(f'<small class="mc-review-difference">{html.escape(detail)}</small>')
        notices.append(
            f'<div class="mc-review-notice {tone}"><div class="mc-review-notice-line">'
            f'<strong>{title}</strong><span>{" ".join(links)}</span>'
            f'<small>（{hint}）</small></div></div>'
        )
    if notices:
        # Keep candidate IDs in the card as compact links. The actual question
        # content is rendered once, outside the grid, in the floating preview
        # panel created by render_duplicate_preview().
        st.markdown(''.join(notices), unsafe_allow_html=True)
    else:
        st.markdown(
            '<div class="mc-review-notice clear"><strong>重复/相似题检查</strong>'
            '<small>未发现来源位置冲突、题干完全相同或高度相似候选。</small></div>',
            unsafe_allow_html=True,
        )
    return preview_ids, bool(notices)


def _similarity_difference_hint(candidate):
    """Return conservative, machine-observed differences for the existing review link."""
    labels = {'numbers': '数字', 'variables': '变量', 'relations': '关系符号',
              'conditions': '条件词', 'visual_pending': '配图需查看',
              'choices': '选项', 'image_count': '配图数', 'intervals': '区间端点或开闭边界有差异'}
    parts = []
    for change in candidate.get('differences') or []:
        if not isinstance(change, dict):
            continue
        label = labels.get(change.get('kind'))
        if label:
            if change.get('kind') == 'numbers':
                left = ','.join(str(v) for v in change.get('left') or [])
                right = ','.join(str(v) for v in change.get('right') or [])
                parts.append(f'数字 {left or "无"}→{right or "无"}')
            elif change.get('kind') == 'relations':
                left = ','.join(str(v) for v in change.get('left') or [])
                right = ','.join(str(v) for v in change.get('right') or [])
                parts.append(f'关系符号 {left or "无"}→{right or "无"}')
            elif change.get('kind') == 'conditions':
                left = ','.join(str(v) for v in change.get('left') or [])
                right = ','.join(str(v) for v in change.get('right') or [])
                parts.append(f'条件词 {left or "无"}→{right or "无"}')
            elif change.get('kind') == 'choices':
                positions = '、'.join(str(v) for v in change.get('positions') or [])
                parts.append(f'选项{positions}有差异' if positions else '选项有差异')
            elif change.get('kind') == 'image_count':
                parts.append(f'配图数 {change.get("left")}→{change.get("right")}')
            else:
                parts.append(label)
    has_choice_detail = any(change.get('kind') == 'choices'
                            for change in candidate.get('differences') or []
                            if isinstance(change, dict))
    if not has_choice_detail and any('选项' in str(warning) for warning in candidate.get('warnings') or []):
        parts.append('选项需核对')
    if not parts:
        for reason in candidate.get('reasons') or []:
            text = str(reason)
            for key, label in labels.items():
                if ((key == 'numbers' and '数字' in text)
                        or (key == 'variables' and '变量符号' in text)
                        or (key == 'relations' and '关系符号' in text)
                        or (key == 'conditions' and '条件词' in text)):
                    parts.append(label)
            if '配图' in text:
                parts.append('配图需查看')
    parts = list(dict.fromkeys(parts))
    return '差异提示：' + '、'.join(parts) if parts else ''


def _render_question(db_path, draft, number, render_preview, token):
    extra = metadata(draft.get('extra_json'))
    draft_id = draft['draft_id']
    st.markdown(f'<div class="mc-review-heading"><strong>第 {html.escape(str(number))} 题</strong>'
                f'<span class="mc-review-status">{html.escape(STATUS.get(draft["review_status"], draft["review_status"]))}</span></div>', unsafe_allow_html=True)
    _metadata_badges(extra, draft)
    render_preview(draft)
    conflicts, matches = _matches(db_path, token, draft.get('stem_tex') or '',
                                  tuple(json.loads(draft.get('choices_json') or '[]')),
                                  draft.get('question_type_id'), draft.get('extra_json') or '{}')
    # Old ingestion summaries contain snapshots of the same duplicate notices.
    # Show the live result above; preserve unrelated manual review notes here.
    reason = draft.get('review_reason') or ''
    if reason and not any(t in reason for t in ('同卷题号已有题目', '已有相似题候选')):
        st.caption(reason)
    note = question_display_note(draft.get('note'))
    if note:
        st.caption(note)
    preview_ids, _ = _match_notices(conflicts, matches, draft_id)
    with st.expander('编辑题干、答案和解析'):
        st.markdown('<span class="mc-review-edit-anchor"></span>', unsafe_allow_html=True)
        with st.form(f'ingestion_edit_{draft_id}'):
            stem = st.text_area('题干', draft.get('stem_tex') or '')
            original_choices = json.loads(draft.get('choices_json') or '[]')
            if not isinstance(original_choices, list):
                original_choices = []
            is_choice = draft.get('question_type_id') in {1, 2} or bool(original_choices)
            edited_choices = []
            if is_choice:
                st.markdown('<div class="mc-review-choice-label">选项 TeX</div>', unsafe_allow_html=True)
                for index in range(max(4, len(original_choices))):
                    edited_choices.append(st.text_area(
                        f'选项 {chr(65 + index)}',
                        original_choices[index] if index < len(original_choices) else '',
                        key=f'ingestion_edit_choice_{draft_id}_{index}', height=72,
                    ))
            answer = st.text_area('答案', draft.get('answer_tex') or '')
            solution = st.text_area('解析', draft.get('solution_tex') or '')
            save = st.form_submit_button('保存修改', disabled=draft['review_status'] == 'committed')
        if save:
            try:
                updates = {'stem_tex': stem, 'answer_tex': answer, 'solution_tex': solution}
                if is_choice:
                    choices = [choice.strip() for choice in edited_choices]
                    while choices and not choices[-1]:
                        choices.pop()
                    if len(choices) < 2 or any(not choice for choice in choices):
                        raise ValueError('选择题至少保留两个选项，中间选项不能为空。')
                    updates['choices'] = choices
                update_draft_question_fields(db_path, draft_id, updates)
                st.rerun()
            except (ValueError, KeyError) as exc:
                st.error(str(exc))
    with st.container():
        st.markdown('<span class="mc-review-actions-anchor"></span>', unsafe_allow_html=True)
        st.markdown('<span class="mc-review-approve-anchor"></span>', unsafe_allow_html=True)
        approved = st.button('✅ 确认本题审核通过', key=f'ingestion_approve_{draft_id}', use_container_width=True,
                     disabled=draft['review_status'] in {'approved', 'committed', 'rejected'})
        if approved:
            try:
                approve_draft_for_commit(db_path, draft_id, operator='human_task_review')
                st.rerun()
            except (ValueError, KeyError) as exc:
                st.error(str(exc))
        st.markdown('<span class="mc-review-reject-anchor"></span>', unsafe_allow_html=True)
        rejected = st.button('❌ 本题放弃录入', key=f'ingestion_reject_{draft_id}', use_container_width=True,
                     disabled=draft['review_status'] in {'committed', 'rejected'})
        if rejected:
            try:
                update_draft_review_status(db_path, draft_id, 'rejected', '人工审核放弃录入')
                st.rerun()
            except (ValueError, KeyError) as exc:
                st.error(str(exc))
    return preview_ids


def _run_bulk_review_action(db_path, rows, mode):
    if mode not in {'all', 'non_duplicate', 'non_exact'}:
        raise ValueError('不支持的批量录入方式')
    committed = 0
    skipped = 0
    errors = []
    for row in rows:
        draft = get_draft_question(db_path, row['draft_id'])
        if draft.get('review_status') in {'committed', 'rejected'}:
            skipped += 1
            continue
        extra = metadata(draft.get('extra_json'))
        conflicts = find_paper_position_conflict(db_path, extra)
        matches = find_question_content_matches(
            db_path, draft.get('stem_tex') or '',
            choices=json.loads(draft.get('choices_json') or '[]'),
            question_type_id=draft.get('question_type_id'), max_results=3,
        )
        kinds = {str(match.get('kind') or '') for match in matches}
        if conflicts or (mode == 'non_duplicate' and 'exact' in kinds) or (
                mode == 'non_exact' and kinds.intersection({'exact', 'similar'})):
            skipped += 1
            continue
        validation = validate_draft_question(normalize_draft_question(draft))
        if validation.get('errors') or validation.get('warnings'):
            skipped += 1
            errors.append(f"{draft.get('source_label') or row['draft_id']}：仍有校验提醒")
            continue
        try:
            approve_draft_for_commit(db_path, row['draft_id'], operator='human_task_review', note='批量录入确认')
            commit_draft_to_question(db_path, row['draft_id'], operator='human_task_review')
            committed += 1
        except (ValueError, KeyError) as exc:
            skipped += 1
            errors.append(f"{draft.get('source_label') or row['draft_id']}：{exc}")
    if committed:
        st.success(f'已入库 {committed} 道；跳过 {skipped} 道。')
    else:
        st.info(f'没有可直接入库的题目；跳过 {skipped} 道。请先逐题处理审核提醒。')
    if errors:
        st.caption('；'.join(errors[:5]))
def render(db_path, render_preview, render_duplicate_preview):
    st.markdown(REVIEW_STYLE, unsafe_allow_html=True)
    components.html(
        """
        <script>
        (() => {
          const doc = window.parent.document;
          const clamp = (v, min, max) => Math.max(min, Math.min(max, v));
          function bind() {
            doc.querySelectorAll('.mc-review-question-trigger').forEach((trigger) => {
              if (trigger.dataset.bound === '1') return;
              trigger.dataset.bound = '1';
              const panel = doc.getElementById(trigger.dataset.reviewDuplicatePanel);
              if (!panel) return;
              const header = panel.querySelector('.mc-review-duplicate-header');
              const close = panel.querySelector('.mc-review-duplicate-close');
              trigger.addEventListener('click', (event) => {
                event.preventDefault(); event.stopPropagation();
                panel.classList.add('mc-review-duplicate-open');
              });
              if (close) close.addEventListener('click', (event) => {
                event.preventDefault(); event.stopPropagation(); panel.classList.remove('mc-review-duplicate-open');
              });
              if (header && panel.dataset.dragBound !== '1') {
                panel.dataset.dragBound = '1';
                let moving = false, ox = 0, oy = 0;
                header.addEventListener('pointerdown', (event) => {
                  const rect = panel.getBoundingClientRect(); moving = true;
                  ox = event.clientX - rect.left; oy = event.clientY - rect.top;
                  header.setPointerCapture(event.pointerId); event.preventDefault();
                });
                header.addEventListener('pointermove', (event) => {
                  if (!moving) return;
                  const rect = panel.getBoundingClientRect();
                  const x = clamp(event.clientX - ox, 12, window.parent.innerWidth - rect.width - 12);
                  const y = clamp(event.clientY - oy, 12, window.parent.innerHeight - rect.height - 12);
                  panel.style.setProperty('left', `${x}px`, 'important');
                  panel.style.setProperty('top', `${y}px`, 'important');
                  panel.style.setProperty('right', 'auto', 'important');
                });
                header.addEventListener('pointerup', () => { moving = false; });
                header.addEventListener('pointercancel', () => { moving = false; });
              }
            });
          }
          bind(); window.parent.setTimeout(bind, 80); window.parent.setTimeout(bind, 300);
          const key = '__mcReviewDuplicateObserver';
          if (window.parent[key]) window.parent[key].disconnect();
          window.parent[key] = new window.parent.MutationObserver(bind);
          window.parent[key].observe(doc.body, {childList:true, subtree:true});
        })();
        </script>
        """,
        height=0,
    )
    st.subheader('录题任务审核')
    nodes, roots = task_tree(db_path)
    if not roots:
        st.info('尚未建立录题任务。任务建立后，这里会显示年份、试卷和实际处理进度。')
        return
    root_ids = [r['batch_id'] for r in roots]
    by_id = {r['batch_id']: r for r in nodes}
    key = 'ingestion_review_task'
    if st.session_state.get(key) not in root_ids:
        st.session_state[key] = root_ids[0]
    if len(roots) > 1:
        st.selectbox('', root_ids, format_func=lambda i: by_id[i]['label'], key=key, label_visibility='collapsed')
    root = by_id[st.session_state[key]]
    is_book = root['metadata'].get('source_kind') == '教材'
    group_label = '章节' if is_book else '年份'
    item_label = '小节' if is_book else '试卷'
    unit_label = '个小节' if is_book else '套试卷'
    subtree = descendants(nodes, root['batch_id'])
    papers = [n for n in nodes if n['batch_id'] in subtree and n.get('hierarchy_level') == 1]
    if not papers:
        st.info('此任务尚未完成来源盘点，试卷目录待建立。')
        return
    for paper in papers:
        year = paper['metadata'].get('chapter_name') if is_book else paper['metadata'].get('year')
        if not year:
            match = re.search(r'(?:19|20)\d{2}', paper.get('subset_key', '') + root['label'])
            year = match.group() if match else '年份待确认'
        paper['year'] = str(year)
    years = sorted({p['year'] for p in papers}, reverse=True)
    if is_book:
        years.sort(key=lambda y: min(p['metadata'].get('page_start', 999999) for p in papers if p['year'] == y))
    year_key = 'ingestion_review_year'
    if st.session_state.get(year_key) not in years:
        st.session_state[year_key] = years[0]
    left, middle, right = st.columns([0.45, 0.8, 4.75], gap='medium')
    with left:
        st.markdown(f'#### {group_label}')
        year = st.radio(group_label, years, key=year_key, label_visibility='collapsed')
        st.caption(f"共 {len(papers)} {unit_label} · {root['draft_count']} 道草稿")
    with middle:
        st.markdown(f'#### {item_label}')
        choices = sorted([p for p in papers if p['year'] == year],
                         key=lambda p: (p['metadata'].get('page_start', 999999), p['label']))
        ids = [p['batch_id'] for p in choices]
        paper_key = 'ingestion_review_paper'
        if st.session_state.get(paper_key) not in ids:
            st.session_state[paper_key] = ids[0]
        def label(i):
            p = by_id[i]
            progress = f"{p['draft_count']} 道草稿" if p['draft_count'] else '待转写'
            return f"{p['label']} · {progress}"
        paper_id = st.radio(item_label, ids, format_func=label, key=paper_key, label_visibility='collapsed')
    with right:
        current_scope = '当前章' if is_book else '当前年份'
        batch_scope = st.radio('批次范围', [current_scope, '整个任务'], horizontal=True,
                               key=f'ingestion_bulk_scope_{root["batch_id"]}')
        year_papers = sorted(
            [paper for paper in papers if batch_scope == '整个任务' or paper['year'] == year],
            key=lambda paper: (paper['metadata'].get('page_start', 999999), paper['label']),
        )
        scope_count = sum(paper['draft_count'] for paper in year_papers)
        scope_title = (year if is_book else f'{year} 年') if batch_scope == current_scope else root['label']
        st.markdown(f'#### {scope_title} · 批次操作')
        st.caption(f'本批范围：{len(year_papers)} {unit_label}，共 {scope_count} 道草稿。以下三个按钮处理本批范围。')
        batch_cols = st.columns(3, gap='small')
        batch_action = ''
        for col, label, mode in zip(
            batch_cols,
            ['录入本批所有未处理题目', '录入本批非重复题目', '录入本批非重复与相似题目'],
            ['all', 'non_duplicate', 'non_exact'],
        ):
            with col:
                if st.button(label, key=f'ingestion_bulk_year_{mode}_{root["batch_id"]}_{year}_{batch_scope}',
                              disabled=not scope_count, use_container_width=True, type='primary' if mode == 'all' else 'secondary'):
                    batch_action = mode
        if batch_action:
            year_rows = [row for paper in year_papers for row in paper_drafts(db_path, nodes, paper['batch_id'])]
            _run_bulk_review_action(db_path, year_rows, batch_action)
        paper = by_id[paper_id]
        st.markdown(f"#### {year if is_book else year + ' 年'} · {paper['label']}")
        detail = paper['metadata']
        if detail.get('page_start'):
            st.caption(f"来源 PDF 第 {detail['page_start']}–{detail['page_end']} 页" + ('' if is_book else ' · 试卷名称已核对标准名录'))
        drafts = paper_drafts(db_path, nodes, paper_id, with_assets=True)
        if not drafts:
            st.info('已建立章节目录，此小节尚未完成题目转写。' if is_book else '已建立试卷目录，题目尚未转写、配图和打标签，当前没有可审核草稿。')
            return
        action_cols = st.columns(3, gap='small')
        bulk_action = ''
        for col, label, mode in zip(
            action_cols,
            ['录入所有未处理问题', '录入所有非重复问题', '录入所有非重复与相似问题'],
            ['all', 'non_duplicate', 'non_exact'],
        ):
            with col:
                if st.button(label, key=f'ingestion_bulk_{mode}_{paper_id}', use_container_width=True,
                             type='primary' if mode == 'all' else 'secondary'):
                    bulk_action = mode
        if bulk_action:
            _run_bulk_review_action(db_path, drafts, bulk_action)
            drafts = paper_drafts(db_path, nodes, paper_id, with_assets=True)
        pending = sum(d['review_status'] in {'needs_review', 'ready', 'blocked'} for d in drafts)
        position_duplicate_count = 0
        similar_count = 0
        summary = st.empty()
        summary.caption(f'整卷共 {len(drafts)} 道草稿 · 待处理 {pending} 道 · 正在核对重复与相似题')
        preview_ids = set()
        token = _db_token(db_path)
        for start in range(0, len(drafts), 2):
            columns = st.columns(2, gap='medium')
            for offset, row in enumerate(drafts[start:start + 2]):
                with columns[offset]:
                    draft = row
                    extra = metadata(draft.get('extra_json'))
                    number = extra.get('detected_question_number') or extra.get('question_number') or start + offset + 1
                    preview_ids.update(_render_question(db_path, draft, number, render_preview, token))
                    position_conflicts, draft_matches = _matches(
                        db_path, token, draft.get('stem_tex') or '',
                        tuple(json.loads(draft.get('choices_json') or '[]')),
                        draft.get('question_type_id'), draft.get('extra_json') or '{}')
                    position_duplicate_count += bool(position_conflicts)
                    similar_count += any(match.get('kind') == 'similar' for match in draft_matches)
        summary.caption(
            f'整卷共 {len(drafts)} 道草稿 · 待处理 {pending} 道 · '
            f'同位置重复 {position_duplicate_count} 道 · 高度相似 {similar_count} 道 · 以下全部展开')
        # One floating preview per existing question, outside the question grid.
        for question_id in sorted(preview_ids):
            render_duplicate_preview(question_id)
