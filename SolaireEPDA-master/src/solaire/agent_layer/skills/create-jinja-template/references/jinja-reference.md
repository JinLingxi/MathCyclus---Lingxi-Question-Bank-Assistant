# Jinja 卷面主模板 — 实现约定（SolEdu）

## 定界符（必须与引擎一致）

渲染环境定义于 `src/solaire/exam_compiler/pipeline/render.py` 中 `_jinja_env`：

| 用途 | 定界符 |
|------|--------|
| 控制结构（if/for/set 等） | `[%` … `%]` |
| 变量与表达式输出 | `[[` … `]]` |
| 注释 | `[#` … `#]` |

**禁止**在模板中使用默认 Jinja 的 `{% %}` / `{{ }}`，否则无法解析。

## 传入模板的主要变量

`render_tex` 渲染时传入（名称以代码为准）：

- `metadata`：卷面级参数（标题、学校、边距、页脚、行距、字体等），键随 `template.yaml` 与组卷结果而定，访问时用 `metadata.get('键', 默认值)` 更稳妥。
- `sections`：小节列表；每项含 `section_id`、`type`、`describe`、`questions` 等；题目循环与材料题分支见示例模板。
- `show_answers`：教师版为真时展示答案/解析块。
- `graphicspath_command`：插入 LaTeX 插图路径命令片段（变量名即此）。
- `exam_id`：当前试卷标识。

## 可用过滤器

在 `_jinja_env` 中注册：

- `|latex_escape`：用于标题、学校名等**普通文本**元数据，避免 LaTeX 特殊字符问题。
- `|safe_label`：标签类安全处理（较少用）。
- Jinja 内置如 `|trim`、`|round` 等可按需使用。

题干、选项等已由管线处理为可嵌入 LaTeX 的内容时，示例中使用 `|safe` 输出（参见 `exam-zh-base.tex.j2`）。

## 模板查找顺序

与 `template.yaml` 同目录的 `latex_base` 文件优先；若不存在再解析内置基架目录。详见 `src/solaire/exam_compiler/latex_jinja_paths.py` 与文档 `src/solaire_doc/advanced/yaml-and-project-files.md` 第 6 节。

## 完整示例（结构参考）

仓库路径：

`examples/gaokao_sample/templates/exam-zh-base.tex.j2`

建议从中学习：

1. **前言区**：按 `metadata` 条件加载包（页眉页脚、装订线、行距、几何边距）。
2. **正文区**：`[% for sec in sections %]` 嵌套 `questions`，区分 `text` 小节与题目小节。
3. **选择题**：根据 `choice_layout`（如 `inline_one_line`、`grid_two_rows`）分支排版。
4. **答案块**：`[% if show_answers %]` 包裹答案与解析。

新建模板时宜先复制该文件再改样式，减少定界符与字段名错误。
