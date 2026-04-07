"""学情诊断（M2）：知识点维度、学生掌握矩阵、班级热力与复讲/补题建议草案。

数据来自成绩分析缓存（含每生每题得分率）与知识图谱题目绑定。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from solaire.edu_analysis.ports import get_result_port
from solaire.knowledge_forge import list_questions_for_node, load_graph


def _analysis_or_raise(project_root: Path, exam_id: str, batch_id: str) -> dict[str, Any]:
    return get_result_port().get_score_analysis(project_root, exam_id, batch_id)


def _node_labels(project_root: Path) -> dict[str, tuple[str, str]]:
    state = load_graph(project_root)
    return {n.id: (n.canonical_name, n.node_kind) for n in state.nodes}


def _question_index_map(raw: dict[str, Any]) -> dict[str, int]:
    order = raw.get("question_order") or []
    return {str(qid): i for i, qid in enumerate(order)}


def _node_to_question_indices(project_root: Path, qid_to_i: dict[str, int]) -> dict[str, list[int]]:
    state = load_graph(project_root)
    node_to_qi: dict[str, list[int]] = {}
    for b in state.bindings:
        qi = qid_to_i.get(b.question_qualified_id)
        if qi is None:
            continue
        node_to_qi.setdefault(b.node_id, []).append(qi)
    for nid in node_to_qi:
        node_to_qi[nid] = sorted(set(node_to_qi[nid]))
    return node_to_qi


def knowledge_diagnosis_v1(project_root: Path, exam_id: str, batch_id: str) -> dict[str, Any]:
    """班级知识点薄弱排序（附节点显示名）。"""
    raw = _analysis_or_raise(project_root, exam_id, batch_id)
    labels = _node_labels(project_root)
    nodes_out: list[dict[str, Any]] = []
    for ns in raw.get("node_stats", []) or []:
        nid = str(ns.get("node_id") or "")
        name, kind = labels.get(nid, (nid, "concept"))
        nodes_out.append(
            {
                **ns,
                "canonical_name": name,
                "node_kind": kind,
            },
        )
    nodes_sorted = sorted(nodes_out, key=lambda x: float(x.get("error_rate", 0) or 0), reverse=True)
    return {
        "exam_id": exam_id,
        "batch_id": batch_id,
        "nodes": nodes_sorted,
        "class_avg_ratio": raw.get("class_avg_ratio"),
        "class_avg_fuzzy": raw.get("class_avg_fuzzy"),
        "unbound_warnings": raw.get("warnings", []),
    }


def student_knowledge_diagnosis_v1(
    project_root: Path,
    exam_id: str,
    batch_id: str,
    *,
    student_id: str | None = None,
) -> dict[str, Any]:
    """每位学生（或指定学号）在各知识点的平均得分率。"""
    raw = _analysis_or_raise(project_root, exam_id, batch_id)
    rows = raw.get("student_mastery_rows") or []
    qid_to_i = _question_index_map(raw)
    node_to_qi = _node_to_question_indices(project_root, qid_to_i)
    labels = _node_labels(project_root)
    sorted_nodes = sorted(node_to_qi.keys())

    def mastery_for_row(row: dict[str, Any], nid: str) -> float | None:
        ratios: list[Any] = row.get("ratios") or []
        qis = node_to_qi.get(nid) or []
        vals = [ratios[i] for i in qis if i < len(ratios) and ratios[i] is not None]
        if not vals:
            return None
        return round(sum(float(v) for v in vals) / len(vals), 4)

    out_students: list[dict[str, Any]] = []
    for row in rows:
        sid = str(row.get("student_id") or "")
        if student_id is not None and sid != student_id:
            continue
        by_node: dict[str, Any] = {}
        for nid in sorted_nodes:
            m = mastery_for_row(row, nid)
            if m is not None:
                nm, k = labels.get(nid, (nid, "concept"))
                by_node[nid] = {"mastery": m, "canonical_name": nm, "node_kind": k}
        out_students.append(
            {
                "name": row.get("name"),
                "student_id": sid,
                "by_node": by_node,
            },
        )
    return {
        "exam_id": exam_id,
        "batch_id": batch_id,
        "students": out_students,
        "node_ids": sorted_nodes,
    }


def class_heatmap_v1(project_root: Path, exam_id: str, batch_id: str) -> dict[str, Any]:
    """学生 × 知识点 得分率矩阵（用于热力图）。"""
    sk = student_knowledge_diagnosis_v1(project_root, exam_id, batch_id, student_id=None)
    node_ids: list[str] = sk.get("node_ids") or []
    students = sk.get("students") or []
    matrix: list[list[float | None]] = []
    for st in students:
        row: list[float | None] = []
        bn = st.get("by_node") or {}
        for nid in node_ids:
            cell = bn.get(nid)
            row.append(float(cell["mastery"]) if isinstance(cell, dict) and cell.get("mastery") is not None else None)
        matrix.append(row)
    columns = []
    labels = _node_labels(project_root)
    for nid in node_ids:
        nm, _ = labels.get(nid, (nid, "concept"))
        columns.append({"node_id": nid, "canonical_name": nm})
    return {
        "exam_id": exam_id,
        "batch_id": batch_id,
        "rows": [{"name": s.get("name"), "student_id": s.get("student_id")} for s in students],
        "columns": columns,
        "matrix": matrix,
    }


def teaching_suggestions_v1(
    project_root: Path,
    exam_id: str,
    batch_id: str,
    *,
    weak_limit: int = 8,
    practice_per_node: int = 12,
) -> dict[str, Any]:
    """复讲优先级（按知识点错误率高到低）+ 薄弱点关联题库题目草案。"""
    kd = knowledge_diagnosis_v1(project_root, exam_id, batch_id)
    nodes = kd.get("nodes") or []
    weak = nodes[: max(1, weak_limit)]
    retell_priority: list[dict[str, Any]] = []
    for i, n in enumerate(weak):
        retell_priority.append(
            {
                "priority": i + 1,
                "node_id": n.get("node_id"),
                "canonical_name": n.get("canonical_name"),
                "error_rate": n.get("error_rate"),
                "mastery_fuzzy": n.get("mastery_fuzzy"),
                "bound_question_count": n.get("bound_question_count"),
            },
        )
    practice_drafts: list[dict[str, Any]] = []
    for n in weak[:5]:
        nid = str(n.get("node_id") or "")
        if not nid:
            continue
        qids = list_questions_for_node(project_root, nid)[:practice_per_node]
        practice_drafts.append(
            {
                "node_id": nid,
                "canonical_name": n.get("canonical_name"),
                "suggested_question_ids": qids,
                "count": len(qids),
            },
        )
    return {
        "exam_id": exam_id,
        "batch_id": batch_id,
        "retell_priority": retell_priority,
        "practice_drafts": practice_drafts,
    }
