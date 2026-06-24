# 高中数学题库管理系统 - 深度架构剖析与开发规范白皮书

本文档详细记录了题库项目的底层设计、各文件的内部逻辑、Streamlit 状态管理机制、核心数据流向以及严苛的 LaTeX 排版与 AI 开发规范。供项目深度维护与二次开发时查阅。

---

## 一、 项目全局技术栈与数据流
- **前端框架**：Streamlit (通过 `st.markdown`, `st.components.v1.html` 等实现自定义 UI)
- **渲染引擎**：基于 Python `re` 预处理 + Streamlit 内置 KaTeX/MathJax 混合渲染
- **数据持久化**：以 `.tex` 纯文本文件存储题目，配合 `题库索引表.csv` 实现 O(1) 级查询加速
- **AI 赋能**：对接 Qwen (如 `qwen3.6-flash`, `qwen-max`) 模型 API，执行结构化 OCR 解析、题目打标签、生成规范解答等任务

---

## 二、 核心文件深度剖析

### 1. 核心路由与主控制台：`question_bank_app.py`
这是整个系统的心脏，长达数千行，集成了路由分发、业务流转、AI 交互与绝大多数 UI 绘制。

#### 1.1 页面路由分发 (`main()` 与 `menu_options`)
- 侧边栏使用 `option_menu` 进行页面导航。
- 对应六大核心视图：
  1. `page_dashboard()`: 数据统计台（调用 `charts.py` 渲染热力图、活动曲线）。
  2. `page_single_entry()`: 单题录入（包含 OCR 剪贴板识别、AI 规范化、自动分配全局唯一 ID、自动写回磁盘）。
  3. `page_browse()`: 全局浏览与编辑（核心查阅页，包含高级检索、行内编辑、标签修改、AI 解答生成面板）。
  4. `page_exam_paper()`: 智能组卷服务（“购物车”逻辑，管理 `st.session_state["exam_selected_qs"]`）。
  5. `page_batch_tools()`: 工具箱（ZIP 上传、文件夹批量处理、题库索引重建）。
  6. `page_advanced_search()`: 独立的三级查找页（复用 `render_advanced_search_inline` 组件）。

#### 1.2 AI 解题核心链路 (`call_ai_for_answer_solutions` 及周边)
这是最容易踩坑的模块，处理从请求到写回的完整生命周期：
- **`call_ai_for_answer_solutions(problem_tex)`**:
  - 强制 AI 输出严格的 JSON 格式（`answer_tex` 和 `solutions_tex`）。
  - **核心痛点**：LaTeX 的反斜杠 `\` 会被 JSON 解析器当做控制字符转义（例如 `\frac` 被转成换页符 `\f`，`\neq` 被转成换行符加 `eq`）。
  - **解决方案**：提示词中强制要求 AI 使用双反斜杠 `\\`，同时在解析后调用 `_repair_latex_from_json_escapes` 进行兜底修复。
- **`_normalize_ai_generated_tex_for_preview(text)`**:
  - 在前端预览渲染前，强制去除 AI 可能带入的 Markdown 代码块符号（```），修正 `$$` 不独占一行导致的渲染崩溃，以及把错误的 `$\boxed{D}$` 强转为 `\boxed{D}`。
- **`_apply_generated_answer_solutions_to_file(..., mode="replace"|"append")`**:
  - **替换模式**：正则精准定位并替换原 `answer` / `solutions`，若无则追加到 `\end{problem}` 之后。
  - **追加模式 (另解)**：通过正则定位**文件末尾最后一个** `\end{solutions}`，在其后追加带有可选参数的新解答环境 `\begin{solutions}[另解/法二]`。

---

### 2. 渲染与文本解析引擎：`utils/latex_ops.py`
该文件负责将干瘪的 `.tex` 源码“变魔术”般转化为前端可漂亮展示的 Markdown/HTML 混合代码。

#### 2.1 核心渲染管线 (`latex_to_markdown`)
- **`problem` 环境解析**：正则提取 `\begin{problem}{年份}{类型}{试卷名}{题号}{板块}`，转化为 `**【2024 全国甲卷，10】**` 形式的加粗标题。
- **`choices` 选项排版**：正则分割 `\choice`，自动生成带有 `Times New Roman` 正体样式的 `A. B. C. D.` 前缀。
- **解答环境多态渲染**：
  - 匹配 `\begin{answer}` -> 转换为 `**【答案】**`
  - 优先匹配 `\begin{solutions}[参数]` -> 转换为 `**【参数】**` (如 `**【另解】**`)
  - 退化匹配 `\begin{solutions}` -> 转换为 `**【解答】**`
- **细节装饰器**：
  - `\circled{}` -> 转换为带有内联 CSS 的圆圈 `<span>`。
  - `\boxed{}` -> 转换为带灰色边框、微圆角、加粗的 `<span>`（`border: 1px solid #c9d1d9; padding: 2px 6px; border-radius: 4px; font-weight: bold;`）。
- **图片挂载**：针对 `\input{...}` 和 `\begin{tikzpicture}`，自动调用 `tikz_ops.py` 编译出 base64 图片并使用 `<img>` 标签嵌入。

#### 2.2 元数据管理 (`parse_meta_data`, `inject_meta_data`)
- 处理文件头部的隐式数据库：
  ```latex
  % === Begin Label Data ===
  % ID: 1024
  % 难度星级: 3
  % 标签: 集合，函数
  % === End Label Data ===
  ```
- 提供字典和 LaTeX 注释块之间的双向无损转换。

---

### 3. 数据可视化层：`utils/charts.py`
为避免主程序过于臃肿，将所有 ECharts (Apache) 的海量 HTML/JS 字符串模板抽离至此。

#### 3.1 GitHub 风格热力图 (`generate_heatmap_html`)
- 基于过去半年的录入数据，通过 JS 动态计算按周排列的热力图。
- 难点在于 Tooltip 的悬浮事件绑定与跨月跨年的坐标轴对齐。

#### 3.2 24小时活动曲线 (`generate_activity_curve_html`)
- 将 `0-23` 小时的录入次数映射为正弦波或折线图。
- **踩坑记录**：原本为了曲线闭合，将 `x=24` 的数据复制为 `x=0` 的数据，导致悬浮提示出现 00:00-00:59 的重复统计。目前已**严格截断至 `0-23` 循环**。
- 支持 🌅 ☀️ 🌇 🌙 的气象图标散点标记（通过 ECharts 的额外 scatter series 实现）。

---

### 4. 检索与索引核心：`utils/csv_ops.py` & `utils/file_ops.py`
由于直接遍历几千个 `.tex` 文本做正则搜索会导致 UI 严重卡顿，项目引入了 CSV 缓存层。

- **`init_csv_index.py` / `csv_ops.py`**:
  - 将所有文件的核心元数据（ID、路径、年份、板块、试卷名）提取并序列化到 `utils/题库索引表.csv`。
  - 在新增、修改标签、修改文件名时，通过 `update_csv_index_for_edit` 进行增量更新，维持 O(1) 级的检索速度。
- **`file_ops.py`**:
  - 提供 `get_all_tex_files` 遍历方法。
  - 提供文件标签提取与重命名封装。

---

## 三、 Streamlit 状态管理与 UI 踩坑指南 (Gotchas)

在 Streamlit 这个基于“每次操作从头执行脚本”的框架中，我们沉淀了以下血泪教训：

### 3.1 `StreamlitDuplicateElementKey` 错误防范
- **症状**：在“全局浏览”和“三级查找”中展示同一个题目时，如果按钮或评分组件的 key 仅使用 `file_path`，会因页面重复渲染同一组件而崩溃。
- **规范**：组件 key 必须**全局唯一**。
  - 标准做法：`fhash = hashlib.md5(fpath.encode()).hexdigest()[:8]`
  - 组件 key：`key=f"ai_sol_gen_{fhash}_{key_prefix}"`

### 3.2 只读文本框 (`text_area`) 更新不刷新的幽灵 Bug
- **症状**：点击“替换解答”或“保存修改”后，右侧 Markdown 渲染已更新，但左侧只读的 `st.text_area("源码", disabled=True)` 里依然显示老代码。
- **原因**：Streamlit 对具有相同 key 的组件有内部缓存机制，如果 key 不变，即使传入新的 `value` 也可能被丢弃。
- **规范**：**必须绑定文件修改时间戳**。
  - `mtime_token = int(os.path.getmtime(fpath))`
  - `st.text_area("源码", value=content, disabled=True, key=f"readonly_{fhash}_{mtime_token}")`

### 3.3 性能陷阱与 Rerun 优化
- **避免内联函数定义**：严禁在 `for fpath in files:` 的主循环中定义 `def` 函数，会导致每次 Rerun 产生极大的内存开销和 GC 压力，**一律改用 `lambda` 或提取到模块顶层**。
- **Session State 依赖**：表单组件不能既设定 `value=xxx` 又关联 `key="session_key"`，否则控制台会疯狂报黄色 Warning。必须在初始化时注入 state，表单仅绑定 key。

---

## 四、 严苛的 LaTeX 排版与 AI 开发规范

这些规范不仅用于约束人类开发者，更是通过 `ocr_prompt.txt` 强制约束 AI 生成内容的**绝对底线**。

### 4.1 数学模式与符号（零容忍区）
1. **行内/行间公式**：
   - 行内必用 `$ $`，行间必用 `$$ $$`（`$$` 必须独立成行，且内部公式也必须独立成行）。
   - **绝对禁止**使用 `\(\)` 或 `\[\]`，渲染引擎无法识别。
2. **强制 `\displaystyle`**：
   - 一旦公式内出现 `\frac`, `\sum`, `\prod`，必须强制在前面加 `\displaystyle`（包括行内公式）。
3. **自适应括号与特殊字符**：
   - 包含分式的括号必须用 `\left( \right)` 和 `\left[ \right]`。
   - 平行符号禁止写 `//`，必须写 `\mathop{//}`。
   - 带圈数字禁止直接打特殊字符 ①②③，**必须无条件写为 `\circled{1}`、`\circled{2}`**。
   - 孤立的阿拉伯数字和英文字母（如 1, A, x）必须用 `$ $` 包裹（即 `$1$`, `$A$`, `$x$`）。

### 4.2 标点、空格与段落排版
1. **间距规则**：
   - 中文文字与数学公式（`$ $` 或 `$$ $$`）交界处，**必须强制加一个半角空格**（如 `若函数 $ f(x) $ 满足`）。
2. **句号的中英自动切换**：
   - 纯中文结尾正常用中文句号 `。`
   - **紧跟在数学公式后面的句号，必须严格使用英文句号 `.`**（如 `解得 $ x=1 $.`）。
3. **段落与环境控制**：
   - 每个完整的推理步骤之间必须**空一空行**。
   - 题目小问禁止使用 `\begin{enumerate}`，直接在文本开头写 `(1)`、`(2)` 即可。
   - 严禁使用 `\begin{cases}` 的替代杂牌写法，必须规范使用。

### 4.3 Python 字符串安全规范
在任何需要做正则替换、路径拼接或生成 LaTeX 模板的 Python 脚本中：
- 只要涉及 LaTeX 命令（如 `\begin`, `\frac`），**必须**使用 Raw String（`r"..."`）或 Raw F-String（`fr"..."`）。
- 若漏加 `r`，诸如 `\begin` 中的 `\b` 会被 Python 编译为退格符，导致输出变为 `egin`，这在过去的迭代中引发过致命渲染错误，必须牢记。
