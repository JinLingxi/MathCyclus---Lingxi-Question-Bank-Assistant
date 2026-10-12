# 维护脚本目录

> 最近同步：2026-09-24。本文档只说明脚本职责和运行边界，不替代脚本自身的 `--help`。
> 不确定的脚本保留，不因为“没有被主程序 import”就删除；很多脚本是人工维护、迁移或发布入口。

## 使用规则

1. 先确认目标数据库、输出目录和备份位置，再运行脚本。
2. `audit_*.py`、`check_*.py`、`diff_*.py`、`review_*.py`、`generate_*.py` 默认用于只读审计或生成报告；仍应先看参数说明。
3. `smoke_*.py` 是回归检查，不是数据清洗工具。除临时测试库外，不应把它当作写库入口。
4. 文件名包含 `dry_run` 的脚本只生成预览或复核结果；确认结果后才进入对应的写入脚本。
5. `apply_*.py`、`merge_*.py`、`delete_*.py`、`split_*.py`、`normalize_*.py` 和 `sync_*.py` 可能改变数据或旧 TeX，运行前必须备份并保留审计报告。

## A. 长期维护与发布入口

这些脚本属于当前项目的持续维护接口，应随源码保留：

`backup_database.py`、`browse_question_db.py`、`build_combined_preview_db.py`、
`build_source_release_package.py`、`check_project_hygiene.py`、
`create_pdf_import_job.py`、`diff_preview_databases.py`、`export_db_to_tex.py`、
`export_relation_summary.py`、`init_local_workspace.py`、`local_data_bundle.py`、
`migrate_schema.py`、`precommit_database_audit.py`、
`promote_preview_to_database.py`、`rebuild_preview_pipeline.py`、
`scan_tex_library.py`、`update_local_installation.py`。

其中 `promote_preview_to_database.py` 虽然是长期入口，但属于正式写库操作，不能当作普通检查脚本运行。

## B. 只读审计脚本

以下脚本用于发现问题、输出报告或检查 Git/数据边界，默认不应修改正式题库：

- `audit_*.py`
- `check_project_hygiene.py`
- `diff_preview_databases.py`
- `review_equivalence_decisions.py`
- `review_paper_mapping.py`
- `generate_data_warning_review_pack.py`
- `generate_equivalence_review_pack.py`
- `generate_paper_name_mapping.py`
- `export_relation_summary.py`

审计报告通常写入 `reports/`，该目录属于本地生成物，不应提交到 Git。

## C. Smoke 与发布回归脚本


Smoke 脚本的判断原则是：优先使用临时目录或临时数据库，检查正式数据库内容不变；如果某个 smoke 需要真实数据，应在脚本说明中明确写出。

## D. 预览、迁移和人工确认脚本

这些脚本不是废弃代码，但不应加入普通启动流程：

- `*_dry_run.py`，以及 `commit_import_drafts_dry_run.py`、`migrate_assets_dry_run.py`、`migrate_tex_to_db_dry_run.py`：生成迁移或导入预览。
- `import_book_json_dry_run.py`、`import_draft_json_dry_run.py`、`import_topic_json_dry_run.py`：检查结构化数据导入内容。
- `apply_data_warning_review_dry_run.py`、`apply_equivalence_review_dry_run.py`、`apply_paper_name_mapping_dry_run.py`、`apply_paper_question_corrections_dry_run.py`：根据人工确认清单生成下一步动作预览。

这类脚本的正确顺序是“备份 → dry-run/报告 → 人工确认 → 写入脚本 → 再审计”，不能直接批量执行。

## E. 已发生数据整理的手工脚本

以下脚本可能是某轮数据清洗留下的人工维护入口，暂时保留，但不应重复运行：

`apply_confirmed_asset_references.py`、`apply_confirmed_cleanup_decisions.py`、
`apply_confirmed_track_corrections.py`、`apply_explicit_paper_naming_decisions.py`、
`apply_g_paper_review.py`、`apply_tex_metadata_sync.py`、
`delete_questions_with_backup.py`、`mark_confirmed_question_variant.py`、
`merge_confirmed_questions.py`、`normalize_question_choices_json.py`、
`remove_redundant_tikz_asset_reference.py`、`split_shared_track_questions.py`、
`split_track_review_papers.py`、`sync_legacy_source_from_paper_relation.py`。

这些脚本的存在不代表仍有待执行任务。是否再次运行必须以新的审计报告和人工决策为准；尤其是删除、合并、拆分和旧 TeX 同步操作，不能因为脚本仍在目录中就重复执行。

## 后续维护约定

- 新增长期入口时，同时在本文档补充职责和是否写库。
- 新增一次性数据脚本时，文件名优先包含 `dry_run` 或 `review`，并在脚本帮助中写明输入、输出和回滚方式。
- 脚本失去用途时先标记为历史脚本并保留一个版本周期，确认没有回滚或审计价值后再删除。
