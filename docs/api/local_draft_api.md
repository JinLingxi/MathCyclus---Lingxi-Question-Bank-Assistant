# 本地录题 API

本接口用于让浏览器脚本、GPT 辅助网页或其他本地工具把识别结果送入题库的“草稿区”。它只监听 `127.0.0.1`，并且只提供草稿、校验、查重和查询能力。

批准草稿和正式入库仍然必须回到 Streamlit 的“草稿审核与逐题确认”页面完成。API 没有批准和入库接口，网页脚本不能绕过人工二次审核。

## 启动

先启动题库项目，确保 `.venv` 已经创建，然后双击项目根目录的 `启动本地录题API.bat`。命令行会显示：

```text
http://127.0.0.1:8765
本次 token（仅显示一次）：...
```

保持这个窗口运行。token 不要发给其他人，也不要写入 Git。需要固定 token 时，可以在终端设置 `MATHCYCLUS_API_TOKEN` 后再启动：

```powershell
$env:MATHCYCLUS_API_TOKEN = "你自己的本地token"
python scripts/run_local_api.py --port 8765
```

## JavaScript 使用

`api/question_bank_api.js` 是浏览器端客户端。它可以被本地网页或浏览器扩展以 ES module 方式引入：

```js
import { MathCyclusApi } from "./api/question_bank_api.js";

const api = new MathCyclusApi({
  baseUrl: "http://127.0.0.1:8765",
  token: "启动窗口显示的 token",
});

const created = await api.createDraft({
  source_item_id: "pdf-page-3-q12",
  source_label: "PDF 第3页第12题",
  question_type_id: 1,
  stem_tex: String.raw`\\begin{problem}\\text{求 }x^2=1\\end{problem}`,
  choices: ["$x=1$", "$x=-1$"],
  extra: { source_kind: "试卷", detected_year: "2026" },
});

const draftId = created.results[0].draft_id;
await api.updateDraft(draftId, { note: "人工复核前补充说明" });
const check = await api.validateDraft(draftId);
console.log(check.validation, check.content_matches);

const candidates = await api.findSimilarQuestions({
  stem_tex: String.raw`\\begin{problem}\\text{求 }x^2=1\\end{problem}`,
  minimum_score: 0.4,
  max_results: 10,
});
console.log(candidates.algorithm, candidates.items);

const paperMatch = await api.matchPaper({
  year: "2024",
  paper_series: "G",
  paper_name: "全国 I 卷",
});
console.log(paperMatch.match.status, paperMatch.match.candidates);
```

也可以直接在浏览器控制台使用 `fetch`。所有写请求都要带：

```text
Authorization: Bearer <token>
Content-Type: application/json
```

## 接口清单

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| `GET` | `/health` | 检查 API、数据库和迁移状态 |
| `POST` | `/api/v1/drafts` | 创建一批草稿；也支持单题 `draft` |
| `GET` | `/api/v1/drafts` | 按批次或审核状态查看草稿 |
| `GET` | `/api/v1/drafts/{id}` | 查看单题草稿 |
| `PATCH` | `/api/v1/drafts/{id}` | 修改草稿字段；修改后会自动撤销旧批准 |
| `POST` | `/api/v1/drafts/{id}/validate` | 字段校验、完全/高度相似查重、同卷位置冲突检查 |
| `GET` | `/api/v1/drafts/{id}/review-events` | 查看审核事件 |
| `GET` | `/api/v1/batches` | 查看录题批次 |
| `GET` | `/api/v1/batches/{id}` | 查看批次汇总和草稿 |
| `POST` | `/api/v1/batches/{id}/validate` | 一次性校验批次内草稿、查重和试卷位置冲突；只读 |
| `GET` | `/api/v1/questions/search` | 查询正式题库，用于人工比对 |
| `POST` | `/api/v1/questions/similarity` | 按统一相似度算法返回候选题；只读 |
| `POST` | `/api/v1/papers/match` | 按年份、卷别、文理赛道和试卷名称匹配标准试卷；只读，非精确命中必须人工确认 |
| `GET` | `/api/v1/questions/{id}` | 查看正式题目详情 |

API 不接受 `review_status=approved`，即使请求中带了这个字段也会降为待审核。人工审核完成后，仍在题库网页中批准并正式入库。
