# 题库数据清洗与命名规范计划

> 状态：执行准备版  
> 目标：对现有 800+ 道题做重复题、来源命名、文理/新高考标注、字段完整性的系统清洗。  
> 原则：先审计、再确认、后写库；不直接批量删除题目，不把本地正式库提交到 GitHub。

## 1. 当前新数据存储位置

新的结构化题库数据存放在本机 SQLite 数据库：

- 正式库：`data/mathcyclus.sqlite3`
- 本机 UI 偏好：`data/local_preferences.json`
- 题目图片资源：`assets/questions/<question_id>/`
- 本地审计报告：`reports/`
- 导出文件：`exports/`

其中 `data/mathcyclus.sqlite3`、`data/local_preferences.json`、`assets/questions/*`、`reports/*`、`exports/*` 都属于本地私有数据或运行产物，默认不提交 GitHub。

## 2. 清洗对象

### 2.1 题目身份

- `question.question_id`：SQLite 内部主 ID，例如 `Q000184`。
- `question.legacy_id`：旧系统题目 ID，仅保留映射用途。
- `question.legacy_file_path` / `legacy_question_map.legacy_file_path`：旧 `chapters/` 下 `.tex` 文件路径。
- `question.canonical_tex`：从结构化字段导出的兼容版 TeX。

后续前端和新功能应优先使用 `question_id`；旧 TeX 文件路径只作为迁移、回溯和兼容导出依据。

### 2.2 来源身份

试卷来源主要拆分为：

- `paper.year`：年份；
- `paper.paper_series`：卷类/来源大类，如 `G`、`M`、`QJ`；
- `paper.track`：`文科`、`理科`、`新高考`、`综合`；
- `paper.paper_name`：标准显示名；
- `paper.source_name`：原始来源名；
- `paper_question.question_number`：题号；
- `paper_question.sub_number`：小题号。

未来教材、专题和图片来源不应该塞进 `paper`，而应通过 `book_*`、`topic_*`、`question_asset` 等关系表表达。

## 3. 命名规范草案

### 3.1 题目 ID

- 新库统一使用 `Q` + 6 位数字，例如 `Q000001`。
- 不用年份、题号、知识板块拼接主键，因为同一道题可能来自多张卷、教材或专题。
- 旧文件名和旧 ID 不再作为唯一身份，只作为来源映射。

### 3.2 试卷命名

推荐规范：

```text
year + paper_series + track + paper_name + question_number + sub_number
```

例如：

- `2021 / G / 新高考 / 新高考I卷 / 7`
- `2008 / G / 文科 / 全国卷 / 9`
- `2011 / G / 理科 / 浙江卷 / 22`

注意：

- `paper_name` 尽量不带 `（文）`、`（理）`；
- 文理信息进入 `track`；
- 原始文件里含 `（文、理）` 的情况通常先标为 `综合`，不要强行拆为文科或理科；
- 不自动合并 `全国I卷` 与 `全国卷I`、`新课标I卷` 与 `新高考I卷`，除非人工确认。

### 3.3 题目来源关系

同一道题如果同时出现在高考卷、教材、模考卷、专题中，应保留一个 `question`，然后挂多条来源关系：

- 高考/模考：`paper_question`
- 教材：`book_exercise_question`
- 专题：`topic_question`
- 图片/原图：`question_asset`
- 等价/近似关系：`question_equivalence`

不要通过复制题目来表达多来源；复制会导致后续改题、导出、标签维护都变复杂。

## 4. 清洗流程

### 4.1 批次 A：重复题与等价关系

目标：

- 找出题干完全相同的题；
- 找出高度相似但不完全相同的题；
- 人工判断是同题、多来源、改编题，还是只是相似。

处理规则：

- 不直接删除；
- 同题优先登记 `question_equivalence`；
- 如果确认只是同一道题被不同知识板块重复收录，应保留一个主题目，并把来源、知识点挂到同一个 `question_id`；
- 如果文科/理科同题但出现在不同卷里，可以保留同一个题目，多挂两条 `paper_question`。

### 4.2 批次 B：来源关系修复

目标：

- 修复没有 `paper_question` 的题；
- 修复题号与旧路径解析不一致的题；
- 确认同一试卷同一题位是否重复。

处理规则：

- 优先从 `legacy_file_path` 反推年份、卷类、试卷名、题号；
- 无法反推时写入人工复核清单；
- 不自动创建模糊试卷名，避免来源污染。

### 4.3 批次 C：试卷命名与文理标注

目标：

- 标准化 `paper_name`；
- 统一 `track`；
- 保留 `source_name` 作为原始记录。

处理规则：

- `paper_name` 去除末尾 `（文）` / `（理）`；
- `track` 承接 `文科` / `理科` / `新高考` / `综合`；
- 特殊情况进入人工映射表，不让脚本自作主张。

### 4.4 批次 D：难度、标签、备注

目标：

- 补齐 `difficulty`；
- 补齐 `tags_json`；
- 清理明显错误备注。

处理规则：

- 难度建议先由 AI 批量初判，再人工抽检；
- 标签优先来自知识板块和题型，再叠加 AI 语义标签；
- 备注只记录确实有用的信息，不把来源信息重复写入备注。

### 4.5 批次 E：答案、解析、图片资源

目标：

- 补齐 `answer_tex` 和 `solution_tex`；
- 整理非 TikZ 图片；
- 建立图片与题目的稳定关系。

处理规则：

- 图片文件进入 `assets/questions/<question_id>/`；
- 图片元信息进入 `question_asset`；
- 多图通过 `sort_order` 排序；
- TeX 中引用 `\questionasset{alias}`，导出时再解析为真实文件路径。

## 5. 审计命令

推荐先运行：

```bash
python scripts/audit_data_cleanup_candidates.py --db data/mathcyclus.sqlite3 --stamp manual_cleanup
python scripts/precommit_database_audit.py --db data/mathcyclus.sqlite3 --stamp manual_cleanup
python scripts/audit_sqlite_legacy_bridge.py --no-report
python scripts/audit_legacy_sqlite_consistency.py --no-report
```

如果当前命令行不是项目虚拟环境，优先使用：

```bash
.\.venv\Scripts\python.exe scripts/audit_data_cleanup_candidates.py --db data/mathcyclus.sqlite3 --stamp manual_cleanup
```

## 6. 写库原则

- 每次清洗前先备份 `data/mathcyclus.sqlite3`。
- 每一批只处理一类问题，不混合改动。
- 自动脚本默认 dry-run，只有显式 `--apply` 才允许写库。
- 写库后必须生成报告并写入 `question_revision`。
- 正式库不进 Git，只提交脚本、文档、schema、迁移工具。

## 7. 下一步建议

1. 先复核 `reports/data_cleanup_candidates_*.md` 中的精确重复和高相似候选。
2. 确认哪些题是“同题多来源”，哪些题是“相似但不同题”。
3. 再写一个 `question_equivalence` 复核包，让你在 CSV/页面中确认处理意见。
4. 最后按批次写入数据库，避免一次性大范围误改。
