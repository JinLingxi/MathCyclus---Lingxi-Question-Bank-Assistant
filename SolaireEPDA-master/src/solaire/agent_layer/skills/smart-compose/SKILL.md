---
name: smart_compose
description: >
  结合题库、试卷模板与选题方案完成校验与导出。当教师提到组卷、出卷、试卷编排、
  校验试卷、导出 PDF 等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.1"
  label: 智能组卷协助
  tool_patterns: "bank.* exam.* graph.list_nodes graph.list_relations graph.search_nodes memory.* agent.*"
  suggested_user_input: 我想组一份卷子，请根据当前模板和题库给我建议和校验步骤。
---

## 工作流程

1. `exam.list_templates` 列出模板；需要小节结构时用 `exam.get_template_preview`（`template_path` 为项目内相对路径）
2. `bank.search_items` / `bank.get_item` 确认题目 id 与内容
3. 组好 `selected_items`（含 `section_id`、`question_ids`，可选 `score_per_item` / `score_overrides`）后调用 `exam.validate_paper`
4. 仅在校验通过后，且教师明确同意导出时，调用 `exam.export_paper`（须含 `export_label`、`subject` 等）

## 注意事项

- 导出前说明将写入的目录与文件名含义，并取得确认
- 校验失败时引用报错中的小节或题号，给出可操作的修改建议
- 需要提前确认版式能否生成时，在校验中开启版式编译试跑（`include_latex_check`）；若导出或版式试跑失败，应依据报错修改题目或模板后再校验，避免在相同条件下重复校验
- 新建或大改模板本身请使用 `create_exam_template` 技能，不在此技能内硬编码模板结构

