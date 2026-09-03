# SQLite 正式库提交流程规划

## 目标

把经过 dry-run 验证的预览 SQLite 库提升为正式 SQLite 库，同时保证：

- 不直接修改旧 `.tex` 题库；
- 不绕过备份、审计和差异报告；
- 不在存在阻断项时写入；
- 所有写入都可追踪、可回滚、可复查。

## 当前脚本

新增脚本：

- `scripts/promote_preview_to_database.py`

默认来源库：

- `data/mathcyclus_preview_combined_20260902_initial.sqlite3`

默认目标库：

- `data/mathcyclus.sqlite3`

确认文本：

- `PROMOTE_SQLITE_PREVIEW`

## 默认 dry-run

默认命令只生成报告，不写正式库：

```text
python scripts/promote_preview_to_database.py --stamp 20260902_initial
```

dry-run 会执行：

1. 检查来源预览库是否存在；
2. 对来源库运行提交前审计；
3. 对比目标正式库与来源预览库的表计数；
4. 采样新增 ID 和删除 ID；
5. 输出 Markdown 与 JSON 报告。

生成报告：

- `reports/promote_preview_to_database_<stamp>.md`
- `reports/promote_preview_to_database_<stamp>.json`

## 正式写入

正式写入必须显式执行：

```text
python scripts/promote_preview_to_database.py --apply --confirm PROMOTE_SQLITE_PREVIEW --allow-warnings --stamp <stamp>
```

写入规则：

- 没有 `--apply`：不写入；
- 没有正确 `--confirm`：拒绝写入；
- 有审计 blocker：拒绝写入；
- 有 warning 且没有 `--allow-warnings`：拒绝写入；
- 目标库已存在：必须先备份；
- 写入使用临时 SQLite 副本校验后原子替换目标文件。

## 备份策略

如果目标库已存在，会先写入：

- `data/backups/mathcyclus_<stamp>.sqlite3`

报告记录：

- 备份路径；
- 备份 SHA256；
- 备份 `PRAGMA integrity_check`；
- 来源库 SHA256；
- 写入后目标库 SHA256。

## 审计策略

当前审计来自：

- `scripts/precommit_database_audit.py`

阻断项包括：

- SQLite `integrity_check` 不通过；
- 存在外键错误；
- 存在失联关系；
- 存在 `blocked` 草稿。

警告项包括：

- 同一试卷同一题号存在重复位置；
- 存在缺失 `includegraphics` 图片；
- 存在未解析 `questionasset` 占位符；
- 存在 `needs_review` 草稿。

## 当前项目状态下的判断

最新综合预览库 `data/mathcyclus_preview_combined_20260902_initial.sqlite3` 与正式库 `data/mathcyclus.sqlite3` 的审计结果：

- blocker：0；
- warning：0。

已处理的历史 warning：

- 试卷题位重复已通过 `db/seed/paper_question_corrections_20260902_final_review.csv` 修正；
- `Q000696` 缺失的 3 个 `includegraphics` 引用已在数据库副本中删除；
- AI/OCR 模板草稿已标记为 `sample`，不会进入正式题表。

正式库已经生成：

- 路径：`data/mathcyclus.sqlite3`；
- Git 管理：应继续被 `.gitignore` 忽略，不提交到仓库。

## 后续接入顺序

推荐顺序：

1. 继续使用 `build_combined_preview_db.py` 生成综合预览库；
2. 使用 `promote_preview_to_database.py` dry-run 查看提交报告；
3. 人工审查并处理 warning；
4. 再决定是否 `--apply`；
5. 正式 SQLite 稳定后，再做 Streamlit 只读浏览入口；
6. 确认只读入口稳定后，再做新录题、改题、图片插入；
7. 最后再做从 SQLite 导出兼容旧 `problem` 命令的 TeX 文件。

## 明确边界

当前脚本不会：

- 修改 `question_bank_app.py`；
- 修改旧 `.tex` 源题库；
- 自动合并重复题；
- 自动补齐缺失图片；
- 自动把 AI/OCR 草稿写进旧题库；
- 自动推送 GitHub。
