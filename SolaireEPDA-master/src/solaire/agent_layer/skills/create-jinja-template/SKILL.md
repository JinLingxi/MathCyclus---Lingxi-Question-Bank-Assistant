---
name: create_jinja_template
description: >
  起草或修改卷面主模板（*.tex.j2）：正确使用系统 Jinja 定界符、渲染上下文与 LaTeX 转义规则，
  与试卷模板 YAML 的「版式模板」文件名对齐。当教师提到版式主模板、卷面排版、LaTeX 骨架、
  *.tex.j2、Jinja、页眉页脚或选择题版式等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.0"
  label: 卷面主模板（Jinja2）
  tool_patterns: "exam.list_templates exam.get_template_preview file.read file.write file.edit file.list memory.* agent.*"
  suggested_user_input: 请根据现有高考样例，帮我起草一份同结构的卷面主模板并保存到模板目录。
---

## 概念

- **卷面主模板**是 `*.tex.j2` 文件，由组卷管线渲染为 `.tex` 再编译 PDF；试卷 YAML 里的 **版式模板**（`latex_base`）必须与其**文件名**一致。
- 项目内优先使用与 `template.yaml` **同目录**的 `*.tex.j2`，便于单模板隔离修改；查找顺序见 `references/jinja-reference.md`。
- 本技能与 `create_exam_template`（起草 `template.yaml`）配合：一个管「结构与小节」，一个管「LaTeX 版式骨架」。

## 工作流程

1. 用 `exam.list_templates` / `file.read` 确认目标 `template.yaml` 及其 `latex_base`；若新建，与教师约定文件名并在 YAML 中同步。
2. 以仓库内完整示例为蓝本阅读结构（推荐）：`examples/gaokao_sample/templates/exam-zh-base.tex.j2`；细节约定见 `references/jinja-reference.md`。
3. 起草或修改 `*.tex.j2`：**仅使用**系统配置的定界符（变量 `[[ ]]`，控制 `[% %]`，注释 `[# #]`），勿与默认 `{{ }}`/`{% %}` 混用。
4. `file.write` 写入与 `template.yaml` 同目录（或教师指定的模板目录），文件名与 `latex_base` 一致。
5. `exam.get_template_preview`（或项目既有预览/导出链路）验证可被解析；报错则根据栈信息用 `file.edit` 修正。

## 注意事项

- 新建模板前，请向用户征集意见，用小学语文老师也能明白的名词进行意见征集
- 用户可见文案中避免堆砌实现术语；技能内说明以「版式模板」「卷面设置」等业务用语为主。
- 教师未点名的文件不要覆盖；新建优先新文件名并在 YAML 中引用。
- 题干等已由管线处理为可进 LaTeX 的片段时按参考示例使用 `|safe`；纯文本元数据用 `|latex_escape`，见参考文件。

## 参考索引

- `references/jinja-reference.md`：定界符、上下文变量、过滤器、与 `exam-zh-base.tex.j2` 对照要点。
