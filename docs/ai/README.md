# MathCyclus AI 工作规范入口

> 当前版本：2026-09-24。本文档目录是给 AI、队友和自动化工具使用的“先读什么”入口，不替代代码和数据库 schema。
> 规则冲突时，以当前代码、`db/schema.sql`、正式迁移文件和本目录的硬规则为准；历史日志只用于追溯，不作为现行规则。

## 使用方式

开始任何开发、录题、数据清洗或发布任务前：

1. 先读本文档和 `hard-rules.md`。
2. 再按任务类型读下表中的专项文档。
3. 修改前检查 `docs/planning/unfinished_tasks.md`，确认事项是当前待办还是历史记录。
4. 修改后运行与任务风险相匹配的 smoke 或发布检查，并在交付时说明未验证的部分。

## 任务与必读文档

| 任务 | 必读文档 | 交付前检查 |
| --- | --- | --- |
| 任何代码、UI、服务层修改 | [hard-rules.md](hard-rules.md)、[task-roadmap.md](task-roadmap.md) | 保留现有数据流；运行相关 smoke |
| 单题、批量、同卷、同书录入 | [question-entry-workflow.md](question-entry-workflow.md)、[tex-and-assets.md](tex-and-assets.md) | 草稿审核、来源关系、重复题和图片资源 |
| PDF/图片识别、MinerU、OCR | [question-entry-workflow.md](question-entry-workflow.md)、[tex-and-assets.md](tex-and-assets.md) | 页面切分、图片绑定、失败重试、人工复核 |
| 试卷来源、题目关系、重复题 | [database-and-source-model.md](database-and-source-model.md)、[task-roadmap.md](task-roadmap.md) | 区分来源位置冲突、完全相同、相似和变式 |
| TeX、答案、解析、图片引用 | [tex-and-assets.md](tex-and-assets.md) | 预览、花括号、choices、questionasset、TikZ |
| 数据库、迁移、批量清洗 | [database-and-source-model.md](database-and-source-model.md)、[维护脚本目录](../planning/maintenance_script_catalog.md) | 备份、dry-run、审计、可回滚 |
| GitHub 同步、部署、安装包 | [hard-rules.md](hard-rules.md)、[发布文件清单](../planning/release_file_checklist.md) | 私有数据隔离、白名单发布包、依赖检查 |
| 后续功能规划 | [task-roadmap.md](task-roadmap.md)、[当前未完成事项](../planning/unfinished_tasks.md) | 不把历史规划误当成当前未完成项 |

## 可直接套用的任务模板

- PDF / 图片识别：[task-templates/pdf-import.md](task-templates/pdf-import.md)
- 批量题目录入：[task-templates/question-entry.md](task-templates/question-entry.md)
- 数据清洗：[task-templates/data-cleanup.md](task-templates/data-cleanup.md)
- 发布与部署：[task-templates/release-and-deployment.md](task-templates/release-and-deployment.md)

开始实际开发前，先选择一个模板，并在任务记录中补充本次输入范围、验收结果和未完成项。

## 当前权威来源

- 题目 OCR/TeX 输出细则：[ocr_prompt.txt](../../ocr_prompt.txt)。
- 当前数据库结构：[db/schema.sql](../../db/schema.sql) 与 [db/migrations](../../db/migrations)。
- 当前任务状态：[unfinished_tasks.md](../planning/unfinished_tasks.md)。
- 历史实施过程：[docs/logs](../logs) 和 [数据库重构实施规划](../planning/题库数据库重构实施规划.md)。
- 运行脚本边界：[maintenance_script_catalog.md](../planning/maintenance_script_catalog.md)。
- 发布与私有数据边界：[release_file_checklist.md](../planning/release_file_checklist.md)。

## 不应放入本目录的内容

- API Key、个人路径、真实题库内容、PDF、题目图片和数据库数据。
- 每次运行产生的报告、日志和临时任务文件。
- 尚未确认的个人偏好，或只适用于某一次数据清洗的决定。
