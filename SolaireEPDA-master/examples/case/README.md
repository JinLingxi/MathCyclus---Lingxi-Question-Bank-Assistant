# 综合练习案例（合成题库）

本目录为**自编合成题**，用于演示完整试卷结构（选择题 12 + 填空 4 + 计算/证明 5）。

## 文件说明

| 文件 | 说明 |
|------|------|
| `exam.yaml` | 试卷实例：选题、模板引用、`question_libraries` |
| `template.yaml` | 试卷蓝图：各题型数量与分值 |
| `bank/questions.yaml` | 题库（原 `library.yaml` 已合并至此） |

## 编译

在仓库根目录执行：

```bash
python -m solaire.exam_compiler.cli build examples/case/exam.yaml -v
```

或使用 Docker（见仓库根目录 `README.md`）。

生成的 PDF 默认在 `examples/case/`；中间文件在 `examples/case/exam/`。

## 题型说明

- `choice` / `fill` / `short_answer` / `essay`：与 PRD 枚举一致。
- `reasoning`：推理（含计算与证明），渲染方式与简答/论述类似（无 A–D 选项），在教师版展示多行答案与解析。
