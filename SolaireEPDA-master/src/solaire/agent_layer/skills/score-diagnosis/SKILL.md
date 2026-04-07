---
name: score_diagnosis
description: >
  基于项目内考试数据列举数据集与内置分析任务，运行流水线并解读作业输出。
  当教师提到成绩分析、考试诊断、跑内置统计、学情作业结果等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.1"
  label: 成绩诊断报告
  tool_patterns: "analysis.* memory.* agent.*"
  suggested_user_input: 请根据当前项目里已有的考试成绩，帮我做一份成绩诊断要点。
---

## 工作流程

1. `analysis.list_datasets` → 确认考试与批次
2. `analysis.list_builtins` → 选择合适内置任务
3. `analysis.run_builtin` 提交作业，再用 `analysis.get_job` 轮询至结束
4. 将输出中的指标与图表要点转写为教师可执行的建议（注明考试 id、批次、样本量）

## 与 `weak_points` 的分工

本技能侧重**跑通分析作业与解读原始输出**；若要把结论挂到知识图谱上谈行动，可切换到 `weak_points`。

## 注意事项

- 不得伪造数据集或作业状态
- 作业失败时保留错误信息中的关键词，便于排查或改选其它内置任务

