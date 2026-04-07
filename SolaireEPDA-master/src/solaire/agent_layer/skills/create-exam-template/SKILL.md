---
name: create_exam_template
description: >
  在项目内起草或修改试卷模板 YAML（小节结构、版式、默认卷面参数），写入后可用预览工具校验。
  当教师提到新建模板、改模板、试卷结构、章节分值、单栏双栏、LaTeX 基架名等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.0"
  label: 创建试卷模板
  tool_patterns: "exam.list_templates exam.get_template_preview file.write file.read file.edit file.list memory.* agent.*"
  suggested_user_input: 请帮我新建一份试卷模板，包含选择题与解答题两个考查小节，并写入项目。
---

## 概念

- **试卷模板**是 `templates/` 下的 `*.yaml`，描述「有哪些小节、每节抽几题、默认分值、版式与 LaTeX 主文件」等；**不等于**某次考试的选题结果。
- **`template_id`** 应与文件用途一致且在项目内可区分；**`latex_base`** 指向 Jinja 主模板文件名（通常与内置或项目内 `*.tex.j2` 对应）。
- **`type: text`** 的小节为说明块，**`required_count` 必须为 0**。

## 参考索引（语法与示例）

完整字段说明、合法小节 `type`、`metadata_defaults` 常用键，见同目录：

- `references/exam-template-schema.md`

## 工作流程

1. `exam.list_templates` 看现有命名习惯；可 `exam.get_template_preview` 参考同类模板的小节列表。
2. 按参考文件起草 YAML 全文（勿遗漏必填字段）。
3. `file.write` 写入 `templates/<建议文件名>.yaml`（路径为项目相对路径）。
4. 再次调用 `exam.get_template_preview`（`template_path` 同上）确认可被编译器解析；若报错，根据错误信息用 `file.edit` 修正。

## 注意事项

- 不擅自覆盖教师未点名的模板文件；新建优先使用新文件名。
- 修改 `latex_base` 前确认对应 `*.tex.j2` 在项目或内置基架中存在。
- 组卷与导出仍走 `smart_compose` 技能中的校验 / 导出工具链。
