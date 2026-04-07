"""KnowledgeForge — 知识图谱领域模块。

提供知识点节点（ConceptNode）、关系（NodeRelation）、题目绑定（QuestionBinding）
和资料挂载（NodeFileLink）的持久化与查询能力。

公共 API 见本 __init__.py 的 __all__。
外部模块（包括 web 层）须从此处或 knowledge_forge.service 导入，不得深入内部实现。
"""

from solaire.knowledge_forge.service import (
    # 领域模型
    ConceptNode,
    GraphState,
    GraphTaxonomy,
    NodeFileLink,
    NodeRelation,
    QuestionBinding,
    # 持久化与查询
    attach_file_to_node,
    bind_question_to_node,
    bind_questions_batch,
    count_nodes_by_kind,
    create_concept_node,
    create_node_relation,
    delete_concept_node,
    delete_node_relation,
    detach_file_link,
    ensure_graph_layout,
    generate_unique_node_id,
    get_concept_node,
    get_taxonomy,
    list_concept_nodes,
    list_file_links_for_node,
    list_node_relations,
    list_nodes_for_question,
    list_questions_for_node,
    list_resource_files,
    load_graph,
    set_taxonomy,
    unbind_question_from_node,
    unbind_questions_batch,
    update_concept_node,
)

__all__ = [
    "ConceptNode",
    "GraphState",
    "GraphTaxonomy",
    "NodeFileLink",
    "NodeRelation",
    "QuestionBinding",
    "attach_file_to_node",
    "bind_question_to_node",
    "bind_questions_batch",
    "count_nodes_by_kind",
    "create_concept_node",
    "create_node_relation",
    "delete_concept_node",
    "delete_node_relation",
    "detach_file_link",
    "ensure_graph_layout",
    "generate_unique_node_id",
    "get_concept_node",
    "get_taxonomy",
    "list_concept_nodes",
    "list_file_links_for_node",
    "list_node_relations",
    "list_nodes_for_question",
    "list_questions_for_node",
    "list_resource_files",
    "load_graph",
    "set_taxonomy",
    "unbind_question_from_node",
    "unbind_questions_batch",
    "update_concept_node",
]
