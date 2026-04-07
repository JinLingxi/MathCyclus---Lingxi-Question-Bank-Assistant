from __future__ import annotations

from typing import Any


BUILTINS: list[dict[str, Any]] = [
    {
        "builtin_id": "builtin:exam_stats_v1",
        "title": "考试统计分析 v1",
        "description": "复用现有成绩统计逻辑，输出题目/学生/知识点统计。",
    },
    {
        "builtin_id": "builtin:knowledge_diagnosis_v1",
        "title": "知识点诊断 v1",
        "description": "按知识点聚合薄弱程度并排序（需图谱题目绑定）。",
    },
    {
        "builtin_id": "builtin:student_diagnosis_v1",
        "title": "学生知识点掌握 v1",
        "description": "全班每位学生在各知识点的平均得分率。",
    },
    {
        "builtin_id": "builtin:class_heatmap_v1",
        "title": "班级热力图数据 v1",
        "description": "学生×知识点得分率矩阵，供可视化热力图使用。",
    },
    {
        "builtin_id": "builtin:teaching_suggestions_v1",
        "title": "复讲与补题建议 v1",
        "description": "薄弱知识点复讲顺序与关联题库题目草案。",
    },
]


def list_builtins() -> list[dict[str, Any]]:
    return BUILTINS
