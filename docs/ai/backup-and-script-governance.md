# 备份与历史脚本治理

## 2026-11-03 当前结果

本轮保留所有业务数据、UI 和脚本原路径，新增备份目录审查、脚本分类索引与压缩冷归档工具。未开启自动清理、过期删除、脚本自动执行或后台计划任务。

首次审查 data/backups 与 .backups 共 2,241 个文件，约 5.56 GiB，其中 217 个 SQLite 快照。采用只读 immutable 方式检查数据库，避免审计生成 WAL/SHM 或修改旧快照；结构快速检查和外键检查全部通过。存在约 394 MiB 相同字节副本，仍保留各自历史路径，不因哈希相同就自动去掉副本。

保护层包括 data/backups/source_pdf_migration 的 PDF 独立恢复包和 data/backups/draft_asset_storage 的草稿图迁移前快照。它们保留到相应迁移的回退周期结束，不能纳入普通缓存清理。

历史层为 .backups 中 1,774 个文件，共 640,022,295 字节，包含 42 个数据库及旧 TeX、CSV 和变更清单。压缩归档记录每个原相对路径、字节数、修改时间和 SHA-256；生成后在隔离临时目录逐一恢复文件、核对字节并检查恢复后的数据库，再次盘点原目录确认其未变后才发布归档。源目录和源备份保持原样，所以本步骤新增压缩恢复副本，不宣称已释放磁盘空间。

实际 ZIP 为 141,037,671 字节（约 134.5 MiB），压缩后为原体积的 22.04%。已验证恢复 1,774 个文件和全部 42 个数据库。

## 工具和报告

- scripts/audit_backup_retention.py：默认只有只读审计操作，--output 为必须不存在的新 JSON 报告路径。非空 WAL 标记为需一致性快照，不直接按单独数据库文件检查。
- scripts/archive_historical_backups.py：默认预演；--apply 仅增加 ZIP，不剪除原文件。可用 --archive 指定新 ZIP 路径，--report 指定新报告。发布前拒绝坏数据库、目录联接、符号链接、SQLite sidecar、变化中的源备份和已存在输出。
- 同一归档工具使用 --verify ZIP路径 --report 新报告路径，可重新独立验证全部文件恢复。它不会把文件恢复进当前工作目录覆盖现有题库。
- scripts/catalog_maintenance_scripts.py：只解析文本和 AST，不执行、不导入被审查脚本；参数 --output 指定新报告。写操作线索、main guard 和静态引用仅作人工审查参考，不是安全执行认证。
- scripts/README.md：按用途列出维护入口，区分历史录题和日常工具。

首次报告：reports/backup_retention_audit_20261103.json、reports/maintenance_scripts_catalog_20261103.json、reports/historical_backups_archive_preflight_20261103.json、reports/historical_backups_archive_verified_20261103.json。归档存于 data/backups/cold_archives/historical_backups_20261103.zip。

首次脚本盘点为 393 个，按名称和用途线索分类：193 个历史任务候选、75 个核查候选、13 个运维候选、112 个需人工阅读。新增治理脚本后可重新生成当前清单。所有历史脚本保留原位置，避免破坏文件相对路径、相互调用和既有工作流；193 个候选不等于193 个无用文件。

## 后续处理边界

可恢复冷归档不自动授权删除原备份。确认历史阶段已验收、完整恢复材料齐备且原路径没有调用方之后，才考虑按具体清单压缩替代。数据库快照可能依赖外部图片、PDF 与目录结构，quick_check 通过不代表完整应用恢复已经验证。

本轮未移动或删除历史脚本，未修改现有应用入口、服务运行逻辑、正式题或草稿记录。继续优先小范围、可验证和可回退的整理。
