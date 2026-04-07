# 项目内主要文件格式（题库 / 模板 / 组卷）

本文面向**开发者、自动化脚本与助手**：说明考试项目内与组卷相关的磁盘文件与 **YAML** 结构要点。完整字段以代码库中的校验模型为准。

---

## 1. 项目目录（约定）

```
<项目根>/
  resource/<科目>/<题集>/     # 题库：questions.yaml 或若干 *.yaml
  templates/                   # 试卷模板：*.yaml + LaTeX 基架
  result/                      # 导出 PDF 等产物
  analysis/                    # 自定义分析脚本（可选）
  .solaire/                    # 组卷/构建辅助（由工具生成，勿手改除非排错）
    drafts/                    # 组卷草稿
    agent/                     # 智能助手：会话、记忆、审计等（由系统写入）
```

---

## 2. 题库：`questions.yaml` 与单题文件

- **位置**：`resource/<科目>/<题集>/` 下。
- **形态**：
  - **合并文件**：根键 `questions:`，值为题目对象列表；可含 **`groups`**（题组）。
  - **多文件**：同目录多个 `*.yaml`，每文件一道题或一组结构（导入合并规则见 Web 导入逻辑）。

**单题（根上一条记录）常见字段：**

| 字段 | 说明 |
|------|------|
| `id` | 题内唯一标识 |
| `type` | `choice` / `fill` / `judge` / `short_answer` / `reasoning` / `essay` 等 |
| `content` | 题干 |
| `options` | 选择题选项键值；非选择题不应出现 |
| `answer` | 答案（判断题为 `T`/`F`） |
| `analysis` | 解析，可空 |
| `metadata` | 扩展键值，供筛选或模板侧使用 |

**题组 `groups`**：混编多小题时，组内成员可带 `type`、`content`、`options` 等；展开后的题内 id 形如 `组id__01`。

---

## 3. 试卷模板：`templates/<名>.yaml`

对应编译器中的 **ExamTemplate** 概念，核心字段：

| 字段 | 说明 |
|------|------|
| `template_id` | 与文件名/引用一致 |
| `layout` | `single_column` 或 `double_column` |
| `latex_base` | LaTeX 基架文件名（如 `exam-zh-base.tex.j2`） |
| `sections` | 小节列表：每节含 `section_id`、`type`（含 `text`/`group`/各题型）、`required_count`、`score_per_item`、`describe` 等 |
| `metadata_defaults` | 与组卷时试卷 metadata **深度合并**；用于版式默认、插图在 PDF 中的宽度等 |

`type: text` 的小节通常 **`required_count` 必须为 0**（纯说明块，不抽题）。

---

## 4. 组卷草稿与构建用 `exam.yaml`

- Web 在**校验**或**导出**时会在 `.solaire/` 下生成/更新面向流水线的 **exam 描述文件**（名称以产品实现为准，如 `validate.yaml` / 构建用 `build.yaml`）。
- 内容包含：**选用的 `template_ref`、模板相对路径、各小节已选题目 id 列表、试卷标题等 metadata**；各小节还可选 `score_per_item`、`score_overrides`（按题目完整编号覆盖分值）。  
- **教师草稿**另存于 `.solaire/drafts/*.yaml`，便于下次继续组卷；**不要**手工编辑流水线用 `build.yaml` / `validate.yaml` 代替界面操作，除非明确在排错。

---

## 5. 与「交换包」的关系

题库 **ZIP 交换包**内含合并的 `questions.yaml` 与 `image/` 等；结构需符合导入器的宽松/严格模式。见用户向手册「题库交换包」篇。

---
## 6. Jinja 模板与 `template.yaml` 的关系（给 AI 更新用）

当你需要让 AI 去编辑/扩展 LaTeX 输出版式时，最关键的对应关系是：

1. `templates/<名>.yaml` 里的 `latex_base`
2. 与 `latex_base` 同名的 `*.tex.j2` Jinja 模板文件

### 6.1 `template.yaml` 决定渲染“用哪一份 Jinja 模板”

- `template.yaml` 提供一个字段：`latex_base`（例如 `exam-zh-base.tex.j2`）
- 生成 PDF 时，系统会以 `latex_base` 作为 Jinja 的“主模板文件名”
- 主模板会收到模板渲染所需的上下文数据，用来把题目内容与版式骨架拼成 `.tex`

### 6.2 Jinja 搜索顺序：先项目覆盖，再使用内置基架

在模板渲染时，系统会按下面顺序查找 `latex_base` 对应的 `*.tex.j2`：

- 优先在该 `template.yaml` 所在目录下查找 `latex_base` 对应文件
- 若项目目录未提供，再查找内置的模板基架目录

因此，如果你希望“AI 修改后只影响某个模板”，推荐把新的 `*.tex.j2` 放到同一个 `template.yaml` 目录里，并保持文件名与 `latex_base` 完全一致。

### 6.3 主模板会拿到哪些关键数据（模板作者需要关心）

Jinja 主模板渲染时会提供以下主要变量（字段名以系统实际传入为准）：

- `metadata`：试卷级 metadata（用于抬头、页眉页脚、版式参数等）
- `exam_id`：当前考试/试卷的标识
- `graphicspath_command`：用于 LaTeX 找图的命令片段
- `sections`：小节数据（来自 `template.yaml` 的 `sections`，并结合组卷选题结果）
- `show_answers`：是否展示答案/解析

其中 `sections` 的结构大致可理解为：每个小节有 `section_id`、`type`、`describe`、`score_per_item`、以及一组 `questions`；每个 `question` 里包含 `content`、`options`（如选择题）、`answer`、`analysis`、用于显示的编号 `display_number`、以及合并分值后的 `item_score` 等。

### 6.4 你该怎么写/更新 Jinja（最少约束）

- 使用系统配置的 Jinja 定界符：变量用 `[[ ... ]]`，代码块用 `[% ... %]`
- 需要把题干/说明等“原样文本”输出到 LaTeX 时，优先使用模板上下文字段；涉及特殊字符时由系统侧的处理规则来保证安全

如果你希望 AI 给出更具体的模板草案，请从 `template.yaml` 的 `latex_base` 文件名开始定位：先确认主模板 `*.tex.j2` 属于“项目目录覆盖”还是“内置基架”，再进行局部替换或 include 扩展。

### 6.5 与 `*.metadata_ui.yaml` 的关联（影响编辑界面，不改变 LaTeX 主渲染）

与 `latex_base` 同 stem 的 `*.metadata_ui.yaml` 文件，用来声明模板工作台可编辑的 metadata 扩展字段；它主要服务于“在界面上填什么、怎么填”，而不是直接参与 `.tex` 的主模板渲染。
