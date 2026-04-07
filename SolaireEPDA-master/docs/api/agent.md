# Agent API（M3）

面向教师的智能助手：自然语言编排分析、组卷校验/导出、知识图谱与跨会话记忆（索引 + 主题文件）。

## 环境变量（后端进程）

| 变量 | 说明 |
|------|------|
| `SOLAIRE_LLM_API_KEY` 或 `OPENAI_API_KEY` | 模型服务密钥 |
| `SOLAIRE_LLM_BASE_URL` 或 `OPENAI_BASE_URL` | 可选，兼容 OpenAI 的网关地址 |
| `SOLAIRE_LLM_MODEL` | 主模型，默认 `gpt-4o-mini` |
| `SOLAIRE_LLM_FAST_MODEL` | 可选，快模型（与主模型相同时可省略） |
| `SOLAIRE_LLM_MAX_TOKENS` | 可选，单次助手生成最大 token；未设置时默认 `4096`（亦可通过项目内 `llm_overrides` 覆盖） |

## 端点（前缀 `/api/agent`）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/config` | 是否已配置密钥、当前模型名等 |
| GET | `/llm-settings` | 当前生效的模型参数预览（访问密钥脱敏）；未打开项目时仍可读环境变量合并结果 |
| PUT | `/llm-settings` | 将参数写入当前项目的 `.solaire/agent/llm_overrides.json`（需已打开项目）；覆盖环境变量中的同名项 |
| GET | `/skills` | 内置快捷协助列表（`id` / `label` / `description` / `suggested_user_input`） |
| GET | `/sessions` | 列出当前项目下的会话摘要（含 `title`：首条用户话摘要） |
| POST | `/sessions` | 新建会话，返回 `session_id` |
| GET | `/sessions/{id}` | 会话详情（消息 JSON） |
| POST | `/sessions/{id}/cancel` | 请求停止当前进行中的助手生成（与前端中止配合） |
| DELETE | `/sessions/{id}` | 删除会话 |
| GET | `/memory` | 记忆索引 `INDEX.md` 全文 |
| PUT | `/memory` | 覆盖记忆索引，`{ "content": "..." }` |
| GET | `/memory/topics` | 主题笔记文件名列表（`topics/*.md`） |
| GET | `/memory/{topic}` | 主题文件（`.md`，可省略扩展名） |
| PUT | `/memory/{topic}` | 覆盖主题文件，`{ "content": "..." }` |
| POST | `/chat` | **SSE** 流式对话（见下） |

## POST `/chat`（SSE）

请求 JSON：

| 字段 | 类型 | 说明 |
|------|------|------|
| `session_id` | string? | 已有会话；省略则服务端新建 |
| `message` | string? | 用户输入；与 `confirm_action_id` 二选一必填 |
| `mode` | string | `execute`（默认）或 `suggest` |
| `confirm_action_id` | string? | 继续此前 `confirm_needed` 返回的操作 |
| `confirm_accepted` | bool? | 默认 `true`；`false` 表示取消 |
| `page_context` | object? | 教师当前 Web 界面上下文，写入系统提示「教师当前界面」一节（见下） |
| `skill_id` | string? | 内置技能标识（与 `GET /skills` 中 `id` 对应），收窄下发工具并注入简短工作流指引 |
| `execution_plan_path` | string? | 教师批准执行的计划文件项目内相对路径（与 `agent.exit_plan_mode` 的 `plan_file_path` 一致）；服务端据此重读文件并同步会话内任务步骤，并注入「计划执行」系统提示 |

`page_context` 可选字段：

| 字段 | 说明 |
|------|------|
| `current_page` | 模块标识：`compose` / `bank` / `template` / `graph` / `analysis` / `help` / `log` |
| `selected_resource_type` | 当前选中资源类型（如 `question`、`exam`、`graph_node`、`template_file`） |
| `selected_resource_id` | 对应标识（题号、考试 id、节点 id、模板路径等） |
| `summary` | 一句业务语言场景说明（展示给模型，宜用教师可读表述） |

响应：`text/event-stream`。首帧通常为 `event: session`，数据中含 `session_id`。事件在服务端产生后尽快推送（含模型流式输出时的多段 `text_delta`）。

常见事件：

- `thinking`：进度提示文案（`message`），供界面展示「正在…」类反馈  
- `text_delta`：助手正文片段  
- `tool_start` / `tool_result`：工具执行（子任务中 `tool_result` 可带 `subagent: true`）  
- `confirm_needed`：需教师确认（含 `action_id`）  
- `task_update`：多步任务清单变更，`steps` 为 `{ title, status }[]`（计划落盘或点「执行」时也会推送）  
- `plan_ready`：计划模式退出后已生成计划文件，含 `plan_file_path` 与正文摘要 `content`  
- `subagent_start` / `subagent_done`：子任务深度分析  
- `memory_updated`：已写入项目内记忆文件（含 `topics_changed` 文件名列表）  
- `memory_update_failed`：会话末自动写入记忆失败，`message` 为原因（同时会记入 `audit.jsonl`）  
- `done`：本轮结束，`usage` 为 token 统计（若提供商返回）；若用户停止可带 `cancelled: true`  
- `error`：错误信息（含用户停止时 `code: cancelled`）  

### 子任务（`agent.run_subtask`）与确认

子任务在**独立短对话**中执行，**无法弹出与主会话相同的人工确认卡片**。因此：需要教师确认的写入/破坏性工具若在子任务内被调用，子任务会中止并向模型返回错误说明，**应在主对话中完成确认类操作**，或先在主对话中批准同类写入后再尝试子任务（若护栏已登记会话内批准）。

## 磁盘布局（项目内）

- `.solaire/agent/sessions/*.json` — 会话  
- `.solaire/agent/memory/INDEX.md` — 记忆索引（提示性质，助手需用工具核对）  
- `.solaire/agent/memory/topics/*.md` — 主题记忆（含 `analysis_history.md`、`session_digest.md` 等由助手维护的笔记）  
- `.solaire/agent/audit.jsonl` — 工具调用审计  

## 工具目录（摘要）

- `analysis.*` — 与 `edu_analysis` 一致（数据集、内置流水线、脚本、作业查询）  
- `exam.*` — 模板列表/预览、校验、导出 PDF；`exam.validate_paper` 可选 `include_latex_check`（与导出一致的版式编译试跑，需本机已安装 TeX 工具链）、`include_math_static`（题干等字段的静态提示：数学定界符 `$`/`$$`、正文中的 `_`/`^`/`%` 等易致 LaTeX 报错之情形，默认开启）  
- `bank.*` — 题库检索、读取/新建/修改独立题目（题组请在界面编辑）  
- `graph.*` — 知识图谱节点/关系/绑定/资料挂载  
- `memory.*` — 读取索引、读取/搜索主题  
- `agent.set_task_plan` / `agent.update_task_step` — 本会话多步任务登记与进度更新  
- `agent.run_subtask` — 子任务隔离分析（仅返回精简结论到主对话）  
