# PDF 来源存储与去重

2026-11-03 已完成首次来源去重。data/source_pdfs/哈希前两位/完整SHA-256.pdf 保存独立复制的来源对象；每个任务的 source.pdf 原路径保留，通过同卷硬链接读取同一对象。原始上传文件不参与硬链接，后续修改上传文件不会改变已存来源。

## 数据与界面边界

- 不修改 SQLite 正式题、草稿、审核状态、题目关系、图片目录、题干、答案或解析。
- 不修改任务清单或候选载荷，不改变 source.pdf 的路径，因此 UI、来源复核、重试和旧脚本仍按原路径读取。
- 集中来源和任务来源均设为只读。硬链接共享字节与文件属性，不能清除只读标志后原地编辑任意一条链接；修改来源应上传新文件并创建新任务。只读属性防止普通误写，不是对管理员或恶意程序的安全隔离。
- 新建 PDF 任务自动使用集中存储，跨卷不能创建硬链接时采用独立副本，保留功能。
- 本地数据迁移包包含 data/source_pdfs。该迁移包仍不包含完整 PDF 任务目录，因此换电脑要继续保留或另行迁移任务、页面截图及相关清单；不能把集中 PDF 包等同于完整录题任务备份。
- 本步骤不删除任何任务目录，不清理原图片、旧题源、任务页面、备份或一次性脚本。

## 本次结果与验证

88 个来源路径分成 2 个相同内容组；最大组有 74 份 102,144,746 字节的 PDF。每份文件均与各自清单 SHA-256 一致后才允许处理。

迁移前用 ZIP_STORED 独立保存每种唯一来源一份以及完整计划，逐份验证恢复包哈希，再更新路径。日志逐条记录 prepared/applied 状态，支持中断审查和回退。Windows 短暂占用曾导致最终日志写入失败，随后独立验证全部 88 条路径、只读属性、哈希、任务清单字节、页数与首页渲染一致后才补写 complete；日志写入增加了短期重试。

扣除约 97.6 MiB 的来源恢复包，估计净释放 7,356,087,597 字节（约 6.85 GiB）。这是按重复文件字节估算，硬盘实际可用空间还受文件系统分配影响。

数据库仍为 1,056 道正式题、8,524 条草稿、2,259 条草稿资源；其中 needs_review 草稿 8,431 条。quick_check 正常、foreign_key_check 无问题。42 项回归测试通过，PDF 导入、失败重试、审核页面和本地数据包导出恢复冒烟检查通过。UI 文件本轮未修改。

## 操作与恢复

- 预演：虚拟环境 Python 运行 scripts/migrate_source_pdfs.py。
- 执行：同一命令添加 --apply，自动生成恢复包和迁移日志；执行前应避开任务写入，保存 dry-run 结果。
- 验证：scripts/verify_source_pdf_migration.py --journal 指向日志，--output 指定新的 JSON 报告。只有验证全部通过时才可使用 --finalize 补写中断的最终状态。
- 回退：scripts/migrate_source_pdfs.py --apply --rollback 指定迁移日志。逐条从恢复包复制成独立文件，恢复原权限与修改时间；如果来源字节已发生变化则拒绝覆盖。回退不删除集中对象或恢复包。

本次可回退日志：reports/source_pdf_migration_journal_20261103.json。其 backup 字段包含恢复包路径。验证报告：reports/source_pdf_migration_verified_20261103.json。预演报告：reports/source_pdf_migration_preflight_20261103.json。

后续已完成备份盘点、阶段冷归档及历史脚本分类/源码归档，见 [backup-and-script-governance.md](backup-and-script-governance.md)、[backend-script-template-consolidation.md](backend-script-template-consolidation.md)。原路径和恢复材料仍保留，不删除恢复包、稳定图片、集中 PDF 或历年任务目录。最新边界见 [local-data-boundaries-and-status.md](local-data-boundaries-and-status.md)。
