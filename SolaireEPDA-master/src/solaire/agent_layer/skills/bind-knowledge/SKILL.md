---
name: bind_knowledge
description: >
  在题库中检索题目并挂接到知识图谱节点，支持单题与批量绑定。当教师提到题目挂载、
  知识点绑定、题目关联知识点、批量挂接等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.1"
  label: 题目挂载知识点
  tool_patterns: "bank.* graph.list_nodes graph.search_nodes graph.bind_question graph.batch_bind_questions graph.batch_create_nodes graph.create_relation graph.batch_create_relations memory.* agent.*"
  suggested_user_input: 我想把题库里的题目挂到知识图谱的知识点下，请一步步协助我完成。
---

## 工作流程

1. 用 `bank.search_items` / `bank.get_item` 确认题目**完整标识**（`科目/题集/题内id`）
2. 用 `graph.search_nodes` 或 `graph.list_nodes` 确认要点 id 与名称
3. 单题用 `graph.bind_question`；多题同一要点优先 `graph.batch_bind_questions`
4. 要点缺失时再用 `graph.batch_create_nodes` / `graph.create_relation` 等补全（先父后子）

## 注意事项

- 勿编造题目或要点标识，每一步以工具返回为准
- 批量操作前向教师复述「题号 ↔ 要点」对应表，确认后再执行
