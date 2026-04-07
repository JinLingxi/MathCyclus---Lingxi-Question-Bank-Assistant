# PrimeBrush：围栏与类型总览

## 围栏写法

- 开头一行：`` ```primebrush ``
- 正文：YAML，顶层键 **`primebrush:`**

## `type` 一览

| `type` | 用途 | 主要下级字段 |
|--------|------|----------------|
| `geometry_2d` | 平面几何 | `canvas`、`style`、`seed`、`constructions` |
| `plot_2D` / `plot_2d` | 函数图像 | `canvas`、`style`、`seed`、`axes`、`elements` |
| `chart` | 统计图 | `canvas`、`style`、`seed`、`kind`、`data`、`options` |
| `chemistry_molecule` | 化学二维结构式 | `canvas`、`style`、`seed`、`notation`、`value` |

## 各类型共用根级字段（可选）

| 字段 | 含义 |
|------|------|
| `canvas` | `width`、`height`、`unit`（如 `px`） |
| `style` | 如 `stroke_width`、`font_family`、`font_size` |
| `seed` | 整数；固定随机几何形状时使用 |

详见：`geometry-2d.md`、`plot-chart-chemistry.md`、`examples-and-troubleshooting.md`。
