# 试卷模板 YAML 参考

对应编译器模型 `ExamTemplate` / `TemplateSection`（以仓库当前版本为准）。

## 顶层字段

| 字段 | 说明 |
|------|------|
| `template_id` | 模板逻辑 id，建议与文件名或用途一致 |
| `layout` | `single_column` 或 `double_column` |
| `latex_base` | Jinja 主模板文件名，如 `exam-zh-base.tex.j2` |
| `sections` | 小节列表（见下表） |
| `metadata_defaults` | 可选。与正式组卷时的试卷级信息**深度合并**；可含插图在 PDF 中的宽度等（键名由 LaTeX 基架约定） |

## 小节 `sections[]` 每项

| 字段 | 说明 |
|------|------|
| `section_id` | 小节 id，组卷选题时引用 |
| `type` | `text`（说明块） / `group` / `choice` / `fill` / `judge` / `short_answer` / `reasoning` / `essay` |
| `required_count` | 本小节题目数量下限（整数 ≥0） |
| `score_per_item` | 每题默认分值（≥0） |
| `describe` | 可选，小节说明 |

**规则**：`type: text` 时 **`required_count` 必须为 0**（该块不抽题）。

## `metadata_defaults` 常见键（可选）

与模板工作台、导出流水线一致，常用包括（具体以项目模板与基架为准）：

- `primebrush_pdf` → `latex_width`：教育绘图插图在 PDF 中的宽度（LaTeX 长度表达式）
- `mermaid_pdf` → `landscape_width` / `portrait_width` / `portrait_max_height`：流程图插图尺寸

## 最小可用示例

```yaml
template_id: demo_midterm_v1
layout: single_column
latex_base: exam-zh-base.tex.j2
sections:
  - section_id: instr
    type: text
    required_count: 0
    score_per_item: 0
    describe: 考试说明与注意事项
  - section_id: mcq
    type: choice
    required_count: 10
    score_per_item: 3
    describe: 选择题
  - section_id: sa
    type: short_answer
    required_count: 4
    score_per_item: 10
    describe: 填空或简答
metadata_defaults:
  primebrush_pdf:
    latex_width: "0.9\\linewidth"
  mermaid_pdf:
    landscape_width: "0.62\\linewidth"
    portrait_width: "0.52\\linewidth"
```

## 兼容说明

若历史文件顶层曾使用 `layout_options`，编译器会合并入 `metadata_defaults`；**新稿请直接写 `metadata_defaults`**。
