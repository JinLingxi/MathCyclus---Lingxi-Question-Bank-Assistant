# AI/OCR 草稿导入流程

> 状态：第一版可执行 dry-run  
> 目标：让 AI/OCR 参与题目录入，但不直接污染正式题库。

## 1. 核心原则

- AI/OCR 的输出先进入 `question_import_draft`。
- 图片、扫描件、附件先进入 `question_import_draft_asset`。
- 只有 `ready` 或 `approved` 草稿可以进入提交预演。
- 提交预演只操作数据库副本，不修改正式库和 `.tex` 文件。
- 每一次插入或更新都必须写入 `question_revision`。
- 每一次导入都必须写入 `import_batch` 和 `import_report_item`。

## 2. 当前已落地文件

服务层：

- `services/import_service.py`
- `services/revision_service.py`

脚本：

- `scripts/import_draft_json_dry_run.py`
- `scripts/commit_import_drafts_dry_run.py`

模板：

- `templates/ai_ocr_draft_import_example.json`

报告：

- `reports/import_draft_json_dry_run_20260902_initial.md`
- `reports/commit_import_drafts_dry_run_20260902_initial.md`

## 3. JSON 输入格式

第一版支持对象顶层：

```json
{
  "source_path": "来源说明",
  "summary": "导入摘要",
  "items": []
}
```

也支持数组顶层：

```json
[
  {}
]
```

单题字段：

| 字段 | 说明 |
| --- | --- |
| `source_item_id` | 原始材料中的题目标识 |
| `source_label` | 前端显示名 |
| `proposed_action` | `insert` / `update` / `skip` |
| `target_question_id` | 更新已有题时填写 |
| `review_status` | `needs_review` / `ready` / `blocked` / `approved` / `rejected` |
| `question_type` | 支持英文编码，也支持单选题、填空题、解答题等中文名 |
| `stem_tex` | 题干 |
| `choices` | 选项数组，或 `{ "A": "...", "B": "..." }` 字典 |
| `answer_tex` | 答案 |
| `solution_tex` | 解析 |
| `difficulty` | 难度星级，建议 1-5 |
| `tags` | 标签数组 |
| `note` | 备注 |
| `official_flag` | 是否官方 |
| `raw_source_text` | 原始 OCR/AI 输入文本 |
| `confidence` | 字段置信度 |
| `validation` | 外部校验结果 |
| `extra` | 临时扩展信息 |
| `assets` | 图片/附件草稿数组 |

## 4. 草稿状态规则

`ready`：

- 题干、答案、解析等基础字段通过初检；
- 仍需用户最终确认；
- 可以进入提交 dry-run。

`needs_review`：

- 字段基本可保存，但有明显缺口；
- 例如缺答案、缺解析、含图片占位、置信度低；
- 不会被提交 dry-run 自动写入正式题目。

`blocked`：

- 无法安全处理；
- 例如缺题干、更新目标不存在、动作字段不支持；
- 必须人工修正后再提交。

`approved`：

- 已经人工确认；
- 可以进入提交 dry-run。

`rejected`：

- 确认不入库；
- 后续可保留审计记录。

## 5. 当前验证结果

命令：

```bash
python scripts/import_draft_json_dry_run.py --stamp 20260902_initial
python scripts/commit_import_drafts_dry_run.py --stamp 20260902_initial
python scripts/browse_question_db.py --db data/mathcyclus_preview_draft_commit_20260902_initial.sqlite3 import-drafts
python scripts/browse_question_db.py --db data/mathcyclus_preview_draft_commit_20260902_initial.sqlite3 revisions --limit 3
```

结果：

- 输入草稿：2 条。
- `ready` 草稿：1 条。
- `needs_review` 草稿：1 条。
- 提交预演插入题目：1 条。
- 新增预演题号：`Q000894`。
- 写入修订记录：1 条。
- `needs_review` 草稿未被提交。

另做过坏输入验证：

- `update` 指向不存在的 `target_question_id` 时，草稿被标记为 `blocked`。
- 缺少 `stem_tex` 时，草稿被标记为 `blocked`。
- 脚本不崩溃，不写正式题库。

## 6. 后续接入前端时的边界

录入新题页面可以逐步改为：

1. AI/OCR 输出 JSON。
2. 写入草稿预览区。
3. 左侧展示字段和来源关系。
4. 中间展示 TeX 源码。
5. 右侧展示渲染结果和校验结果。
6. 用户把 `needs_review` 修到 `ready` 或 `approved`。
7. 点击确认后进入正式提交流程。

正式提交流程上线前必须补：

- 数据库自动备份；
- 重复题检查；
- 图片文件存在性检查；
- 试卷、教材、专题关系确认；
- 完整 LaTeX/前端渲染预览；
- 回滚策略。

## 7. PDF 导入扩展方向

PDF 导入不应直接替代当前 AI/OCR 单题录入，而应作为草稿生成器接入本流程。

推荐路线：

1. 原始 PDF 先进入本地私有导入批次目录；
2. 通过 MinerU、pdf2md 或 PyMuPDF 解析为页面、文本块、公式块和图片块；
3. 系统按题号、页码、栏目和坐标初步切分题目；
4. AI 只处理单题块和局部截图，不直接吞完整 PDF；
5. 解析结果写入 `question_import_draft`；
6. PDF 中切出的题内图片写入 `question_import_draft_asset`；
7. 用户审核后再提交到正式 `question` 和 `question_asset`。

详细设计见：

- `docs/planning/pdf_import_pipeline.md`
