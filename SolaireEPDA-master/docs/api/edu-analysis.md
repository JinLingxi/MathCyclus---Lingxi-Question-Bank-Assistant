# EduAnalysis API 对接说明

本文档描述当前 `EduAnalysis` 的人工 API 与 Agent 工具契约映射关系，便于前端、自动化脚本与 Agent harness 对接。

## 总览

- 基础路径：`/api/analysis/*`
- 设计原则：
  - 人工 API 与工具能力同构
  - 输出以结构化 JSON 为主
  - `run_script` 采用最小安全执行器（Python 子进程隔离 + 超时 + 受限导入）

## 工具契约与 API 映射

| 工具名 | 人工 API | 说明 |
| --- | --- | --- |
| `analysis.list_datasets` | `POST /api/analysis/tools/analysis.list_datasets` | 列出可分析数据集（考试结果） |
| `analysis.list_builtins` | `POST /api/analysis/tools/analysis.list_builtins` | 列出内置分析器 |
| `analysis.run_builtin` | `POST /api/analysis/jobs/builtin` 或 tool 调用 | 运行内置分析任务 |
| `analysis.save_script` | `POST /api/analysis/scripts` 或 tool 调用 | 保存/更新脚本 |
| `analysis.run_script` | `POST /api/analysis/jobs/script` 或 tool 调用 | 运行脚本任务（受限执行） |
| `analysis.get_job` | `GET /api/analysis/jobs/{job_id}` 或 tool 调用 | 查询任务及输出 |

## API 详情

### 1) 获取工具清单

- `GET /api/analysis/tools`
- 响应示例：

```json
{
  "tools": [
    {
      "name": "analysis.run_builtin",
      "description": "Run a builtin analyzer and return a job.",
      "input_schema": { "type": "object" },
      "output_schema": { "type": "object" }
    }
  ]
}
```

### 2) 通用工具调用入口

- `POST /api/analysis/tools/{tool_name}`
- 请求体：

```json
{
  "arguments": {
    "builtin_id": "builtin:exam_stats_v1",
    "exam_id": "2025期末考试",
    "batch_id": "xxxx",
    "recompute": true
  }
}
```

### 3) 脚本管理

- `GET /api/analysis/scripts`：脚本列表
- `POST /api/analysis/scripts`：保存脚本
- `GET /api/analysis/scripts/{script_id}`：脚本详情
- `DELETE /api/analysis/scripts/{script_id}`：删除脚本

保存脚本请求示例：

```json
{
  "script_id": "optional",
  "name": "学情分析草稿",
  "language": "python",
  "code": "print('hello')"
}
```

响应示例：

```json
{
  "script": {
    "script_id": "9d8...",
    "name": "学情分析草稿",
    "language": "python",
    "code": "print('hello')",
    "created_at": "2026-03-31T00:00:00+00:00",
    "updated_at": "2026-03-31T00:00:00+00:00"
  }
}
```

### 4) 任务运行与查询

- `POST /api/analysis/jobs/builtin`
- `POST /api/analysis/jobs/script`
- `GET /api/analysis/jobs?limit=50`
- `GET /api/analysis/jobs/{job_id}?include_output=true`
- 两类运行接口均支持可选 `request_id`（幂等重试键）
- 脚本执行器默认限制（当前实现）：`timeout_seconds=6`、`max_output_bytes=20000`、`max_cpu_seconds=6`、`max_memory_mb=256`、并发上限 `2`

运行内置分析请求示例：

```json
{
  "builtin_id": "builtin:exam_stats_v1",
  "exam_id": "2025期末考试",
  "batch_id": "f4a1...",
  "recompute": true,
  "request_id": "req-20260401-001"
}
```

运行内置分析响应示例：

```json
{
  "job_id": "2a1f...",
  "status": "succeeded",
  "output": {
    "summary": { "title": "内置考试统计分析", "status": "succeeded" },
    "tables": [],
    "chart_specs": [],
    "series": []
  }
}
```

脚本任务响应示例：

```json
{
  "job_id": "4f8c...",
  "status": "failed",
  "error_code": "resource_exceeded",
  "output": {
    "summary": { "title": "脚本分析结果", "status": "failed" },
    "tables": [],
    "chart_specs": [],
    "series": [],
    "logs": ["..."],
    "warnings": [],
    "limits_applied": {
      "timeout_seconds": 6,
      "max_output_bytes": 20000,
      "max_cpu_seconds": 6,
      "max_memory_mb": 256
    },
    "truncated": true,
    "killed_reason": "output_limit"
  }
}
```

## 错误语义

- `400`：参数不合法、工具名无效、内置分析器 ID 无效、沙箱违规
- `404`：脚本不存在、任务不存在、考试/批次不存在
- `500`：服务内部异常
- 脚本错误码（`error_code`）：`timeout`、`sandbox_violation`、`runtime_error`、`resource_exceeded`

典型错误响应：

```json
{
  "detail": "Job not found: xxx"
}
```

## 输出字段约定（当前实现）

- 任务对象：
  - `job_id`, `kind`, `status`, `error`, `error_code`, `output_ref`, `created_at`, `updated_at`
  - 安全元数据：`limits_applied`, `truncated`, `killed_reason`, `duration_ms`
- 输出对象（建议消费）：
  - `summary`: 指标摘要
  - `tables`: 表格结果
  - `chart_specs`: 图形声明
  - `series`: 序列数据
  - `logs`: 执行日志
  - `warnings`: 风险提示
  - `limits_applied`/`truncated`/`killed_reason`: 执行治理与截断标记

## 审计记录

- 审计日志位置：`result/edu_analysis/audit.log.jsonl`
- 每条最小字段：`job_id`, `script_id`, `request_id`, `status`, `error_code`, `duration_ms`, `created_at`
- 说明：用于追踪任务执行与安全失败原因，不影响现有接口返回结构

## Agent 调用建议

- 发现工具：`GET /api/analysis/tools`
- 执行工具：`POST /api/analysis/tools/{tool_name}`
- 轮询任务：`GET /api/analysis/jobs/{job_id}`
- 幂等重试：同一 `request_id` 重复调用会返回同一 `job_id` 对应结果
- 安全失败恢复：若返回 `resource_exceeded` 或 `timeout`，建议调整脚本输出规模/计算复杂度后使用新的 `request_id` 重试

## 兼容说明

- 现有 `results` 统计链路仍可用：`/api/results/*`
- 新分析能力建议优先走：`/api/analysis/*`
