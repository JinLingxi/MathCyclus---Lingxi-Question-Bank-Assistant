# 维护脚本使用索引

本目录同时包含日常运维、只读审计、自动化回归和历史录题脚本。脚本不应仅凭文件名执行；有些历史脚本会在导入模块时直接写文件或访问数据库。

2026-11-13 同步筛查：具体年份、教材、批次的本地维护脚本通过本目录 `.gitignore` 的精确文件名清单排除，原文件保留原路径。应用和测试需要的依赖、通用维护工具、回归脚本继续纳入源码；不要通过 `git add -f` 将本地任务材料一起上传。具体录题交付记录同样由 `docs/ai/.gitignore` 排除。本地完整筛查与缓存删除清单见 `reports/*20261113*.json`，这些报告不上传。

## 推荐入口

| 用途 | 入口 | 执行边界 |
| --- | --- | --- |
| 工作区体积与重复来源盘点 | audit_workspace_cleanup.py | 只读盘点；不删除业务文件 |
| 录题目录引用审查 | audit_ingestion_references.py --output 新报告路径 | 覆盖库内 JSON 与项目文本；未发现静态引用也不授权删除 |
| 图片与任务文件完整性 | python -m scripts.audit_resource_integrity --output 新报告路径 | 只读检查题目资源、草稿、来源 PDF、截图和裁剪图；不自动修复 |
| 整理后资源验收 | python -m scripts.audit_resource_integrity --check-readability --baseline 基线JSON --output 新报告路径 | 同范围重查并逐项比较；基线保留，新增问题或范围缩小不算通过 |
| 备份盘点与保留建议 | audit_backup_retention.py --output 新报告路径 | 不改数据库；不因重复或时间较久就判可删 |
| 脚本分类和静态引用 | catalog_maintenance_scripts.py --output 新报告路径 | 仅 AST 和文本分析；不导入被分析脚本 |
| 历史备份冷归档 | archive_historical_backups.py --report 新报告路径 | 默认预演；--apply 只增加经恢复验证的归档，保留原路径 |
| 验证冷归档 | archive_historical_backups.py --verify ZIP路径 --report 新报告路径 | 在隔离临时目录逐文件恢复、核对哈希和数据库 |
| 已确认完成任务的旧数据库副本整理 | compact_completed_task_snapshots.py | 默认预演；--apply 逐份压缩、完整恢复验证后删除原副本；保留最新恢复点、基线、带 sidecar 或有引用的库，见 docs/ai/completed-task-snapshot-cleanup.md |
| 沪教完成后整组快照整理 | compact_snapshot_bundles.py | 先确认七组全部入库；主库新备份保护；主文件与 WAL/SHM 全部独占、整组恢复验证后才删除，不清理湘教在录任务 |
| 数据库备份 | backup_database.py | 运行前查看 --help；保留备份和审计报告 |
| 本地数据包 | local_data_bundle.py | 覆盖范围见文档，不等于完整录题任务备份 |
| 包含录题任务材料的数据包 | local_data_bundle.py export --include-ingestion | 显式包含 data/imports；暂停任务写入；跨电脑绝对路径另行迁移，见 docs/ai/ingestion-task-bundles.md |
| 草稿图片迁移 | migrate_draft_asset_storage.py | 默认预演；--apply 前检查报告；保持人工审核门槛 |
| PDF 来源去重 | migrate_source_pdfs.py | 默认预演；执行/回退需 --apply；需避开并发任务写入 |
| Word 公式提取 | inspect_word_formulas.py | 生成待复核报告，不直接录入正式题库 |

各脚本的参数以 --help 和源码为准。不是所有脚本都有预演选项，不能给历史脚本机械加 --dry-run 后就认为安全。

## 历史任务脚本

历史源码归档入口为 python -m scripts.archive_maintenance_sources --archive 新ZIP --report 新JSON，默认只预演，--apply 增加经校验的源码副本而不移动原脚本。最新调用关系和归档边界见 docs/ai/backend-script-template-consolidation.md。

stage_*、record_*、prepare_*、payload* 以及 fix.py、fix3.py、up09.py 等脚本通常对应特定年份、特定批次的输入和修补步骤，不能当作通用按钮反复运行。有些脚本互相读取或调用，也可能依赖当前脚本目录位置。

本次采用保留原路径、单独建立索引的整理方式，不移动脚本，不删除源码，不为一次性写入脚本新增启动入口。新的只读清单位于 reports/maintenance_scripts_catalog_20261103.json，包含分类、引用来源、文档摘要、写操作线索和语法问题。没有查到静态引用不代表无效。

smoke_*、audit_*、verify_* 是检查工具候选，但名称并不保证只读；例如冒烟测试应明确只在临时库/副本运行。执行前仍需看相关文档和参数。

## 备份保留原则

1. 迁移前恢复包、迁移日志和近期快照作为保护层保留。
2. 历史修改基线先做可恢复的压缩冷归档，保留每个原文件名和哈希。
3. 是否可删必须检查对应任务是否验收、原路径是否仍被使用、外部图片/PDF 是否齐全；本轮没有启用自动过期或删除。
4. SQLite 的 WAL/SHM 文件不能单独当缓存删除，带非空 WAL 的备份需先建立一致性快照。

完整说明见 docs/ai/backup-and-script-governance.md。

已结束 PDF 任务的页面去重：`python scripts/deduplicate_closed_job_pages.py` 默认预演，`--apply` 仅合并指定旧目录中完全相同的生成页面，保留原路径并设为只读，不删除 OCR、裁剪图或草稿。范围与审核清单见 [页面整理说明](../docs/ai/closed-job-page-dedup.md)。
