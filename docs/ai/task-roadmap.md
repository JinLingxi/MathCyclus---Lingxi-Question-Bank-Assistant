# 当前路线与后续任务

## 2026-11-06 当前复核

草稿及录题材料的默认目录已被 Git 忽略，私有跟踪审计无待处理项。草稿图稳定存储、集中 PDF、备份和历史源码阶段归档已完成基础治理；不继续把这些基础工作笼统列为未完成。详细证据、存储/备份范围及限制见 [local-data-boundaries-and-status.md](local-data-boundaries-and-status.md)。

当前继续推进：并行任务独立草稿与正式提交协调、跨机器路径迁移及完整任务恢复验证、持续录题后的新一轮数据审计、发布前完整回归。以下题量、差异数量和旧阶段结论保留用于追溯，不等于当前数据库状态。

## 既有阶段实施记录

用户确认同位置冲突草稿正确后，651 个题位已按可信草稿覆盖，旧答案解析138份迁入匹配目标，31份不确定内容另建保全草稿。正式题总数保持8322，旧文件/关系历史保留。详见 [position-replacement-with-responses.md](position-replacement-with-responses.md)。

用户授权五组录题任务按“录入本批非重复题目”正式录入，新增 7,266 道，正式题合计 8,322；1,165 道重复/位置冲突继续待审核。详见 [nonduplicate-bulk-entry-20261103.md](nonduplicate-bulk-entry-20261103.md)。

已统一导出资源解析/路径/复制逻辑，保留原接口；193 个历史脚本和 9 个关联脚本已做源码校验归档，原路径保留；新增独立讲义/训练导出与六份编译样张。Lucide 因缺包与网络限制未验证。详见 [backend-script-template-consolidation.md](backend-script-template-consolidation.md)。

资源审计现支持 --baseline 前后逐项比对，区分新增异常、已知问题、计数下降与扫描范围缩小，不自动更新基线。验收入口见 [resource-acceptance.md](resource-acceptance.md)。

资源深度可读性检查已覆盖登记资源、草稿回看材料、来源页码和任务原页：30,526 张图片解码通过，无新增异常；已知示例缺图和 created 任务保留原状。详见 [resource-integrity-audit.md](resource-integrity-audit.md)。

已执行正式题、草稿、资产和 PDF 任务的资源引用只读检查；已兼容历史图像摘要格式。结果、示例草稿和未完成任务的分类见 [resource-integrity-audit.md](resource-integrity-audit.md)。本轮无资源修复或删除。

本地数据包新增可选 --include-ingestion，主库导出改用一致性快照，恢复前先全量校验。原 UI 与默认导出范围保持；跨根目录绝对路径迁移尚待单独验证，见 [ingestion-task-bundles.md](ingestion-task-bundles.md)。

录题目录引用审查已补齐只读工具，覆盖库内 JSON、审核/修订记录及项目文本。清单仅列保留证据和待核对项，不授权删除；见 [ingestion-directory-retention.md](ingestion-directory-retention.md)。

2026-11-03 已补备份保留审查、历史备份冷归档与隔离恢复验证、维护脚本静态分类和入口索引。原备份/脚本路径全部保留，无自动删除；见 [backup-and-script-governance.md](backup-and-script-governance.md)。

2026-11-03 已完成 PDF 来源统一存储及 88 条任务路径去重，保留原路径和恢复包，验证及回退说明见 [source-pdf-storage.md](source-pdf-storage.md)。备份盘点、冷归档和历史源码阶段归档亦已完成对应步骤；后续删除或迁移仍需具体清单和恢复依据。

已完成未批准草稿图片迁入稳定资源目录，并接入新增、替换图片和本地数据迁移包。详见 [draft-asset-storage.md](draft-asset-storage.md)。共享 PDF 来源与备份治理已有专项实施记录，历年录题目录继续按引用及恢复需要保留。

外部项目吸收的已实现内容、工具入口和边界见 [external-project-improvements.md](external-project-improvements.md)：相似差异提示、资源哈希与来源复核协议、Word 原生公式提取、教材与知识板块独立查询。编辑器、组卷和统计的后续交互修改见本轮复核。

## 已形成闭环

- SQLite 结构化题库、旧 TeX 兼容桥接和 TeX 导出。
- 单题、批量、同卷、同书草稿录入与人工二次审核。
- 云端 MinerU 优先、PyMuPDF 回退的 PDF 页面解析边界。
- 页面级 AI 识别、进度持久化、暂停/恢复、失败重试和图片裁剪草稿。
- PDF 任务 provenance 已记录输入哈希、解析器、模型、提示词指纹和识别器版本。
- 完全相同、来源位置冲突、高度相似和人工等价关系记录。
- Local API 草稿输入和发布包私有数据隔离。

## 阶段优先任务（历史，当前验证范围见顶部复核）

1. 用真实题库样本评估相似度阈值的误报和漏报，再决定是否调整阈值。
2. 继续人工复核 31 条旧 TeX/SQLite 非阻塞元数据差异，不自动覆盖来源信息。
3. 完善扫描 PDF 的人工拖拽裁剪、复杂图片区域检测和多区域合并。
4. 补强教材、专题、试卷、图片资源和修订记录的双向查看入口。
5. 继续完善本地数据迁移包、版本兼容检查和普通用户部署流程。

## 可以吸收的外部启发

朋友项目中的“任务 → 必读规范”很适合本项目，具体吸收为本目录的任务路由表。除此之外还有三点值得后续采用：

- 为每一种录入任务提供固定的“输入、预期输出、禁止事项、验收检查”文档，减少 AI 自由发挥。首批模板见 [task-templates](task-templates/README.md)。
- 为外部题集、教材和官方样卷建立独立导入工作流，先保存原始来源和外部 ID，再通过 `question_equivalence` 关联已有题目。
- 为每次批量导入建立可恢复任务摘要，记录解析器、模型、提示词版本、输入文件哈希和人工决策，方便复现和回滚。

## 暂不直接照搬的部分

- 不把所有规范堆到一个超长的单一 AI 指令文件，避免通用规则、TeX 规则和数据库规则互相污染。
- 不把每次开发日志当成当前规范；日志进入 `docs/logs/`，当前规则进入 `docs/ai/`。
- 不把外部题库的字段和 PaperType 直接套进当前 schema；先做字段映射和来源类型确认。
- 不因为有了 AI 规范文档就绕过草稿审核、重复题检查或正式入库保护。
