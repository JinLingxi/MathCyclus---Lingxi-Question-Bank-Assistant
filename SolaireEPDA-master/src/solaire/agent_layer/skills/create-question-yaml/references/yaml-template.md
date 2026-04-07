# 题目模板参考

## 基础模板（单题）

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

## 选择题模板

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

## 判断题模板

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

## 注意

- `type` 仅可为：`choice` / `fill` / `judge` / `short_answer` / `reasoning` / `essay`
- 仅 `choice` 题允许 `options`
- `judge` 题 `answer` 仅可为 `T` 或 `F`
- 其余题型不要写 `options`
