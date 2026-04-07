# 自定义分析脚本教程（函数入口 + 图形对象）

这篇文档专门回答：**如何用最少代码完成自定义数据处理，并直接产出结果图表**。

## 1. 你能直接用的脚本能力

脚本运行时系统会自动提供以下能力：

- `get_rawdata()`：获取本次考试/批次的结构化结果数据
- `get_graph()`：获取本次分析相关的知识图谱子集
- `HistogramChart(title=..., data=...)`：输出直方图
- `PieChart(title=..., data=...)`：输出扇形图

你只需要写分析逻辑，最后把结果放到 `RESULT`。

可选返回方式：

- `RESULT = HistogramChart(...)` 或 `RESULT = PieChart(...)`
- `RESULT = {...}`（结构化结果）

## 2. 最小可运行示例（推荐起步）

```python
raw = get_rawdata()

RESULT = HistogramChart(
    title="学生人数示例",
    data=[{"label": "人数", "value": raw.get("student_count", 0)}],
)
```

## 3. 数据结构（全字段）

`raw = get_rawdata()` 返回对象字段如下：

- `exam_id: str`，考试标识
- `batch_id: str`，批次标识
- `student_count: int`，参与统计学生数
- `question_count: int`，试题数量
- `imported_at: str`，导入时间（部分场景可能不存在）
- `class_avg_ratio: float`，班级平均得分率
- `class_avg_fuzzy: float`，班级平均掌握度
- `warnings: list[dict]`，告警列表，每项字段：
  - `question_id: str`
  - `header: str`
  - `section_id: str`
  - `message: str`
- `question_stats: list[dict]`，每题统计列表，每项字段：
  - `question_id: str`
  - `header: str`
  - `section_id: str`
  - `score_per_item: float`
  - `answered_count: int`
  - `error_rate: float`
  - `avg_score_ratio: float`
  - `avg_raw_score: float`
  - `first_csv_raw: float`
- `node_stats: list[dict]`，知识点统计列表，每项字段：
  - `node_id: str`
  - `bound_question_count: int`
  - `bound_questions: list[str]`
  - `mastery_fuzzy: float`
  - `error_rate: float`
- `student_stats: list[dict]`，学生统计列表，每项字段：
  - `name: str`
  - `student_id: str`
  - `raw_total: float`
  - `score_ratio: float`
  - `fuzzy_score: float`
  - `rank: int`
  - `class_rank: int`
  - `total_in_class: int`

`kg = get_graph()` 返回对象字段如下：

- `nodes: list[dict]`，每项字段：
  - `id: str`
- `edges: list[dict]`，每项字段：
  - `from: str`
  - `to: str`
  - `type: str`（当前为 `part_of`）

说明：`get_graph()` 返回的是“本次分析相关子图”，不是全量图谱。

## 4. 图形对象输入要求

两种图都使用同一种数据格式：

```python
[
  {"label": "显示名称", "value": 数值},
  ...
]
```

## 5. 真实脚本案例（仓库内可直接参考）

位于 `analysis/examples/`：

- `error_rate_histogram.py`：题目错误率直方图
- `node_error_pie.py`：知识点错误率扇形图
- `student_band_histogram.py`：学生分层直方图
- `default_exam_stats_rewrite.py`：默认统计重写示例

## 6. 兼容说明

- 推荐写法：`RESULT = HistogramChart(...)` 或 `RESULT = PieChart(...)`
- 兼容写法：`RESULT = {...}`（结构化结果）

## 7. 在工作区如何使用

1. 把脚本放到项目的 `analysis/` 目录。  
2. 在分析工作区右侧选择脚本并运行。  
3. 结果会在中间结果区显示；图表区可下载结果数据与图片。

## 8. 常见错误与处理

- `timeout`：脚本执行超时，减少循环与计算量
- `resource_exceeded`：输出或资源超限，减少大体量打印与中间结果
- `sandbox_violation`：使用了受限能力（如不允许导入）
- `runtime_error`：脚本自身错误（变量/类型等）

## 9. 实用建议

- 先从最小示例跑通，再逐步添加逻辑
- 每次只改一小段，便于定位问题
- 优先使用 `analysis/examples/` 里的脚本做二次修改
