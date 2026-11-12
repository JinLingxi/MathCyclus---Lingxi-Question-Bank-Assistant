# 规划索引

> 这里存放数据库重构、迁移、发布、导入、清洗相关的长期规划与沉淀文档。  
> 当前真正要执行的事项以 `unfinished_tasks.md` 为准；长文档用于追溯设计依据和阶段记录。

## 主文档

- `../ai/README.md`：AI、队友和自动化工具的任务路由与当前硬规则入口。
- `题库数据库重构实施规划.md`：数据库重构主规划与阶段执行记录。
- `题库重构参考沉淀.md`：外部题库系统、AI 录入方式和数据库设计参考。
- `unfinished_tasks.md`：当前未完成事项、优先级和下一步入口。

## 专项规划

- `ai_ocr_draft_import_flow.md`：AI/OCR 草稿识别与确认入库流程。
- `pdf_import_pipeline.md`：PDF 导入、截图、切题和草稿生成路线。
- `data_cleanup_and_naming_plan.md`：旧题库数据清洗、重复题复核、试卷命名和文理标注规范。
- `paper_name_normalization.md`：试卷命名标准化规则、文理 track 规则、重复题治理原则。
- `paper_catalog_and_ingestion_flow.md`：卷目录主表、别名表和录入确认流程草案。
- `local_workspace_and_migration.md`：本地工作区初始化、迁移包和私有数据边界。
- `release_file_checklist.md`：发布前文件白名单、黑名单和私有数据检查。
- `maintenance_script_catalog.md`：维护、审计、smoke、迁移和一次性清洗脚本的职责边界。
- `version_update_and_installer.md`：版本更新、启动器和安装包边界。
- `schema_migration_flow.md`：SQLite schema 迁移流程。
- `sqlite_promotion_flow.md`：预览库提升为正式库流程。
- `question_id_rules.md`：题目 ID 规则。
- `database_schema_notes.md`：当前 SQLite schema 表职责说明。

## 当前推进顺序

以 [2026-11-06 状态复核](../ai/local-data-boundaries-and-status.md) 和 `unfinished_tasks.md` 顶部为当前入口；旧章节中的题量和验收结论是历史快照。

1. 录题任务保持独立批次和输出目录；正式提交协调执行，不宣称并行提交已验收。
2. 草稿图片、PDF 来源、备份/源码阶段归档和任务打包的基础治理已完成，原路径按引用及恢复需要保留。
3. 继续验证跨机器绝对路径迁移、完整任务恢复、持续录题后的数据质量及当前版本发布回归。
4. 复杂扫描裁剪、相似度评估和可选模板增强按实际需要推进，不重复执行历史数据清洗。

## 常用只读审计入口

```powershell
.\.venv\Scripts\python.exe scripts\audit_data_cleanup_candidates.py --db data\mathcyclus.sqlite3 --stamp latest
.\.venv\Scripts\python.exe scripts\audit_paper_naming_standard.py --db data\mathcyclus.sqlite3 --stamp latest
.\.venv\Scripts\python.exe scripts\precommit_database_audit.py --db data\mathcyclus.sqlite3 --stamp latest
```
