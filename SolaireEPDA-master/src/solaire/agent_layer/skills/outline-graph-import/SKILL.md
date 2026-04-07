---
name: outline_graph_import
description: >
  将大纲、课标或复习材料中的要点层级整理为图谱节点与关系，并批量写入当前项目。
  当教师提到导入大纲、课标整理、知识点结构化、批量建要点等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.1"
  label: 课标大纲导入图谱
  tool_patterns: "graph.* web.search memory.* agent.*"
  suggested_user_input: 请根据我提供的高考大纲内容，整理成知识要点并批量写入当前项目的知识图谱。
---

## 工作流程

1. 从教师材料抽取**层级清单**（父要点 → 子要点），明确拟用 `kind` / 标签（以工具约定为准）
2. **先创建父、后创建子**；必要时 `graph.batch_create_nodes` 分批提交
3. 用 `graph.batch_create_relations` 表达前置、并列等关系（类型以图谱当前支持为准）
4. 需核对公开表述时使用 `web.search`，摘录须注明来源与日期

## 注意事项

- 不扩充材料中未出现的知识点；不确定处向教师确认
- 写入前可摘要「将新增节点数 / 关系数」请教师确认

