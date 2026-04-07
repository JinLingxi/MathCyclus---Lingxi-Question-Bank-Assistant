---
name: primebrush_diagrams
description: >
  在题目正文或解析中编写 PrimeBrush 教育绘图（平面几何、函数图、统计图、化学结构式），
  使用 `` ```primebrush `` 围栏与 `primebrush:` 根键。当教师提到画图、插图、几何作图、
  函数图像、统计柱状图、SMILES、结构式等关键词时激活此技能。
metadata:
  author: solaire-builtin
  version: "1.0"
  label: PrimeBrush 绘图协助
  tool_patterns: "bank.get_item bank.update_item bank.search_items file.read file.edit agent.read_skill_reference memory.* agent.*"
  suggested_user_input: 请帮我在题干里加一幅平面几何图，用 PrimeBrush 写法并保证能编译。
---

## 概念

- **PrimeBrush**：声明式 YAML → SVG，嵌入题面时使用**代码围栏**包裹一段缩进 YAML。
- **围栏标签**：第一行写 `` ```primebrush ``。
- **根节点**：围栏内顶层键为 `primebrush:`。
- **`type` 字段**决定图类：已实现 `geometry_2d`、`plot_2D`/`plot_2d`、`chart`、`chemistry_molecule`；其它类型可能尚未实现。
- 几何类依赖 **`constructions`** 步骤列表，**步骤顺序**决定点名是否已定义；需要可复现的随机图时设 **`seed`**。

## 参考索引（具体语法与示例）

参考文件在**技能包内**，不在教师项目目录中。请用 **`agent.read_skill_reference`**：`name` 填 `primebrush_diagrams`，`path` 填下表中的相对路径（勿用 `file.read` 拼 `src/solaire/...` 仓库路径）。

| path（相对技能根目录） | 内容 |
|------------------------|------|
| `references/overview.md` | 围栏约定、共用字段、`type` 总表 |
| `references/geometry-2d.md` | 尺规作图 `op` 参数表 |
| `references/plot-chart-chemistry.md` | 函数图、统计图、化学结构式 |
| `references/examples-and-troubleshooting.md` | 完整 YAML 样例与常见问题 |

产品侧说明文档（若已部署）：仓库内 `src/solaire_doc/user/primebrush.md`（仅供人类维护，模型以本技能 references 为准）。

## 工作流程

1. 确认题型与插图位置（`content` / `analysis` / 题组材料等）。
2. 用 `agent.read_skill_reference` 打开上表对应文件，**逐字段**抄写结构；几何题先列点再连线。
3. 写入题目：优先 `bank.update_item` 带完整题干；或配合 `file.edit` 修改题库 YAML（路径须在项目内）。
4. 若教师需要组卷验证，提醒使用 `exam.validate_paper`（见 `smart_compose` 技能）。

## 注意事项

- `op` 名、缩进错误会导致渲染失败；勿臆造未在 reference 中出现的 `op`。
- 化学图需合法 **SMILES**；服务端未装 RDKit 时可能仅显示占位图，但仍可保存题目。
- 与 **Mermaid 流程图**可同题混用，顺序与书写顺序一致。
