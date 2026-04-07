# PrimeBrush 教育绘图：语法说明与示例图

**PrimeBrush** 是本平台的**教育绘图**能力，用于在题目正文中插入**几何图、函数图像、统计图或化学结构示意图**。您在题干里用**代码围栏**（三个反引号）包住一段**按缩进书写的配置**即可。下面按「先总结构 → 平面几何每一步有哪些参数 → 函数图与统计图 → 化学结构式 → 配图示例」说明。

> **从旧版项目升级**：若题库或模板仍使用旧围栏或旧键名，请先按仓库内 [迁移说明](../../../docs/migrations/primebrush-rename.md) 运行一次性迁移脚本，再在本软件中打开项目。

---

## 一、总结构（`type` 一览）

围栏内正文须以 **`primebrush:`** 开头，并写明 **`type:`**：

| `type` | 用途 | 主要下级字段 |
|--------|------|----------------|
| `geometry_2d` | 平面几何 | `canvas`、`style`、`seed`、`constructions`（作图步骤列表） |
| `plot_2D` 或 `plot_2d` | 函数图像 | `canvas`、`style`、`seed`、`axes`、`elements` |
| `chart` | 统计图 | `canvas`、`style`、`seed`、`kind`、`data`、`options` |
| `chemistry_molecule` | 化学二维结构式 | `canvas`、`style`、`seed`、`notation`、`value` |

**各类型共用的根级字段（可选）：**

| 字段 | 含义 |
|------|------|
| `canvas` | 画布：`width`、`height`（像素常用数字即可）、`unit`（如 `px`） |
| `style` | 全局样式：如 `stroke_width`（线宽）、`font_family`、`font_size` |
| `seed` | 整数，**固定随机图**（如随机三角形）时，相同种子会画出相同形状 |

---

## 二、平面几何（`geometry_2d`）

用 **`constructions:`** 写**有序列表**，每一步是一个 `- op: …`。**后面的步骤可以引用前面已经定义的点名**（如先有 `A、B、C`，再写 `in_line` 得到 `M`）。

### 2.1 `triangle`（三角形）

| 参数 | 是否必填 | 说明 |
|------|----------|------|
| `op` | 必填 | 写 `triangle` |
| `nodes` | 必填 | 三个顶点名字，如 `[A, B, C]` |
| `attr` | 可选 | 目前支持 `type: random`（随机形状三角形），`min_angle`：最小角下限（**度**），避免三角形太扁 |
| `label` | 可选 | 顶点旁标注位置：对每个顶点写 `top`、`bottom_left`、`bottom_right` 等，控制字母不遮挡图形 |

### 2.2 `in_line`（直线上的点）

在由两点 `source` 决定的线段（延长线）上取参数为 `params` 的点。

| 参数 | 是否必填 | 说明 |
|------|----------|------|
| `op` | 必填 | `in_line` |
| `id` | 必填 | 新点的名字 |
| `source` | 必填 | `[P, Q]`，两点须已存在 |
| `params` | 可选 | 默认 `0.5` 为中点；`0` 在 `P` 处，`1` 在 `Q` 处；可小于 0 或大于 1 表示延长 |
| `label` | 可选 | 该点旁显示的文字 |

### 2.3 `line`（作图线段）

连接两个**已存在**的点。

| 参数 | 是否必填 | 说明 |
|------|----------|------|
| `op` | 必填 | `line` |
| `source` | 必填 | `[P, Q]` |
| `style` | 可选 | `solid`（实线）或 `dashed`（虚线） |
| `label` | 可选 | `text`：文字；`pos`：0～1，在线上标注的位置比例 |

### 2.4 `foot`（垂足）

| 参数 | 说明 |
|------|------|
| `id` | 垂足点名 |
| `point` | 垂线外的点 |
| `line` | 直线，由 `[A, B]` 两点确定 |

### 2.5 `reflection`（轴对称点）

| 参数 | 说明 |
|------|------|
| `id` | 对称点名字 |
| `point` | 原点 |
| `line` | 对称轴，由 `[A, B]` 确定 |

### 2.6 `perpendicular` / `parallel`（过一点作垂线 / 平行线）

在画布上画**足够长**的直线段（便于看见）。

| 参数 | 说明 |
|------|------|
| `through` | 经过的点 |
| `to` | `[A, B]`，表示与直线 AB 垂直或平行 |
| `style`、`label` | 同 `line` |

### 2.7 `intersection_lines`（两直线交点）

| 参数 | 说明 |
|------|------|
| `id` | 交点名字 |
| `line1`、`line2` | 各为 `[A, B]`、`[C, D]` |

两直线不能平行，否则无法求交点。

### 2.8 `intersection_line_circle`（直线与圆的交点）

| 参数 | 说明 |
|------|------|
| `id` | 交点名字 |
| `line` | `[A, B]` 直线 |
| `center` | 圆心点名（须已存在） |
| 半径 | **三选一**：`radius`（数值）、`through`（圆上一点）、`radius_from: [X, Y]`（半径 \|XY\|） |
| `which` | `0` 或 `1`：沿直线方向**两个交点**中取哪一个（先出现的为 0） |

### 2.9 `intersection_circles`（两圆交点）

| 参数 | 说明 |
|------|------|
| `circle1`、`circle2` | 各为圆描述：`center` + 半径三选一（`radius` / `through` / `radius_from`） |
| `ids` | 一个交点（相切）时写 `[P]`；两个交点写 `[P, Q]` |

### 2.10 `circle`（圆）

| 参数 | 说明 |
|------|------|
| `center` | 圆心点名 |
| 半径 | **三选一**：`radius`、`through`、`radius_from`（含义同上） |
| `style` | 如 `solid` |
| `fill` | 可选填色 |

### 2.11 `ellipse`（椭圆）

| 参数 | 说明 |
|------|------|
| `center` | 中心点 |
| `rx`、`ry` | 半轴长（像素） |
| `rotation_deg` 或 `rotate_deg` | 旋转角度（度） |
| `style`、`fill` | 可选 |

### 2.12 `perpendicular_bisector`（垂直平分线）

| 参数 | 说明 |
|------|------|
| `source` | `[A, B]` 线段 |
| `style`、`label` | 可选 |

### 2.13 `angle_bisector`（角平分线）

| 参数 | 说明 |
|------|------|
| `source` | `vertex: B`（角的顶点）、`arms: [A, C]`（角的两边上的点） |
| `style`、`label` | 可选 |

---

## 三、函数图像（`plot_2D`）

### 3.1 `axes`（坐标轴）

| 子字段 | 含义 |
|--------|------|
| `x`、`y` | 各自可有 `label`、`range: [最小, 最大]`、`ticks`（刻度**步长**数字；不写则自动取较整齐步长） |
| `grid` | `true` 时画背景网格 |

### 3.2 `elements`（曲线与点）

**曲线**：写 `f: "表达式"`，自变量为 **`x`**；可用 `sin(x)`、`x**2`、`x^2` 等；可选 `domain: [a, b]` 限制画图区间；可选 `color`、`width`、`style`（`solid`/`dotted`）、`label`。

**在曲线上取点**：一项写 `op: point_on_f`，并包含：

| 字段 | 说明 |
|------|------|
| `f_id` | 第几条曲线（从 **0** 开始数，只计含 `f:` 的项） |
| `x` | 该点横坐标 |
| `label` | 点旁标注 |
| `show_projection` | `true` 时画到两轴的虚线投影 |

---

## 四、统计图（`chart`）

| 字段 | 说明 |
|------|------|
| `kind` | `bar`（柱状）或 `line`（折线）等 |
| `theme` | 如 `academic`（偏灰阶印刷风） |
| `data` | 多行记录，每行至少 `label`、`value`；柱状可写 `error` 表示误差棒 |
| `options` | 如 `x_label`、`y_label`、`bar_width`、`show_value`、`show_error`、`y_range` |

---

## 五、化学二维结构式（`chemistry_molecule`）

用于按 **SMILES** 描述渲染常见有机分子骨架（需运行环境安装 **RDKit** 时方可输出完整结构图；未安装时界面会给出占位说明，不影响保存题目）。

| 字段 | 是否必填 | 说明 |
|------|----------|------|
| `notation` | 可选 | 目前请使用 `SMILES`（默认）。其它写法尚未接入渲染。 |
| `value` | 必填 | SMILES 字符串，例如乙醇可写 `CCO`。 |
| `canvas` | 可选 | 出图宽高，与其它图类型相同。 |

---

## 六、示例与效果图

以下示例与仓库内 **`examples/primebrush/`** 目录下的示例文件一致；图为本手册打包的示意图，**与题目中保存后生成的图**在细节上可能因种子略有差异，但**写法相同**。

**复制到题目里时**：请使用**代码围栏**，第一行三个反引号后写 **`primebrush`**；把下面代码块中的整段内容（从 `primebrush:` 到结束）粘贴到围栏内；不要照抄本页用于展示的 `text` 标记。

### 示例 1：三角形与中线（`geometry_2d`）

![三角形 ABC、AB 中点 M、中线 CM](/api/help/asset/primebrush/median_line.svg)

```text
primebrush:
  type: geometry_2d
  seed: 42
  canvas: { width: 400, height: 300, unit: px }
  style:
    stroke_width: 1.2
    font_family: sans-serif

  constructions:
    - op: triangle
      id: T1
      nodes: [A, B, C]
      attr: { type: random, min_angle: 30 }
      label:
        A: top
        B: bottom_left
        C: bottom_right

    - op: in_line
      id: M
      source: [A, B]
      params: 0.5
      label: "M"

    - op: line
      id: L1
      source: [C, M]
      style: dashed
      label: { text: "中线", pos: 0.5 }
```

### 示例 2：中垂线、角平分线、圆与椭圆（`geometry_2d`）

![中垂线、角平分线、圆、椭圆](/api/help/asset/primebrush/advanced_ops.svg)

```text
primebrush:
  type: geometry_2d
  seed: 42
  canvas: { width: 520, height: 380, unit: px }
  style:
    stroke_width: 1.1
    font_family: sans-serif

  constructions:
    - op: triangle
      id: T1
      nodes: [A, B, C]
      attr: { type: random, min_angle: 35 }
      label:
        A: top
        B: bottom_left
        C: bottom_right

    - op: in_line
      id: O
      source: [A, C]
      params: 0.5

    - op: perpendicular_bisector
      id: pb_AB
      source: [A, B]
      style: dashed
      label: { text: "中垂线", pos: 0.35 }

    - op: angle_bisector
      id: bis_B
      source: { vertex: B, arms: [A, C] }
      style: dashed
      label: { text: "角平分线", pos: 0.55 }

    - op: circle
      id: c1
      center: O
      through: B
      style: solid

    - op: ellipse
      id: e1
      center: A
      rx: 55
      ry: 32
      rotation_deg: 18
      style: solid
```

### 示例 3：正弦曲线与抛物线、曲线上取点（`plot_2D`）

![sin(x)、抛物线与点 P 的投影](/api/help/asset/primebrush/sin_and_point.svg)

```text
primebrush:
  type: plot_2D
  seed: 42
  canvas: { width: 480, height: 360, unit: px }
  style:
    font_size: 11

  axes:
    x: { label: "x", range: [-5, 5], ticks: 1 }
    y: { label: "y", range: [-2, 2], ticks: 0.5, arrows: true }
    grid: true

  elements:
    - f: "sin(x)"
      domain: [-3.14, 3.14]
      color: "#1a5fb4"
      width: 2
      label: "sin"

    - f: "x**2 - 1"
      color: "#c01c28"
      style: dotted

    - op: point_on_f
      f_id: 0
      x: 1.57
      label: "P"
      show_projection: true
```

### 示例 4：柱状图与误差棒（`chart`）

![各班平均分柱状图与误差棒](/api/help/asset/primebrush/bar_scores.svg)

```text
primebrush:
  type: chart
  seed: 42
  canvas: { width: 420, height: 280, unit: px }
  style:
    font_family: sans-serif

  kind: bar
  theme: academic
  data:
    - { label: "一班", value: 85, error: 5 }
    - { label: "二班", value: 92, error: 3 }
    - { label: "三班", value: 78, error: 8 }
  options:
    x_label: "班级"
    y_label: "平均分"
    bar_width: 0.6
    show_value: true
    show_error: true
    y_range: [0, 100]
```

### 示例 5：化学结构式（`chemistry_molecule`，SMILES）

```text
primebrush:
  type: chemistry_molecule
  canvas: { width: 320, height: 240, unit: px }
  notation: SMILES
  value: "CCO"
```

---

## 七、常见问题

| 现象 | 建议 |
|------|------|
| 提示未知 `op` | 检查 `op` 英文拼写与缩进（同一步骤下的字段应比 `- op` 多缩进）。 |
| 提示某点不存在 | 作图步骤**顺序**要对：先定义点，再在后续步骤里引用。 |
| 求交点失败 | 检查两直线是否平行、线圆/两圆是否真的相交。 |
| 随机三角形每次不同 | 属正常；若希望可复现，固定 **`seed`**。 |
| 化学图只有文字占位 | 多为未安装 RDKit 或 SMILES 无法识别；请检查 `value` 是否为合法 SMILES，或联系管理员确认运行环境。 |

更多尺规组合示例（垂足、平行、两圆交等）可参考仓库内 **`examples/primebrush/geometry_2d/ruler_compass.yaml`**。若需在开发机上把单份图稿编译成 SVG，可执行 `python -m solaire.primebrush.cli build <文件.yaml>`（YAML 顶层须为 `primebrush:`）。命令行亦提供 `primebrush build <文件.yaml>`（见 `pyproject.toml` 中的入口配置）。
