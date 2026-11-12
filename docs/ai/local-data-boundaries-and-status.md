# 本地录题数据边界与项目状态复核

> 复核日期：2026-11-06。范围为实际存储代码、Git 忽略/跟踪状态和主要文档的一致性。未执行正式库写入、资源迁移、文件清理、生产备份或恢复，也未重新执行全套发布验收。

## 草稿和录题材料保存在哪里

| 内容 | 默认位置 | Git 边界 | 备份要求 |
| --- | --- | --- | --- |
| 草稿题文、分类、审核状态、草稿资源登记 | `data/mathcyclus.sqlite3` 中的 `question_import_draft`、`question_import_draft_asset` 等表 | 数据库及 SQLite sidecar 已忽略 | 默认数据包包含主库一致性快照 |
| 草稿图片稳定副本 | `data/draft_assets/<哈希前两位>/<SHA-256>/<原文件名>` | 已显式忽略 | 默认数据包包含；属于需保留的数据 |
| 集中 PDF 来源 | `data/source_pdfs/` | 已显式忽略 | 默认数据包包含；任务路径可能仍依赖硬链接或副本 |
| PDF 任务、原页、整题截图、候选、OCR、任务内历史快照 | `data/imports/`，标准 PDF 任务在 `data/imports/pdf_jobs/` | 已忽略，仅跟踪目录占位文件 | 导出时显式使用 `--include-ingestion` |
| 上传文件、解析缓存 | `data/uploads/`、`data/asset_cache/` | 已显式忽略 | 按任务引用决定保留；不能仅凭目录名删除 |
| 可重建查重缓存 | `data/cache/` | 被 `data/*` 覆盖 | 可重建，区别于草稿、原页和来源对象 |
| 本地任务协调记录 | `.ingestion/` | 已显式忽略 | 当前标准数据包不包含此目录，按需要另行备份 |
| 正式题图片、备份、报告、导出 | `assets/questions/`、`data/backups/`、`.backups/`、`reports/`、`exports/` | 已忽略，部分目录保留 `.gitkeep` | 按各自恢复及验收用途保留 |

`data/imports/` 的具体任务可以使用自己的子目录。后续新开的强基、教材等任务应放在独立子目录，并使用独立批次和输出文件名；不要在根目录随意建立未被忽略的草稿输出目录。

实际服务允许自定义任务根目录；工作区外临时数据库的草稿图片保存在数据库同级的 `draft_assets/`。这些自定义位置不能默认视为已被本仓库的忽略规则或数据包覆盖。

## 本轮 Git 检查结果

- `git check-ignore -v --no-index` 验证数据库/WAL、草稿图片、PDF 来源、PDF 任务、上传/缓存、任务协调记录、正式图片、报告和导出路径均命中规则。
- `git ls-files` 检查主要私有数据目录，只发现 `.gitkeep` 占位文件。
- `git ls-files -ci --exclude-standard` 无结果：未发现已被忽略但仍受 Git 跟踪的文件。
- `python scripts/audit_tracked_private_files.py --json` 返回 `status=ok`、`tracked_cleanup_count=0`，未执行取消跟踪操作。
- 当前规则已覆盖上述默认位置，本轮不修改 `.gitignore`，也不执行 Git 提交或上传。

检查结论针对当前索引和规则，不等于对 Git 全部历史、任意位置的草稿文件或全部源码内容完成泄露审查。新目录、新的自定义输出位置和发布包仍需重新检查。

## 已完成的基础治理

- 草稿图片已接入稳定存储；迁移工具、回退依据和范围见 [draft-asset-storage.md](draft-asset-storage.md)。
- PDF 来源共享存储及保留原路径的去重已落地，见 [source-pdf-storage.md](source-pdf-storage.md)。
- 录题目录引用审查、资源深度检查、基线比较已提供对应工具，见 [ingestion-directory-retention.md](ingestion-directory-retention.md)、[resource-acceptance.md](resource-acceptance.md)。
- 备份盘点、历史备份冷归档及恢复验证、历史源码归档已完成相应阶段，见 [backup-and-script-governance.md](backup-and-script-governance.md)、[backend-script-template-consolidation.md](backend-script-template-consolidation.md)。
- 数据包支持可选包含录题材料，见 [ingestion-task-bundles.md](ingestion-task-bundles.md)。
- 本次会话已处理单题编辑重叠、组卷两列纯预览、试题篮局部开关与双侧缩放、选项布局稳定性、首帧定位和多余占位、统计分布与活跃热力图交互。验证脚本在 `scripts/check_exam_*.cjs`、`scripts/check_statistics_distribution.cjs`、`scripts/check_activity_heatmap.cjs`；单次局部检查不替代完整发布回归。

这些工作完成后，历史文件仍可能保留原位置以支持来源回看、失败重试和回退。保留文件是当前治理策略的一部分，不能把“尚未删除”直接认定为整理未完成。

## 仍需推进或重新验证

1. **并行正式入库**：当前不能宣称多个 Codex 同时提交正式题库已安全验收。保持独立任务/草稿，正式提交协调执行；同一任务和程序文件也需避免交叉修改。
2. **跨机器恢复**：已有任务材料打包能力，但跨根目录绝对路径迁移、完整来源回看以及当前全部录题任务的生产恢复仍需专项验证。导出一致性包时暂停相关录题写入。
3. **当前数据质量**：历史报告中的题量、缺图数、重复题和元数据差异数量只是当时快照。录题持续进行，应依据新生成的同范围审计报告判断，不能沿用旧数字声称当前通过。
4. **发布验收**：当前工作区有多项未提交改动；发布前仍需检查白名单包、私有数据排除、依赖及完整回归。本次没有重跑全套检查。
5. **按需增强**：复杂扫描页裁剪、相似度阈值评估、可选 Lucide 模板依赖等以专项文档为准，没有验证的内容继续保留为待办。

自动清理业务资料、删除旧脚本、覆盖历史备份均未开启。本次复核没有授权或执行这些操作。
