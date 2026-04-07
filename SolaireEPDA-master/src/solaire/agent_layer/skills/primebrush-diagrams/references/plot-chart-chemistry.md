# PrimeBrush：`plot_2D`、`chart`、`chemistry_molecule`

## `plot_2D` — 坐标轴 `axes`

| 子字段 | 含义 |
|--------|------|
| `x`、`y` | 可有 `label`、`range: [min, max]`、`ticks`（步长） |
| `grid` | `true` 画背景网格 |

## `plot_2D` — 曲线与点 `elements`

- **曲线项**：`f: "表达式"`（自变量 **`x`**），可用 `sin(x)`、`x**2`、`x^2` 等；可选 `domain`、`color`、`width`、`style`（`solid`/`dotted`）、`label`。
- **曲线上点**：`op: point_on_f`，含 `f_id`（从 0 起，只计含 `f:` 的项）、`x`、`label`，可选 `show_projection: true`。

## `chart`

| 字段 | 说明 |
|------|------|
| `kind` | 如 `bar`、`line` |
| `theme` | 如 `academic` |
| `data` | 多行，常含 `label`、`value`；柱状可加 `error` |
| `options` | 如 `x_label`、`y_label`、`bar_width`、`show_value`、`show_error`、`y_range` |

## `chemistry_molecule`

| 字段 | 必填 | 说明 |
|------|------|------|
| `notation` | 否 | 使用 `SMILES`（默认）；其它写法若未接入则仅占位 |
| `value` | 是 | SMILES 字符串，如乙醇 `CCO` |
| `canvas` | 否 | 出图区域，与其它类型相同 |

完整 YAML 片段见 `examples-and-troubleshooting.md`。
