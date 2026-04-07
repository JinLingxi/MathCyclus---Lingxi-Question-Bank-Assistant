# PrimeBrush：完整示例与排错

以下围栏内正文均以 `primebrush:` 为例。

## 平面几何：三角形与中线

```yaml
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

## 平面几何：中垂线、角平分线、圆、椭圆

```yaml
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

## 函数图

```yaml
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

## 柱状图

```yaml
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

## 化学结构式（SMILES）

```yaml
primebrush:
  type: chemistry_molecule
  canvas: { width: 320, height: 240, unit: px }
  notation: SMILES
  value: "CCO"
```

## 常见问题

| 现象 | 处理 |
|------|------|
| 未知 `op` | 核对英文拼写与 YAML 缩进 |
| 点不存在 | 调整 `constructions` 顺序，先定义后引用 |
| 求交失败 | 检查平行、相离等几何条件 |
| 随机图每次不同 | 固定 `seed` |
| 化学图为占位 | 校验 SMILES；或确认运行环境是否具备 RDKit |

## 离线编译 SVG（开发用）

```bash
python -m solaire.primebrush.cli build path/to/file.yaml
```

**注意**：该 CLI 要求 YAML **顶层键为 `primebrush:`**（与 `python -m solaire.primebrush.cli` 一致）。
