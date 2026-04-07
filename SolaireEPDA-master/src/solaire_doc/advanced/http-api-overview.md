# HTTP 接口总览（项目 / 题库 / 模板 / 组卷）

本文面向**开发者与助手**：列出本机 Web 服务常见 **`/api`** 前缀路由，便于编排自动化。默认 **JSON**，UTF-8；业务错误多为 `4xx/5xx` + `{"detail": "..."}`。所有路径均相对于**已绑定的项目根**（须先打开项目）。

**基础地址**：`http://127.0.0.1:<端口>`（以实际启动为准）。

---

## 1. 项目

| 方法 | 路径 | 作用 |
|------|------|------|
| POST | `/api/project/open` | 绑定项目根目录 |
| GET | `/api/project/info` | 当前是否已绑定、路径 |
| POST | `/api/project/create` | 新建项目目录 |
| POST | `/api/project/pick-open` / `pick-parent` | 图形环境下调系统选目录（若可用） |

---

## 2. 题库

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/bank/subjects`、`/api/bank/collections` | 科目、题集列表 |
| GET | `/api/bank/items` | 题目列表 |
| GET | `/api/bank/items/{qualified_id}` | 单题详情（路径需编码） |
| PUT/DELETE | `/api/bank/items/{qualified_id}` | 更新/删除 |
| POST | `/api/bank/items` | 新建题目 |
| POST | `/api/bank/import`、`import-bundle` | 合并 YAML / ZIP 交换包导入 |
| GET/POST | `/api/bank/export-bundle` | 导出交换包 |

`qualified_id` 形如：`科目/题集/题内id`。

---

## 3. 模板

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/templates` | 模板列表 |
| GET | `/api/templates/parsed` | 解析后的编辑器载荷（`path=` 模板路径） |
| GET/PUT | `/api/templates/raw` | 读写模板 YAML 原文 |
| POST | `/api/templates/create` | 创建最小模板 |

模板路径须落在项目 `templates/` 下。

---

## 4. 组卷与导出

| 方法 | 路径 | 作用 |
|------|------|------|
| POST | `/api/exam/validate` | 按当前选题与模板做校验 |
| POST | `/api/exam/export` | 校验通过后生成 PDF 等；可选 `overwrite_existing`（覆盖已有 `result/` 子目录） |
| POST | `/api/exam/export/check-conflict` | 请求体：`export_label`、`subject`；返回是否与已有导出记录冲突 |
| GET | `/api/exam/drafts` | 列出 `.solaire/drafts/` 中的组卷草稿 |
| POST | `/api/exam/drafts` | 保存新草稿 |
| GET | `/api/exam/drafts/{draft_id}` | 读取草稿全文 |
| PUT | `/api/exam/drafts/{draft_id}` | 更新草稿 |
| DELETE | `/api/exam/drafts/{draft_id}` | 删除草稿 |
| POST | `/api/exam/drafts/from-result/{exam_id}` | 从 `result/{exam_id}/exam.yaml` 生成草稿 JSON；**默认不落盘**。请求体可选 `persist`（`true` 时写入 `.solaire/drafts/`） |

请求体含 `template_ref`、`template_path`、`selected_items`；每项可选 `score_per_item`、`score_overrides`（题目完整编号 → 分值），与界面组卷一致。

---

## 5. 导出目录中的 PDF（`result/{exam_id}/`）

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/results/{exam_id}/pdf-file` | 查询参数 `variant=student`（默认）或 `teacher`；返回 `application/pdf`，`Content-Disposition: inline`，供浏览器新标签内嵌查看 |
| POST | `/api/results/{exam_id}/open-pdf` | 可选 JSON `{"variant":"student"|"teacher"}`；在本机后端用系统默认程序打开对应 PDF（无图形环境或无文件时返回错误说明） |

---

## 6. 其它通用

| 方法 | 路径 | 作用 |
|------|------|------|
| GET | `/api/health` | 健康检查 |
| GET | `/api/help/index`、`/api/help/page/{id}`、`/api/help/asset/...` | 应用内手册（`{id}` 与 `src/solaire_doc/help-manifest.json` 中 `id` 一致） |
| GET | `/api/resource/{path}` | 项目 `resource/` 下静态文件（如插图） |

---

## 7. 考试分析与学情诊断（摘要）

以下均为 **GET**，查询参数通常含 **`exam_id`**、**`batch_id`**（成绩批次），须先打开项目。

| 路径 | 作用 |
|------|------|
| `/api/analysis/diagnosis/knowledge` | 班级维度知识点薄弱排序等 |
| `/api/analysis/diagnosis/student` | 学生×知识点诊断；可选 `student_id`（学号），不传则全班 |
| `/api/analysis/diagnosis/class-heatmap` | 班级热力相关数据 |
| `/api/analysis/diagnosis/suggestions` | 教学建议与补讲优先级等草案 |

自定义脚本、内置工具、任务队列等另有 `/api/analysis/scripts`、`/api/analysis/jobs/*`、`/api/analysis/tools` 等路由，详见 `src/solaire/web/app.py`。

---

## 8. 智能助手（`/api/agent/*`）

路由定义于 `src/solaire/web/agent_api.py`，由 `app` 以前缀 **`/api`** 挂载，故完整路径形如 **`/api/agent/chat`**。

| 方法 | 路径 | 作用 |
|------|------|------|
| POST | `/api/agent/chat` | **SSE** 流式对话；请求体含 `message`、`session_id`（可选）、`mode`（`execute`/`suggest`）、`page_context`（可选）、`skill_id`（可选）、`confirm_*`（确认流）等 |
| GET/POST | `/api/agent/sessions`、`/api/agent/sessions/{id}`、`DELETE ...` | 会话列表、读取、创建、删除 |
| POST | `/api/agent/sessions/{id}/cancel` | 请求取消当前轮 |
| GET/PUT | `/api/agent/config`、`/api/agent/llm-settings`、`/api/agent/safety-mode` | 配置与策略（部分写入须已打开项目） |
| GET | `/api/agent/skills` | 内置技能列表 |
| GET/PUT | `/api/agent/memory`、`/api/agent/memory/topics`、`/api/agent/memory/{topic}` | 项目内记忆索引与主题正文 |
| POST | `/api/agent/upload` | 附件上传至项目 `.solaire/uploads/` |
| GET/PUT | `/api/agent/prompt-overrides` | 系统提示覆盖文件 |

**知识图谱** 的 REST 路由见「高级使用说明」中的 **图谱 HTTP 接口**篇。

更细的参数与边界情况可参考仓库 **`docs/dev/README.md`**（开发说明，与界面手册分工不同）。
