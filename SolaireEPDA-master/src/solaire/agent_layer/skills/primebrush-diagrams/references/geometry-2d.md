# PrimeBrush：`geometry_2d` 尺规作图

用 **`constructions:`** 有序列表描述步骤，每项 `- op: ...`。后序步骤可引用先前步骤定义的点名。

## `triangle`

| 参数 | 必填 | 说明 |
|------|------|------|
| `op` | 是 | `triangle` |
| `nodes` | 是 | 三顶点名，如 `[A, B, C]` |
| `attr` | 否 | 如 `type: random`、`min_angle`（度，防过扁） |
| `label` | 否 | 顶点标注方位：`top`、`bottom_left`、`bottom_right` 等 |

## `in_line`

线段（可延长）上取点：`source: [P, Q]`；`params` 默认 `0.5` 为中点。

## `line`

`source: [P, Q]`；可选 `style: solid|dashed`，`label: { text, pos }`。

## `foot`

垂足：`id`、`point`、`line: [A, B]`。

## `reflection`

轴对称点：`id`、`point`、`line: [A, B]`。

## `perpendicular` / `parallel`

过 `through` 且与直线 `[A,B]`（`to`）垂直或平行；`style`、`label` 同 `line`。

## `intersection_lines`

`id`、`line1`、`line2` 各为 `[A,B]`、`[C,D]`；两线不可平行。

## `intersection_line_circle`

`id`、`line: [A,B]`、`center`；半径三选一：`radius` / `through` / `radius_from: [X,Y]`；`which: 0|1` 选交点。

## `intersection_circles`

`circle1` / `circle2`（各含 `center` 与半径三选一）；`ids: [P]` 或 `[P,Q]`。

## `circle` / `ellipse`

圆：`center` + 半径三选一。椭圆：`center`、`rx`、`ry`、`rotation_deg` 或 `rotate_deg`；可选 `style`、`fill`。

## `perpendicular_bisector`

`source: [A, B]`；可选 `style`、`label`。

## `angle_bisector`

`source: { vertex: B, arms: [A, C] }`；可选 `style`、`label`。

更多组合示例见仓库 `examples/primebrush/geometry_2d/ruler_compass.yaml`。
