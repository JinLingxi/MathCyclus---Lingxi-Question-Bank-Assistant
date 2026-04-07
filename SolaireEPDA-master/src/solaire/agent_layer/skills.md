# 内置 Skill 参考模板

内置技能目录：`src/solaire/agent_layer/skills/<技能文件夹>/SKILL.md`。编排层通过 `name` 字段作为 `skill_id`。

| `name` | 文件夹 | 简述 |
|--------|--------|------|
| `create_question_yaml` | `create-question-yaml` | 按规范创建/更新题目 |
| `create_exam_template` | `create-exam-template` | 起草试卷模板 YAML |
| `create_jinja_template` | `create-jinja-template` | 卷面主模板（Jinja2） |
| `primebrush_diagrams` | `primebrush-diagrams` | 题面中 PrimeBrush 插图 |
| `smart_compose` | `smart-compose` | 组卷校验与导出 |
| `bind_knowledge` | `bind-knowledge` | 题目挂载图谱 |
| `outline_graph_import` | `outline-graph-import` | 大纲导入图谱 |
| `score_diagnosis` | `score-diagnosis` | 内置学情分析作业 |
| `weak_points` | `weak-points` | 薄弱项与图谱对照 |

---

## create_question_yaml

用途：供“创建题目”技能参考，生成符合题库单题文件格式的 YAML。

注意：
- `type` 仅可为：`choice` / `fill` / `judge` / `short_answer` / `reasoning` / `essay`
- 仅 `choice` 题允许 `options`
- `judge` 题 `answer` 仅可为 `T` 或 `F`
- 其余题型不要写 `options`

基础模板（单题）：

```yaml
id: your_question_id
type: short_answer
content: |-
  在此填写题干。
answer: |-
  在此填写答案。
analysis: |-
  在此填写解析（可留空）。
metadata:
  难度: 中等
  题型: 解答题
```

选择题模板：

```yaml
id: your_choice_question_id
type: choice
content: |-
  在此填写题干。
options:
  A: 选项A
  B: 选项B
  C: 选项C
  D: 选项D
answer: A
analysis: |-
  在此填写解析（可留空）。
metadata:
  难度: 中等
  题型: 选择题
```

判断题模板：

```yaml
id: your_judge_question_id
type: judge
content: |-
  在此填写题干。
answer: T
analysis: |-
  在此填写解析（可留空）。
metadata:
  难度: 中等
  题型: 判断题
```
