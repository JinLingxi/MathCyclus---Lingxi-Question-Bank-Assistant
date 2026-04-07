# 开发约定与工程结构

本文面向开发者，说明项目结构、接口边界与前后端协作方式。

## 技术栈

- 后端：Python + FastAPI
- 前端：React + TypeScript + Vite + Tailwind
- 数据：项目目录文件（`resource/`、`result/`、`templates/`、`.solaire/`）

## 工程边界

- 业务规则以 `exam_compiler` 为准，Web 层负责编排与交互。
- API 统一走 `/api/*`，错误返回遵循 `{"detail":"..."}`。
- 帮助文档统一从 `src/solaire_doc/` 读取并发布。

## 常见开发入口

- 页面与交互：`web/src/pages/`
- API 客户端：`web/src/api/client.ts`
- 服务路由：`src/solaire/web/app.py`（图谱、组卷、题库等 REST）；智能助手 SSE 等见 `src/solaire/web/agent_api.py`（挂载前缀 `/api/agent`）
- 试卷编译与插图展开：`src/solaire/exam_compiler/`
- 教育绘图（PrimeBrush）：`src/solaire/primebrush/`
- 知识图谱领域逻辑：`src/solaire/knowledge_forge/`（HTTP 层仍在 `app.py` 中暴露 `/api/graph/*`）
- 考试分析（SkillAnalyzer，代码目录仍为 `edu_analysis`）：`src/solaire/edu_analysis/`
- 智能助手编排：`src/solaire/agent_layer/`

## 本地验证建议

- 后端测试：`pytest`
- 前端测试：`npm test`
- 前端构建：`npm run build`
- 基线回归：`scripts/check_edu_analysis_baseline.ps1`

## EduAnalysis 图形扩展规范

- 用户脚本运行时提供 `get_rawdata()`、`get_graph()`。
- 推荐脚本返回图形对象实例（如直方图、扇形图），而非手写复杂输出结构。
- 图形对象需实现统一接口：
  - `to_payload()`：输出结构化结果
  - `get_picture(...)`：输出图片内容（如 SVG）
- 保持旧版 `RESULT` 字典兼容，避免历史脚本失效。
