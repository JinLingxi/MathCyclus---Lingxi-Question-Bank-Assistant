# 可选录题任务备份与恢复

## 当前能力

scripts/local_data_bundle.py export 新增 --include-ingestion，显式选择时包含 data/imports 下的任务文件、来源 PDF、页面图片、候选载荷、录题中间材料和历史快照。默认导出范围保持不变，未改 UI。

示例：使用虚拟环境 Python 运行 scripts/local_data_bundle.py export --include-ingestion --include-legacy-tex --output data/backups/自选新文件名.zip。建议先加 --dry-run 核对范围和体积。任务目录逻辑体积可能很大；ZIP 不保留硬链接去重关系，原路径下的相同 PDF 会分别打包，恢复后也可能成为独立文件。

这项能力用于完整携带指定目录的材料，不代表所有外部依赖均已被发现。工作区外文件不自动纳入；其他根目录参考 PDF、模板和维护源码需另行保留。任务、数据库和 JSON 中的绝对路径原样保存，跨电脑/跨根目录需要独立路径迁移与回看验证，不能宣称恢复后所有来源链接自动可用。

`.ingestion/` 本地协调记录也不属于 `--include-ingestion` 的范围；该开关对应的是 `data/imports/`。各目录的 Git 与备份边界见 [local-data-boundaries-and-status.md](local-data-boundaries-and-status.md)。

## 一致性与覆盖保护

- 主数据库通过 SQLite backup API 建立一致性快照，避免直接复制数据库时遗漏 WAL 中已提交的数据。
- 新包拒绝覆盖已有输出，先写临时 ZIP，核对打包过程中的文件哈希后发布。
- 非主库任务快照如果存在非空 WAL 则拒绝打包，需先做一致性快照；WAL/SHM 和 Python 缓存不独立打包。
- 导出时暂停录题、裁剪、OCR 和审核写入。数据库快照一致不等于数据库与整个文件树具有跨资源事务一致性，文件树在扫描完成后新增加/删除的文件仍需重新预演。
- 恢复先核对全部允许路径、文件哈希、目标冲突和主数据库，再开始写入，坏包不会在预检阶段写入一半；禁止目录链接、路径穿越等目标。
- --overwrite 仍需显式给出，数据库覆盖前保留一致性备份。恢复不是多文件事务，写入阶段的磁盘满、权限变化或断电仍可能导致部分文件已写入；生产恢复优先落到新目录，验证后再切换。
- 不执行包内 Python、SQL 或其他脚本；保留审核状态，不自动导入题目。

## 验证

tests/test_ingestion_bundle.py 覆盖可选任务往返、默认范围不变、提交到 WAL 的数据不丢失、损坏包零写入、目标冲突零写入和路径穿越拒绝。scripts/smoke_local_workspace_tools.py 验证现有数据包导出、预演、恢复、冲突和覆盖备份行为。

本轮未制作当前所有录题目录的巨大生产包，也未向实际工作库执行恢复。所有恢复测试在隔离目录进行；原题、草稿、页面、来源和原备份均保留。
