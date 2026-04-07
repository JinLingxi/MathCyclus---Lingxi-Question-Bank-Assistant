from __future__ import annotations

from pathlib import Path

import pytest

from solaire.web.app import ensure_project_layout
from solaire.web.graph_service import (
    attach_file_to_node,
    bind_question_to_node,
    bind_questions_batch,
    create_concept_node,
    create_node_relation,
    delete_concept_node,
    delete_node_relation,
    get_concept_node,
    list_concept_nodes,
    list_node_relations,
    list_nodes_for_question,
    list_questions_for_node,
    unbind_question_from_node,
    unbind_questions_batch,
    update_concept_node,
)


def test_concept_node_crud_round_trip(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ensure_project_layout(root)

    node_id = "math/func/derivative"
    create_concept_node(
        root,
        {
            "id": node_id,
            "canonical_name": "导数",
            "subject": "数学",
            "level": "高中",
            "description": "求导相关概念",
            "tags": ["微分"],
            "aliases": ["Derivative"],
        },
    )

    nodes = list_concept_nodes(root)
    assert node_id in {n["id"] for n in nodes}

    d = get_concept_node(root, node_id)
    assert d["canonical_name"] == "导数"


def test_list_nodes_includes_file_link_count(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    res_dir = root / "resource" / "资料"
    res_dir.mkdir(parents=True, exist_ok=True)
    (res_dir / "a.txt").write_text("a", encoding="utf-8")
    (res_dir / "b.txt").write_text("b", encoding="utf-8")
    create_concept_node(root, {"id": "n-with-files", "canonical_name": "A", "aliases": []})
    create_concept_node(root, {"id": "n-empty", "canonical_name": "B", "aliases": []})
    attach_file_to_node(root, "n-with-files", "资料/a.txt")
    attach_file_to_node(root, "n-with-files", "资料/b.txt")
    nodes = list_concept_nodes(root)
    assert next(n for n in nodes if n["id"] == "n-with-files")["file_link_count"] == 2
    assert next(n for n in nodes if n["id"] == "n-empty")["file_link_count"] == 0


def test_relation_and_question_binding_and_cascade_delete(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ensure_project_layout(root)

    a = "math/func/derivative"
    b = "math/func/extrema"
    create_concept_node(root, {"id": a, "canonical_name": "导数", "subject": "数学", "aliases": []})
    create_concept_node(root, {"id": b, "canonical_name": "极值", "subject": "数学", "aliases": []})

    rel_id = create_node_relation(
        root,
        {"from_node_id": a, "to_node_id": b, "relation_type": "prerequisite"},
    )
    rels = list_node_relations(root)
    assert any(r["id"] == rel_id for r in rels)

    qid = "数学/高考真题/demo_choice_001"
    bind_question_to_node(root, {"question_qualified_id": qid, "node_id": a})
    assert qid in set(list_questions_for_node(root, a))

    # delete node a should cascade: node removed, relations removed, bindings removed
    delete_concept_node(root, a)
    assert a not in {n["id"] for n in list_concept_nodes(root)}
    assert not any(r["from_node_id"] == a or r["to_node_id"] == a for r in list_node_relations(root))
    assert qid not in set(list_questions_for_node(root, a))


def test_relation_requires_at_least_one_concept_endpoint(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    create_concept_node(
        root,
        {"id": "skill-a", "canonical_name": "技能甲", "node_kind": "skill", "aliases": []},
    )
    create_concept_node(
        root,
        {"id": "causal-b", "canonical_name": "因果乙", "node_kind": "causal", "aliases": []},
    )
    with pytest.raises(ValueError, match="知识点"):
        create_node_relation(
            root,
            {"from_node_id": "skill-a", "to_node_id": "causal-b", "relation_type": "related"},
        )


def test_duplicate_node_id_rejected(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    node_id = "math/func/derivative"
    create_concept_node(root, {"id": node_id, "canonical_name": "导数", "subject": "数学", "aliases": []})
    with pytest.raises(ValueError):
        create_concept_node(root, {"id": node_id, "canonical_name": "导数2", "subject": "数学", "aliases": []})


def test_update_node_and_unbind_and_delete_relation(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ensure_project_layout(root)

    a = "math/func/derivative"
    b = "math/func/extrema"
    create_concept_node(root, {"id": a, "canonical_name": "导数", "subject": "数学", "aliases": []})
    create_concept_node(root, {"id": b, "canonical_name": "极值", "subject": "数学", "aliases": []})

    rel_id = create_node_relation(
        root,
        {"from_node_id": a, "to_node_id": b, "relation_type": "related"},
    )

    qid = "数学/高考真题/demo_choice_001"
    bind_question_to_node(root, {"question_qualified_id": qid, "node_id": a})
    assert qid in set(list_questions_for_node(root, a))

    # update node (created_at preserved)
    created_at_before = get_concept_node(root, a)["created_at"]
    update_concept_node(
        root,
        a,
        {
            "id": a,
            "canonical_name": "导数（更新）",
            "subject": "数学",
            "aliases": [],
        },
    )
    d = get_concept_node(root, a)
    assert d["canonical_name"] == "导数（更新）"
    assert d["created_at"] == created_at_before

    # unbind
    unbind_question_from_node(root, {"question_qualified_id": qid, "node_id": a})
    assert qid not in set(list_questions_for_node(root, a))

    # delete relation
    delete_node_relation(root, rel_id)
    assert not any(r["id"] == rel_id for r in list_node_relations(root))


def test_bind_questions_batch_and_list_nodes_for_question_and_unbind_batch(tmp_path: Path) -> None:
    root = tmp_path / "proj"
    ensure_project_layout(root)
    node = "math/topic/a"
    create_concept_node(root, {"id": node, "canonical_name": "主题A", "subject": "数学", "aliases": []})
    q1 = "数学/题库/q1"
    q2 = "数学/题库/q2"
    out = bind_questions_batch(root, node_id=node, qualified_ids=[q1, q2, q1])
    assert out["added"] == 2
    assert out["skipped"] == 1
    assert set(list_questions_for_node(root, node)) == {q1, q2}
    nodes_for_q1 = list_nodes_for_question(root, q1)
    assert len(nodes_for_q1) == 1
    assert nodes_for_q1[0].id == node
    rem = unbind_questions_batch(root, node_id=node, qualified_ids=[q1])
    assert rem["removed"] == 1
    assert q1 not in set(list_questions_for_node(root, node))
    assert q2 in set(list_questions_for_node(root, node))

