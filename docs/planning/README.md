# 规划索引

> 这里存放数据库重构、迁移、发布、导入、清洗相关的长期规划与沉淀文档。  
> 当前真正要执行的事项以 `unfinished_tasks.md` 为准；长文档用于追溯设计依据和阶段记录。

## 主文档

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
- `version_update_and_installer.md`：版本更新、启动器和安装包边界。
- `schema_migration_flow.md`：SQLite schema 迁移流程。
- `sqlite_promotion_flow.md`：预览库提升为正式库流程。
- `question_id_rules.md`：题目 ID 规则。
- `database_schema_notes.md`：当前 SQLite schema 表职责说明。

## 当前推进顺序

1. P0 稳定性复核已完成：2026-09-11 发布前检查 `failed=0`，保留两项非阻断 warning。
2. PDF 导入 P0-P3 可用首版已完成；下一步补页面区域裁剪、题内图片命名与排序的 P3.1。
3. P2 继续补强题目、试卷、教材、专题、图片资源、修订记录之间的双向关系。
4. P2 数据清洗已进入来源命名阶段：先用只读审计报告确认试卷标准名、文理 track 和重复题治理策略，再批量写库。
5. P3 继续完善白名单源码包、更新助手、迁移包和未来安装包边界。

## 常用只读审计入口

```powershell
.\.venv\Scripts\python.exe scripts\audit_data_cleanup_candidates.py --db data\mathcyclus.sqlite3 --stamp latest
.\.venv\Scripts\python.exe scripts\audit_paper_naming_standard.py --db data\mathcyclus.sqlite3 --stamp latest
.\.venv\Scripts\python.exe scripts\precommit_database_audit.py --db data\mathcyclus.sqlite3 --stamp latest
```
