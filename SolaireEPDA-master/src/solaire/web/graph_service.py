"""知识图谱 web 层适配（向后兼容重导出）。

领域逻辑已迁移至 solaire.knowledge_forge。
此文件保留导出以保持 web/app.py 和其他 web 层模块的导入路径不变。
新代码请直接从 solaire.knowledge_forge 导入。
"""

from solaire.knowledge_forge import (  # noqa: F401
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
