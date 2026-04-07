# PrimeBrush 示例

声明式 YAML → `primebrush build` → 同目录同名 `.svg`。

## 案例

| 目录 | 说明 |
|------|------|
| `geometry_2d/median_line.yaml` | 三角形 + AB 中点 M + 中线 CM |
| `geometry_2d/advanced_ops.yaml` | 中垂线、角平分线、圆、椭圆 |
| `geometry_2d/ruler_compass.yaml` | 垂足、平行/垂直、两线交、线圆交、两圆交、对称点、`radius_from` |
| `plot_2d/sin_and_point.yaml` | sin 与抛物线、`point_on_f` 投影 |
| `chart/bar_scores.yaml` | 学术主题柱状图 + 误差棒 |

## 复现

在项目根目录（已 `pip install -e ".[dev]"`）：

```bash
primebrush build examples/primebrush/geometry_2d/median_line.yaml
primebrush build examples/primebrush/geometry_2d/advanced_ops.yaml
primebrush build examples/primebrush/plot_2d/sin_and_point.yaml
primebrush build examples/primebrush/chart/bar_scores.yaml
```

默认在同目录生成同名 `.svg`。可用 `--seed` 覆盖随机种子。

若需查阅早期设计备忘，见仓库 `doc_useless/` 下归档文稿（不作为产品交付物维护）。
