# PDF 试题导入与图片切分流程设计

> 状态：规划补充，暂不改代码  
> 目标：为后续“试卷 / 教材 / 专题 PDF → SQLite 草稿 → 人工确认入库”建立清晰流程，降低 AI 幻觉、减少 token 消耗，并保留原始材料可回溯。

## 1. 设计原则

- PDF 导入不能直接写入正式 `question` 表，必须先进入草稿链路。
- 原始 PDF、切页图、题内图片、版面解析 JSON 都属于本地私有数据，不上传 GitHub。
- AI 只负责“结构化理解与补全”，不负责单独决定正式入库。
- 图片优先由版面解析工具切分，再登记到草稿资源表，避免让大模型凭记忆或模糊截图重画。
- 每道题最终仍走现有 SQLite 题目结构：题干、选项、答案、解析、来源关系、图片资源、修订记录。
- 旧 `problem` 命令兼容由导出器负责，数据库内部不强行保存旧 TeX 文件头。

## 2. 推荐技术路线

推荐采用分层管线：

```text
PDF 原件
  ↓
PDF 版面解析层（MinerU 优先，pdf2md / PyMuPDF 兜底）
  ↓
页面级中间件（页码、文本块、公式块、图片块、坐标）
  ↓
题目切分层（按题号 / 小题 / 栏目 / 页码切题）
  ↓
AI 结构化校订层（补 TeX、识别题型、标签、难度、答案解析）
  ↓
SQLite 草稿层（question_import_draft + question_import_draft_asset）
  ↓
人工审核与确认入库
```

## 3. MinerU 与 pdf2md 的定位

### 3.1 MinerU

MinerU 更适合作为主解析器：

- 输出版面结构，能区分文本、公式、图片、表格、页眉页脚等区域；
- 有利于按题号、页码、栏目、图文位置切分题目；
- 能把 PDF 中的原图切出来，后续直接作为题目图片资源；
- 对教材、讲义、试卷这类混合排版材料更稳。

### 3.2 pdf2md

pdf2md 更适合作为轻量兜底：

- 对纯文字或简单公式 PDF，可快速生成 Markdown；
- 对复杂双栏、图片、图文混排材料，容易丢失坐标和图片关系；
- 不建议作为唯一主链路。

### 3.3 PyMuPDF

PyMuPDF 适合作为底层辅助：

- 渲染整页截图；
- 裁剪页面局部区域；
- 获取页码、图片对象、坐标；
- 在 MinerU 输出不完整时做二次补救。

## 4. 本地文件结构建议

PDF 导入过程会产生大量中间文件，应全部放入本地私有目录。

建议目录：

```text
data/imports/
  pdf_jobs/
    <job_id>/
      source.pdf
      job_manifest.json
      mineru_output/
      pages/
        page_001.png
        page_002.png
      crops/
        page_001_q03_region_01.png
      extracted_assets/
        QDRAFT_0001_figure_01.png
        QDRAFT_0001_figure_02.png
      draft_payload.json
      import_report.md
```

原则：

- `data/imports/**` 必须被 `.gitignore` 保护；
- `job_id` 建议使用时间戳加短 hash，例如 `pdf_20260904_153012_a1b2c3`；
- 原始 PDF 保存在 job 内，方便日后回溯；
- 切出的图片先在 job 内暂存，正式入库后再复制到 `assets/questions/<question_id>/`；
- 所有路径在数据库里尽量保存相对路径，方便本地迁移包跨电脑恢复。

## 5. 数据库映射方案

### 5.1 导入批次

每次 PDF 导入创建一条 `import_batch`：

- `source_type`：`pdf_paper` / `pdf_book` / `pdf_topic` / `pdf_misc`；
- `source_path`：原始 PDF 相对路径；
- `summary`：导入说明；
- `created_at`：导入时间；
- `extra_json`：解析器版本、页数、解析策略、用户选择。

### 5.2 题目草稿

每道切出的题进入 `question_import_draft`：

- `source_item_id`：例如 `page_12_q_03`；
- `source_label`：例如 `第12页 第3题` 或 `2025 全国II卷 第3题`；
- `proposed_action`：默认 `insert`；
- `review_status`：默认 `needs_review`；
- `stem_tex`、`choices_json`、`answer_tex`、`solution_tex`：结构化内容；
- `difficulty`、`tags_json`、`note`：AI 建议值，但必须可人工修改；
- `raw_source_text`：版面解析出的原始文本；
- `confidence_json`：每个字段的置信度；
- `extra_json`：页码、题号、小题、坐标、栏目、解析器块 ID。

### 5.3 图片草稿

每张题内图片进入 `question_import_draft_asset`：

- `role`：`problem_image` / `solution_image` / `source_page_crop` / `unknown`；
- `file_path`：job 内暂存图片路径；
- `original_file_name`：从 PDF 或裁剪规则生成；
- `caption`：建议命名，例如 `figure_01`、`diagram_02`；
- `sort_order`：同一题内图片顺序；
- `extra_json`：页码、坐标、来源块 ID、裁剪区域。

正式入库时再转入 `question_asset`：

- 复制图片到 `assets/questions/<question_id>/`；
- 生成稳定文件名；
- 写入 `question_asset`；
- 在题目 TeX 中插入或保留 `\questionasset{figure_01}` 这类引用。

## 6. 题目切分策略

### 6.1 试卷 PDF

试卷适合按以下字段切分：

- 年份；
- 卷别；
- 文/理科/新高考；
- 试卷名称；
- 题号；
- 小题；
- 页码；
- 坐标区域。

推荐流程：

1. 用户先填写或选择试卷级来源信息；
2. 系统解析 PDF 页；
3. 按题号正则初步切分；
4. 遇到跨页题时合并相邻页面区域；
5. AI 校订每题的题干、选项、答案、解析；
6. 用户在草稿审核页确认题号、小题和来源关系。

### 6.2 教材 PDF

教材必须保留页码和栏目，因为同一页可能有例题、练习、复习题、拓展题。

推荐字段：

- 书名；
- 册别；
- 章节；
- 小节；
- 页码；
- 栏目；
- 题号；
- 小题；
- 坐标区域。

切分时不要只依赖题号，因为教材里经常出现重复题号。

### 6.3 专题 PDF

专题材料结构不一定稳定，建议用户先给一个专题目录目标：

- 大专题；
- 小专题；
- 分组名称；
- 导出引言；
- 题目排序规则。

导入后题目先进入专题草稿，确认后再写 `topic_question` 关系。

## 7. AI 使用策略

AI 不应该直接吃完整 PDF。推荐只把必要块发送给模型：

- 当前题目的文本块；
- 当前题目的局部截图；
- 当前题目的图片资源清单；
- 上下相邻少量上下文；
- 用户提供的来源信息。

提示词输出应尽量是 JSON：

```json
{
  "stem_tex": "",
  "choices": [],
  "answer_tex": "",
  "solution_tex": "",
  "question_type": "",
  "difficulty": 3,
  "tags": [],
  "asset_refs": [
    {
      "caption": "figure_01",
      "insert_position": "stem",
      "tex_ref": "\\questionasset{figure_01}"
    }
  ],
  "confidence": {
    "stem_tex": 0.92,
    "answer_tex": 0.76,
    "asset_refs": 0.88
  },
  "warnings": []
}
```

这样可以减少 token，并且让模型基于原始块校订，而不是从整页截图中自由发挥。

## 8. 前端 UI 方案

建议先作为 `录入问题` 的一个子入口：

```text
录入问题
  ├─ 单题录入
  ├─ 批量试题录入
  ├─ 同卷试题录入
  ├─ 同书试题录入
  └─ PDF 导入草稿
```

### 8.1 PDF 导入草稿页

左侧：

- 上传 PDF；
- 选择导入类型：试卷 / 教材 / 专题 / 零散材料；
- 填写来源级元数据；
- 选择解析器：MinerU / pdf2md / PyMuPDF 页面截图；
- 开始解析按钮；
- 解析批次列表。

中间：

- 页码预览；
- 题目切分结果；
- 每题状态：待审核 / 可入库 / 阻塞；
- 图片资源数量；
- 置信度和 warning。

右侧：

- 当前题原 PDF 局部截图；
- AI 生成的 TeX；
- 渲染预览；
- 图片资源预览与命名；
- 保存草稿 / 标记 ready / 提交入库。

### 8.2 图片命名交互

每拖入或自动切出一张图时，应出现可编辑命名框：

- 默认名：`figure_01`、`figure_02`；
- 可改名：例如 `graph_parabola`、`geometry_auxiliary`；
- 同一题内 caption 必须唯一；
- 排序由 `sort_order` 控制；
- 题干中引用 `\questionasset{caption}`；
- 多图按 `sort_order` 在资源面板中排序。

## 9. 降低幻觉与节省 token 的关键点

- 先由版面解析工具提取文本和图片，再让 AI 校订，不让 AI 从整页图硬猜。
- 每次只给模型一个题目块，不给整本 PDF。
- 对公式密集区域，只给局部截图加文本块。
- 对图片，优先登记原图，不要求 AI 重绘。
- 对页眉页脚、版权、水印、目录等块，在进入 AI 前过滤。
- 对模型输出使用 JSON schema 校验，不合格则标记 `needs_review`。
- 对低置信度字段在 UI 中高亮，而不是自动入库。

## 10. 实施顺序

不建议马上做完整 PDF 入库。建议按以下阶段推进：

1. **P0：规划与本地目录**
   - 确认 `data/imports/` 本地私有目录；
   - 补 `.gitignore` 和初始化脚本；
   - 只做文档和空目录，不接入前端。

2. **P1：解析器适配层**
   - 新增 `services/pdf_import_service.py`；
   - 定义统一中间格式；
   - 先支持 PyMuPDF 页面渲染和简单文本提取；
   - MinerU 作为可选外部依赖，不强制安装。

3. **P2：PDF → 草稿 dry-run**
   - 从 PDF 生成 `draft_payload.json`；
   - 写入临时预览库或 job 文件；
   - 不写正式 SQLite。

4. **P3：草稿审核 UI**
   - 接入 `录入问题 → PDF 导入草稿`；
   - 支持逐题审核、图片命名、局部预览；
   - 支持批量标记 ready。

5. **P4：正式入库**
   - 复用现有 `commit_draft_to_question()`；
   - 入库前自动备份数据库；
   - 图片转存到 `assets/questions/<question_id>/`；
   - 写入 `question_revision` 与 `import_report_item`。

6. **P5：MinerU 深度接入**
   - 如果本地检测到 MinerU，则启用结构化解析；
   - 如果没有 MinerU，继续保留 PyMuPDF / 手动截图兜底；
   - 文档中说明安装方式和失败回退。

## 11. 风险与边界

- MinerU 可能引入较重依赖，不应放进基础启动器的必装路径。
- PDF 版权材料属于用户本地数据，不能进入 GitHub 或源码包。
- 不同试卷和教材排版差异很大，不能假设一次切分 100% 正确。
- 手写扫描 PDF 仍可能需要 OCR 或视觉模型辅助。
- 图片裁剪区域需要保留人工调整入口，否则容易裁错。
- PDF 导入不应阻塞现有单题录入、SQLite 浏览、组卷和专题收录。

## 12. 推荐结论

PDF 导入值得做，但应作为“草稿生成器”接入，而不是直接替代当前录入流程。最稳妥的路线是：

- 先把 PDF 拆成可回溯的页面、文本块和图片块；
- 再用 AI 把每道题整理成结构化草稿；
- 最后由用户审核入库。

这样能同时兼顾准确性、token 成本、图片资源管理和未来迁移打包边界。
