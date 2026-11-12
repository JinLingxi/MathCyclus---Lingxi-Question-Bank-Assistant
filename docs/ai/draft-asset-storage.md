# 草稿图片稳定存储

## 当前规则

自 2026-10-31 起，新建草稿、添加图片和替换图片时，通过导入服务将可读取的资源复制到稳定资源目录：data/draft_assets/哈希前两位/完整SHA-256/原文件名。

- 图片先验证内容哈希，再原子发布稳定副本；不覆盖已有且内容冲突的文件。
- 原文件名、显式 alias、caption、排序和图片字节保持不变，保证审核预览与题目占位引用兼容。
- 已有文件哈希不匹配时拒绝迁移，不通过重新计算哈希掩盖修改。
- 原文件保留；后续修改临时来源不影响已保存的草稿副本。通过界面换图时生成新的稳定副本，并按原有规则要求重新审核。
- planned_file_path 如果只是 source_path 的镜像，会一起更新；独立的计划目标保持原有语义，不自动迁移。
- 缺失资源仍由原有校验报告，不生成假图片或伪造已完成记录。
- 需要显式原路径的 includegraphics 内容不属于本次历史迁移范围，不能据此认为所有临时目录都已可以删除。

稳定资源目录属于正式使用的本地数据，不能作为缓存删除，也不上传 Git。本地数据迁移包已默认包含该目录，恢复时也允许恢复这一前缀。临时数据库位于项目目录外时，资源保存到临时数据库同级的 draft_assets，避免测试污染真实数据。

## 历史迁移

首次迁移覆盖 2,241 条未批准草稿图片记录，涉及 1,764 道草稿；对应 2,239 个稳定图片文件，约 62.57 MiB。已提交草稿的 17 条历史资源记录和 1 条示例记录跳过。没有自动批准或提交题目，正式题表、试卷关系、教材关系和专题关系不变。

迁移只修改资源记录的 source_path、planned_file_path、file_hash，以及相应草稿的内容哈希和更新时间，追加存储迁移审计事件。未修改题目正文、答案、解析、审核状态、图片内容或显示标题。原图和任务目录保留，本步骤暂时增加约 62.57 MiB 的稳定副本，不宣称已经节省磁盘。

原 PDF、整题截图、来源回看、已提交历史记录和录题脚本仍可能引用历年任务目录。删除任务目录必须另外完成引用分析；不能因本次草稿图迁移完成就整包删除 data/imports。

## 工具与回退

- scripts/migrate_draft_asset_storage.py 默认仅预演，--apply 执行迁移。执行前生成逐条 dry-run 清单，并使用 SQLite backup API 生成一致性数据库备份。
- scripts/verify_draft_asset_relocation.py 默认在临时全量数据库副本上演练，检查字节、别名、显示字段、实际图片预览 HTML、资源引用、正式表内容、幂等性和回退结果。
- 使用验证工具的 --manifest 指定执行清单可检查实际工作库；--output 指定新的报告文件。
- 回退命令：虚拟环境 Python 运行 scripts/migrate_draft_asset_storage.py --apply --rollback reports/draft_asset_storage_applied_20261031.json。回退前再次备份，迁移后被编辑或审核的受影响草稿会被拒绝覆盖，需要逐项处理。两个位置的图片均保留，不执行文件删除。

本次清单：reports/draft_asset_storage_applied_20261031.json。备份路径记录在清单的 backup_path 字段。演练报告、实际校验报告与预览对比报告分别保存在 reports/draft_asset_storage_rehearsal_20261031.json、reports/draft_asset_storage_verified_20261031.json、reports/draft_asset_storage_preview_verified_20261031.json。

## 接下来可继续优化的内容

共享 PDF 来源存储已落地，见 [source-pdf-storage.md](source-pdf-storage.md)；备份分层审查及阶段冷归档见 [backup-and-script-governance.md](backup-and-script-governance.md)，历史源码归档见 [backend-script-template-consolidation.md](backend-script-template-consolidation.md)。这些工作保留原路径，不授权删除旧任务或恢复材料。

稳定图片目录暂不自动垃圾回收；未引用对象需在完整引用检查和保留期设计之后再处理。Git 忽略、备份范围和当前未验证项见 [local-data-boundaries-and-status.md](local-data-boundaries-and-status.md)。
