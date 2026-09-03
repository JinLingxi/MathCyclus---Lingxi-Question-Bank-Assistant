"""Shared exam-selection helpers for legacy rows.

The functions in this module are side-effect free.  They select row payloads
only; callers decide whether to put resolved paths into the UI basket.
"""

from __future__ import annotations

import os
import random
import re
from pathlib import Path
from typing import Any


DEFAULT_HIGH_EXAM_SUBJECTS = [
    "集合",
    "复数",
    "不等式",
    "函数",
    "概率",
    "统计",
    "排列组合",
    "圆锥曲线",
    "解三角形",
    "三角函数",
    "立体几何",
    "向量",
    "数列",
    "导数",
]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(str(value).strip())
    except Exception:
        return default


def row_difficulty(row: dict[str, Any]) -> float:
    try:
        return float(row.get("难度星级") or 1.0)
    except Exception:
        return 1.0


def row_relative_path(row: dict[str, Any]) -> str:
    return str(row.get("相对文件路径") or "").strip()


def expand_selected_subjects(
    selected_subjects: list[str] | tuple[str, ...] | None,
    *,
    high_exam_subjects: list[str] | tuple[str, ...] | None = None,
) -> list[str]:
    high_exam_subjects = list(high_exam_subjects or DEFAULT_HIGH_EXAM_SUBJECTS)
    actual_subjects: list[str] = []
    seen: set[str] = set()
    for subject in selected_subjects or []:
        additions = high_exam_subjects if subject == "高考范围" else [str(subject)]
        for item in additions:
            item = str(item or "").strip()
            if item and item not in seen:
                actual_subjects.append(item)
                seen.add(item)
    return actual_subjects


def build_exam_intent_profile(intent_text: str, subjects: list[str] | tuple[str, ...]) -> dict[str, Any]:
    text = (intent_text or "").strip()
    if not text:
        return {"active": False, "text": "", "subjects": [], "tokens": [], "final_subjects": [], "difficulty": ""}

    subjects_in_text = [subject for subject in subjects if subject and subject in text]
    final_subjects = [
        subject
        for subject in subjects_in_text
        if re.search(
            rf"(最后|压轴|最后一题|最后一道).{{0,12}}{re.escape(subject)}|"
            rf"{re.escape(subject)}.{{0,12}}(最后|压轴|最后一题|最后一道)",
            text,
        )
    ]

    difficulty = ""
    if any(word in text for word in ("压轴", "拔高", "难题", "综合", "挑战")):
        difficulty = "hard"
    if any(word in text for word in ("基础", "简单", "不要太难", "别太难", "中档", "适中")):
        difficulty = "medium_or_easy"

    stop_words = {
        "本次",
        "组卷",
        "试卷",
        "题目",
        "考察",
        "侧重",
        "希望",
        "需要",
        "可以",
        "必须",
        "不要",
        "最后",
        "一道",
        "最后一道",
        "最后一题",
        "比较",
        "适合",
        "学生",
        "高中",
        "数学",
        "训练",
        "练习",
        "讲义",
        "模拟",
        "高考",
        "范围",
        "题型",
        "难度",
    }
    chunks = re.split(r"[\s，。；、,.!?！？：:（）()\[\]【】\"'“”‘’]+", text)
    tokens = set(subjects_in_text)
    for chunk in chunks:
        chunk = chunk.strip()
        if len(chunk) < 2 or chunk in stop_words:
            continue
        if len(chunk) <= 8:
            tokens.add(chunk)
        else:
            for size in (2, 3, 4):
                for index in range(0, max(0, len(chunk) - size + 1)):
                    token = chunk[index : index + size]
                    if token not in stop_words:
                        tokens.add(token)

    return {
        "active": True,
        "text": text,
        "subjects": subjects_in_text,
        "tokens": sorted(tokens, key=lambda value: (-len(value), value))[:80],
        "final_subjects": final_subjects,
        "difficulty": difficulty,
    }


def exam_intent_score(row: dict[str, Any], profile: dict[str, Any]) -> float:
    if not profile.get("active"):
        return 0.0

    haystack = "".join(
        str(row.get(field, ""))
        for field in ("文件名称", "试卷名称", "知识板块", "标签", "备注", "题干", "答案", "解析")
    )
    score = 0.0
    for subject in profile.get("subjects", []):
        if subject in str(row.get("知识板块", "")):
            score += 12
        elif subject in haystack:
            score += 6

    for token in profile.get("tokens", []):
        if token and token in haystack:
            score += min(8, max(2, len(token)))

    difficulty = row_difficulty(row)
    if profile.get("difficulty") == "hard":
        score += difficulty
    elif profile.get("difficulty") == "medium_or_easy":
        score += max(0.0, 6.0 - difficulty)
    return score


def row_looks_multi_choice(row: dict[str, Any]) -> bool:
    text = "".join(str(row.get(field, "")) for field in ("标签", "备注", "题干", "答案", "解析"))
    answer = str(row.get("答案", ""))
    answer_letters = re.findall(r"(?<![A-Za-z])([A-Da-d])(?![A-Za-z])", answer)
    return "多选" in text or len(set(letter.upper() for letter in answer_letters)) >= 2


def select_exam_rows(
    rows: list[dict[str, Any]],
    selected_subjects: list[str] | tuple[str, ...] | None,
    *,
    all_subjects: list[str] | tuple[str, ...],
    target_count: int,
    is_paper_template: bool,
    target_difficulty: float = 3.0,
    intent_text: str = "",
    high_exam_subjects: list[str] | tuple[str, ...] | None = None,
    random_seed: int | None = None,
) -> dict[str, Any]:
    actual_subjects = expand_selected_subjects(selected_subjects, high_exam_subjects=high_exam_subjects)
    candidates = [
        row
        for row in rows
        if row_relative_path(row)
        and (not actual_subjects or any(subject in str(row.get("知识板块", "")) for subject in actual_subjects))
    ]
    rng = random.Random(random_seed) if random_seed is not None else random
    intent_profile = build_exam_intent_profile(intent_text, all_subjects)
    used_paths: set[str] = set()

    def pick_rows(filtered: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
        if count <= 0:
            return []
        available = [row for row in filtered if row_relative_path(row) and row_relative_path(row) not in used_paths]
        if not available:
            return []
        if intent_profile.get("active"):
            available = sorted(
                available,
                key=lambda row: (
                    exam_intent_score(row, intent_profile),
                    -safe_int(row.get("组卷引用次数", "0")),
                    row_difficulty(row),
                    rng.random(),
                ),
                reverse=True,
            )
            picked = available[:count]
        else:
            picked = rng.sample(available, min(count, len(available)))
        used_paths.update(row_relative_path(row) for row in picked)
        return picked

    def sample_questions(
        pool: list[dict[str, Any]],
        count: int,
        *,
        question_type: str | None = None,
        difficulty_range: tuple[float, float] | None = None,
        prefer_multi: bool = False,
        prefer_subjects: list[str] | tuple[str, ...] | None = None,
    ) -> list[dict[str, Any]]:
        filtered = list(pool)
        if question_type:
            filtered = [row for row in filtered if question_type in str(row.get("题型", ""))]
        if difficulty_range:
            filtered = [row for row in filtered if difficulty_range[0] <= row_difficulty(row) <= difficulty_range[1]]
        if prefer_subjects:
            subject_filtered = [
                row
                for row in filtered
                if any(subject in str(row.get("知识板块", "")) for subject in prefer_subjects)
            ]
            if subject_filtered:
                filtered = subject_filtered
        if prefer_multi:
            multi_filtered = [row for row in filtered if row_looks_multi_choice(row)]
            if multi_filtered:
                filtered = multi_filtered

        picked = pick_rows(filtered, count)
        needed = count - len(picked)
        if needed <= 0:
            return picked

        backup = list(pool)
        if question_type:
            backup = [row for row in backup if question_type in str(row.get("题型", ""))]
        picked += pick_rows(backup, needed)
        return picked

    target_count = max(1, int(target_count or 1))
    selected_rows: list[dict[str, Any]]
    if is_paper_template:
        sq_base = sample_questions(candidates, 4, question_type="选择题", difficulty_range=(0.0, 2.5))
        sq_mid = sample_questions(candidates, 3, question_type="选择题", difficulty_range=(3.0, 4.0))
        sq_hard = sample_questions(candidates, 1, question_type="选择题", difficulty_range=(4.5, 6.0))
        mq_base = sample_questions(candidates, 1, question_type="选择题", difficulty_range=(0.0, 2.5), prefer_multi=True)
        mq_mid = sample_questions(candidates, 1, question_type="选择题", difficulty_range=(3.0, 4.0), prefer_multi=True)
        mq_hard = sample_questions(candidates, 1, question_type="选择题", difficulty_range=(4.5, 6.0), prefer_multi=True)
        fq_base = sample_questions(candidates, 1, question_type="填空题", difficulty_range=(0.0, 2.5))
        fq_mid = sample_questions(candidates, 1, question_type="填空题", difficulty_range=(3.0, 4.0))
        fq_hard = sample_questions(candidates, 1, question_type="填空题", difficulty_range=(4.5, 6.0))
        aq_base = sample_questions(candidates, 2, question_type="解答题", difficulty_range=(0.0, 2.5))
        aq_mid = sample_questions(candidates, 2, question_type="解答题", difficulty_range=(3.0, 4.0))
        aq_hard = sample_questions(
            candidates,
            1,
            question_type="解答题",
            difficulty_range=(4.5, 6.0),
            prefer_subjects=intent_profile.get("final_subjects"),
        )
        selected_rows = (
            sq_base
            + sq_mid
            + sq_hard
            + mq_base
            + mq_mid
            + mq_hard
            + fq_base
            + fq_mid
            + fq_hard
            + aq_base
            + aq_mid
            + aq_hard
        )
    else:
        base_count = int(target_count * 0.2)
        hard_count = int(target_count * 0.2)
        mid_count = target_count - base_count - hard_count
        mid_range = (max(0.0, target_difficulty - 1.0), min(6.0, target_difficulty + 1.0))
        base_range = (0.0, max(0.0, target_difficulty - 1.5))
        hard_range = (min(6.0, target_difficulty + 1.5), 6.0)
        selected_rows = (
            sample_questions(candidates, base_count, difficulty_range=base_range)
            + sample_questions(candidates, mid_count, difficulty_range=mid_range)
            + sample_questions(candidates, hard_count, difficulty_range=hard_range)
        )

    selected_rows = selected_rows[:target_count]
    return {
        "selected_rows": selected_rows,
        "selected_count": len(selected_rows),
        "target_count": target_count,
        "candidate_count": len(candidates),
        "actual_subjects": actual_subjects,
        "intent_profile": intent_profile,
    }


def legacy_row_to_existing_path(
    row: dict[str, Any],
    *,
    project_root: str | os.PathLike[str],
    chapters_dir: str | os.PathLike[str],
) -> str:
    raw_path = row_relative_path(row)
    if not raw_path:
        return ""

    root = Path(project_root).resolve()
    chapters = Path(chapters_dir).resolve()
    raw = Path(raw_path)
    candidates = [raw] if raw.is_absolute() else [root / raw_path, chapters / raw_path]

    for candidate in candidates:
        resolved = candidate.resolve()
        try:
            if os.path.commonpath([str(root), str(resolved)]) != str(root):
                continue
        except ValueError:
            continue
        if resolved.is_file():
            return str(resolved)
    return ""


def legacy_rows_to_existing_paths(
    rows: list[dict[str, Any]],
    *,
    project_root: str | os.PathLike[str],
    chapters_dir: str | os.PathLike[str],
) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for row in rows:
        path = legacy_row_to_existing_path(row, project_root=project_root, chapters_dir=chapters_dir)
        if path and path not in seen:
            paths.append(path)
            seen.add(path)
    return paths
