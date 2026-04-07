---
name: weak_points
description: >
  在已有分析或统计结果基础上，将薄弱表现与知识图谱要点对照解读。当教师提到薄弱项、
  薄弱知识点、知识点掌握分布、把分数对应到图谱等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.1"
  label: 薄弱项分析
  tool_patterns: "analysis.* graph.list_nodes graph.list_relations graph.search_nodes memory.* agent.*"
  suggested_user_input: 请根据已有成绩数据，帮我分析班级薄弱知识点并对应到图谱。
---

## 与 `score_diagnosis` 的分工

- **`score_diagnosis`**：驱动内置分析流水线（列举数据集、选内置任务、轮询作业）。
- **本技能**：以「知识点视角」串联结论，用图谱工具核对要点名称、关系，便于教师行动。

## 工作流程

1. 若尚无分析结果，可先按 `score_diagnosis` 的路径跑内置分析，或直接使用已有输出
2. 用 `graph.search_nodes` / `graph.list_relations` 将结论中的知识点与图中节点对齐
3. 向教师说明时写明**考试标识、成绩批次、样本量**

## 注意事项

- 不得编造分数或排名；所有论断须能追溯到工具返回或教师提供的材料

