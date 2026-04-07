---
name: create_question_yaml
description: >
  按题库单题规范起草并写入题目（新建或更新），依赖服务端校验。当教师提到新建题目、
  录入题目、按规范出题、改题干选项等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.1"
  label: 按规范创建题目
  tool_patterns: "bank.create_item bank.update_item bank.get_item bank.search_items file.read agent.read_skill_reference memory.* agent.*"
  suggested_user_input: 请帮我按题库规范创建一道新题，并确保格式校验通过。
---

## 工作流程

1. 按字段组织单题正文（字段清单与样例见 `agent.read_skill_reference`，`name`=`create_question_yaml`，`path`=`references/yaml-template.md`）
2. 需要参照现有题时可用 `bank.get_item` 或 `file.read` 读取项目内 YAML
3. 新建调用 `bank.create_item`；改题调用 `bank.update_item`
4. 校验失败时根据返回信息逐项修正，避免猜测合法取值

## 题型与规则（摘要）

- `type`：`choice` / `fill` / `judge` / `short_answer` / `reasoning` / `essay`
- 仅 `choice` 可有 `options`；`judge` 的 `answer` 仅为 `T` 或 `F`

## 参考文件

- `references/yaml-template.md`：可复制粘贴的 YAML 骨架（用 `agent.read_skill_reference` 读取，勿用 `file.read` 访问技能包路径）

## 注意事项

- 题干中若含教育绘图围栏（PrimeBrush），勿手写非法 `op`；复杂图稿可切换 `primebrush_diagrams` 技能并对照其 `references/`

