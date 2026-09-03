# 数据库字段说明

> 对应文件：`db/schema.sql`  
> 状态：第一版草案  
> 目标：解释第一版 SQLite schema 中每张表的职责，避免后续开发时把题目本体、来源关系、专题关系、图片资源和修订记录混在一起。

## 1. 设计边界

当前数据库设计遵循四条边界：

1. `Question` 只表示题目本身。
2. 题目出现在试卷、教材、专题中的位置，都使用关系表表达。
3. 图片、扫描件、附件使用资源表表达，不直接散落绑定到正文路径。
4. AI/OCR/人工修改都必须进入修订或导入报告，不直接静默覆盖。

## 2. 核心题目表

### 2.1 `question_type`

题型字典表。第一版包含：

- `single_choice`：单选题
- `multiple_choice`：多选题
- `fill_blank`：填空题
- `solution`：解答题
- `other`：其他

题型变化频率低，适合独立成表。

### 2.2 `question`

题目本体表。保存题目核心内容和当前通用元数据。

重要字段：

- `question_id`：未来系统里的唯一题目身份。
- `stem_tex`：题干。
- `choices_json`：选项数组。没有选项时为空数组。
- `answer_tex`：答案。
- `solution_tex`：解析。
- `difficulty`：难度星级。
- `tags_json`：标签数组。
- `note`：题目本体备注。
- `official_flag`：是否官方。
- `canonical_tex`：从字段生成的标准 TeX 缓存。
- `raw_source_tex`：迁移或导入时的原始文本。
- `legacy_id`：旧 `.tex` 头部 `% ID`。
- `legacy_file_path`：旧 `.tex` 路径。
- `usage_count`：当前旧系统中的组卷引用次数。

注意：

- `question` 不保存题号、小题号、教材页码、专题分组。
- 这些信息都属于“题目在某处出现”的关系属性。

### 2.3 `question_analysis`

题目教研分析表，对应朋友截图中的扩展字段：

- `target_tex`：考查目的。
- `production_tex`：命题过程。
- `evaluation_tex`：试题评析。
- `marking_data_tex`：阅卷数据。
- `warning_tex`：易错警示。
- `reference_text`：参考文献。
- `extra_json`：暂未定型的扩展字段。

拆表原因：

- 保持题目核心查询轻量。
- 允许后续增加教研字段。
- 避免 `question` 主表过胖。

## 3. 试卷系统

### 4.1 `paper`

试卷表，保存试卷本身：

- `year`：年份。
- `paper_series`：卷别，例如 `G`、全国卷、新高考卷等。
- `track`：文科、理科、新高考、综合。
- `paper_name`：标准试卷名。
- `source_name`：原始来源名。

### 4.2 `paper_question`

试卷题目关系表，保存题目在试卷中的位置：

- `paper_id`
- `question_id`
- `question_number`
- `sub_number`
- `display_order`
- `origin_tex`
- `location_tex`

关键原则：

- 同一道题出现在两张试卷中，建立两条关系。
- 同一道题在文科和理科卷中都出现，也建立两条关系。
- 题号不是 `Question` 的字段，而是 `PaperQuestion` 的字段。

## 4. 教材系统

### 5.1 `book`

教材表：

- 书名；
- 出版社；
- 版本；
- 年级/册别；
- 必修/选择性必修/上下册；
- 课标版本。

### 5.2 `book_section`

教材章节树：

- `parent_section_id` 支持多级章节；
- `page_start` 和 `page_end` 支持章节页码范围；
- `sort_order` 控制展示顺序。

### 5.3 `book_exercise_question`

教材习题关系表：

- `page_number`：页码；
- `column_name`：栏目，例如例题、练习、习题、思考、探究；
- `exercise_number`：题号；
- `sub_number`：小题；
- `display_order`：教材内排序。

关键原则：

- 教材栏目必须保留，因为不同教材的组织方式不统一。
- 同一道题可同时来自试卷和教材。

## 5. 专题系统

### 6.1 `topic_module`

大专题，例如函数、解析几何、概率统计。

### 6.2 `topic`

小专题，属于某个大专题，可以有简介、导出文件名和专题级 TeX 引言。

当前关键字段：

- `file_name`：专题导出时优先使用的 TeX 文件名；
- `description`：专题用途或选题说明；
- `problem_intro_tex`：专题导出题目部分前插入的 TeX 片段；
- `answer_intro_tex`：专题导出答案部分前插入的 TeX 片段；
- `export_note`：专题导出备注，供后续模板或人工复核使用；
- `extra_json`：尚未稳定进入 schema 的专题扩展信息。

### 6.3 `topic_question`

专题题目关系表：

- `group_name`：专题内分组；
- `sort_order`：专题内排序；
- `topic_note`：该题在该专题下的备注。

关键原则：

- 专题备注独立于题目本体备注。
- 专题排序独立于题目本体。

## 6. 图片与附件

### 7.1 `question_asset`

题目资源表：

- `role`：`problem`、`answer`、`solution`、`source`、`thumbnail`。
- `file_path`：相对路径。
- `original_file_name`：原始文件名。
- `mime_type`：文件类型。
- `width`、`height`：图片尺寸。
- `file_hash`：去重和完整性检查。
- `caption`：说明。
- `sort_order`：同类资源排序。

推荐资源目录：

```text
assets/questions/Q000001/problem-1.png
assets/questions/Q000001/solution-1.png
assets/questions/Q000001/source-scan.pdf
```

## 7. 修订与导入

### 8.1 `question_revision`

记录每次题目变更：

- 人工修改；
- AI 修改；
- OCR 导入；
- 批量导入；
- 批量规范化；
- 迁移。

该表用于回滚、审计和定位问题。

### 8.2 `import_batch`

一次导入任务的批次表。记录来源、模式、开始时间、结束时间和摘要。

### 8.3 `question_import_draft`

AI/OCR/批量录入的题目草稿表。它与正式 `question` 分离，避免模型输出直接覆盖正式题库。

核心字段：

- `draft_id`：草稿 ID。
- `batch_id`：所属导入批次。
- `source_item_id` / `source_label`：原始材料中的题目标识。
- `proposed_action`：建议动作，例如 `insert`、`update`、`skip`。
- `target_question_id`：如果是更新已有题，指向目标题。
- `review_status`：`needs_review`、`ready`、`blocked`、`approved`、`rejected`。
- `review_reason`：为什么需要人工确认或被阻断。
- `stem_tex`、`choices_json`、`answer_tex`、`solution_tex`：AI/OCR 解析出的结构化内容。
- `confidence_json`：模型或 OCR 对字段的置信度。
- `validation_json`：LaTeX、字段完整性、图片引用等校验结果。
- `extra_json`：尚未稳定进入 schema 的扩展信息。

关键原则：

- `ready` 只代表字段初检通过，不代表自动进入正式库。
- 草稿确认入库时必须生成 `question_revision` 和 `import_report_item`。
- 任何缺少题干、更新目标不存在、图片路径不明确的记录都应进入 `blocked` 或 `needs_review`。

### 8.4 `question_import_draft_asset`

AI/OCR 草稿阶段的图片、扫描件、附件占位表。

它不直接写入 `question_asset`，因为草稿还没有正式 `question_id`，或尚未确认图片角色。

核心字段：

- `draft_id`：所属草稿。
- `role`：`problem`、`answer`、`solution`、`source`、`thumbnail`。
- `source_path`：原始图片或附件路径。
- `planned_file_path`：确认入库后的计划路径。
- `review_status`：图片是否需要人工确认。
- `note`：缺图、裁剪、重命名等说明。

### 8.5 `import_report_item`

导入批次中的每一条结果：

- 插入；
- 更新；
- 跳过；
- 失败；
- 待确认。

AI/OCR 导入必须先产出报告，再由用户确认写入。

## 8. 旧题库映射

### 9.1 `legacy_question_map`

连接旧 `.tex` 文件和新 `question_id`：

- `legacy_id`
- `legacy_file_path`
- `content_hash`
- `detected_chapter`
- `detected_year`
- `detected_source`
- `detected_question_number`
- `detected_topic`
- `scan_status`
- `scan_note`

这个表是迁移期最重要的安全网。只要它存在，就能从新库反查旧文件，也能从旧文件定位新题目。

