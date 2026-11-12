# 已完成录题任务的数据库副本整理

## 工具范围

scripts/compact_completed_task_snapshots.py 针对用户指定任务范围中的旧 SQLite 副本提供预演、压缩恢复验证和原副本删除。它不删除任务记录、正式主库、草稿、图片、来源 PDF、任务 JSON、旧 TeX 或脚本，不安装自动清理任务。

本轮目录白名单为截图涉及的人教 A/B、清北强基、AMC 和 2000—2026 高考任务；正在录入的沪教、湘教不在范围内。白名单不等于对任意未来任务自动认定已完成，后续重跑仍需先核对任务状态和预演清单。

## 保留规则

- 每组最新两份恢复点继续留在原路径。
- 初始 baseline_before_batch、baseline_before_task 及 prepared 证据库保留。
- 一小时内修改、有额外硬链接、带 WAL/SHM/journal 文件的数据库保留。
- 正式数据库、任务清单、协调记录及源码/文档中有字面引用的候选保留。
- 引用检查不穷尽工作区外脚本和动态路径，因此被整理的副本仍以可恢复压缩对象保留；历史报告原路径需要时通过恢复命令重建。

## 执行与恢复

预演：python scripts/compact_completed_task_snapshots.py

明确确认预演范围后执行：python scripts/compact_completed_task_snapshots.py --apply

每份副本单独压缩到 data/backups/cold_archives/completed_tasks_时间戳/，以适应磁盘余量较小的情况。压缩后在隔离目录完整恢复，核对 SHA-256、字节数及 SQLite quick_check；再将恢复凭据写入并 fsync 逐项日志，最后独占打开原文件，再次计算哈希，才通过该文件句柄删除。

文件变化、占用、恢复校验失败或磁盘空间不足时保留原副本并记入错误项，不强行删除。归档字节量（包括失败时留下的压缩文件）从实际删除字节量中扣除，报告净减少的文件字节数；这与磁盘实际空闲量还可能因其他录题进程及文件系统分配而不同。

恢复单份：python scripts/compact_completed_task_snapshots.py --restore-archive data/backups/cold_archives/对应目录/对应文件.zip

压缩包内含原路径、修改时间、大小及哈希。恢复时先检查允许路径，在临时文件中完整校验，再无覆盖发布到原路径；原路径已有文件时拒绝覆盖。不自动批量恢复到当前题库，也不执行归档中的程序。

计划、归档验证记录、逐项删除/保留结果和最终汇总保存在 reports/completed_snapshot_cleanup_时间戳.*。不得只看压缩包存在就认定原文件已经可删。

## 沪教任务完成后的整组副本整理

2026-11-08 用户确认沪教录入完成后，新增 scripts/compact_snapshot_bundles.py。该工具先要求 7 个沪教根任务的草稿均为 committed，并保存一份完成后的正式主库一致性备份。湘教在录任务不纳入。

预演：python scripts/compact_snapshot_bundles.py

执行：python scripts/compact_snapshot_bundles.py --apply

本轮输入是上一轮因 sidecar 保留的旧副本，以及沪教各册已经过时的 baseline_before_batch 和 stage_baseline。沪教最新最终演练库、任务完成备份和原页材料保留；这些阶段基线作为完整压缩证据保留，不再要求松散原副本一直占用原路径。

当前数据库、业务服务、界面、协调记录和任务清单中的字面引用会阻止清理。已完成任务的专用维护脚本或历史报告引用的副本可以进入可恢复归档，需要重放历史操作时先恢复原路径。

数据库及现存 WAL/SHM/journal 必须全部取得独占句柄，禁止只删一部分。锁定期间逐个保存精确字节和哈希，完整解压到隔离目录核对后，以 SQLite 实际读取 WAL 的方式执行 quick_check。只有恢复验证及持久化凭据完成后才标记整组删除；某个标记失败时撤销前面已设置的删除标记，无法独占或校验失败则保留。

恢复单组：python scripts/compact_snapshot_bundles.py --restore-archive data/backups/cold_archives/对应目录/对应ZIP

恢复先在隔离目录验证，已有原路径成员仅在字节完全相同时保留；存在不同字节时拒绝覆盖。未缺失的成员不覆盖，缺失成员通过无覆盖方式发布。压缩包携带完整成员清单，支持恢复主文件及其关联 WAL/SHM，不把这些 sidecar 当作普通缓存。

计划、逐组凭据和结果位于 reports/snapshot_bundle_cleanup_时间戳.*。净释放量扣除全部本轮 ZIP 及新建主库保护备份，不将保留压缩包的体积误计为已释放空间。
