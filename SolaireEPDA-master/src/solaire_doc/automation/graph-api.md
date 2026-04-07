# 图谱 HTTP API：批量注入与信息提取（供自动化/助手编排）

本文说明如何通过 **HTTP** 向项目内**知识图谱**写入节点、关系、题目绑定与资料链接，以及如何**读出**图谱用于分析或同步。默认假设服务已启动且工作区根目录已由应用绑定（与 `tests/conftest.py` 中行为一致）。

**基础地址**：`http://127.0.0.1:<端口>`（本地开发以实际为准）。下文用 `$BASE` 表示。

**内容类型**：请求体为 `application/json`，除非另有说明。

---

## 1. 批量注入推荐顺序

对一批数据（例如从表格或模型输出）建议按以下顺序调用，并在每步做失败重试（见第 5 节）：

1. **创建节点** `POST /api/graph/nodes`（可先创建父级，再创建子级；或一次指定 `id` 与可选 `parent_node_id`）。
2. **创建关系** `POST /api/graph/relations`（两端至少一端为「知识点」类型节点的业务规则由服务端校验）。
3. **绑定题目**（可选）`POST /api/graph/bindings`。
4. **挂载资料**（可选）：先保证文件存在于项目 `resource/` 下，再 `POST /api/graph/file-links`；或先 `POST /api/graph/upload` 上传再挂链。

---

## 2. 核心端点一览

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/graph/nodes` | 列出节点；支持 `?node_kind=concept` 等筛选 |
| POST | `/api/graph/nodes` | 创建节点 |
| GET | `/api/graph/nodes/{node_id}` | 单节点详情（路径中的 `node_id` 需按 URL 编码） |
| PUT | `/api/graph/nodes/{node_id}` | 更新节点 |
| DELETE | `/api/graph/nodes/{node_id}` | 删除节点 |
| GET | `/api/graph/relations` | 列出全部关系 |
| POST | `/api/graph/relations` | 创建关系 |
| DELETE | `/api/graph/relations/{relation_id}` | 删除关系 |
| POST | `/api/graph/bindings` | 题目与节点绑定 |
| POST | `/api/graph/bindings/unbind` | 解除绑定 |
| GET | `/api/graph/nodes/{node_id}/questions` | 某节点关联题目 |
| GET | `/api/graph/nodes/{node_id}/files` | 某节点资料链接列表 |
| POST | `/api/graph/file-links` | 为节点添加资料（文件须已存在） |
| DELETE | `/api/graph/file-links/{link_id}` | 删除资料链接 |
| POST | `/api/graph/upload` | 上传资料文件（multipart），返回相对 `resource/` 的路径 |
| GET | `/api/graph/taxonomy` | 学科/层级等分类信息 |
| PUT | `/api/graph/taxonomy` | 更新分类信息 |

**列表节点响应**：`GET /api/graph/nodes` 返回 JSON，含 `nodes` 数组与 `kind_counts`。每个节点含展示与布局所需字段，并含 **`file_link_count`**：该节点已挂载的资料条数（用于前端圆大小等，**勿向终端用户暴露实现细节**）。

---

## 3. 请求体要点

### 创建节点 `POST /api/graph/nodes`

- **`canonical_name`**：必填，标准名称。
- **`aliases`**：别名列表，无则 `[]`。
- **`id`**：可选；若留空则通常需提供 **`parent_node_id`** 以自动生成内部标识（具体规则见服务端）。
- **`parent_node_id`**：可选；若提供可能自动建立「组成」类关系（见服务端实现）。
- **`node_kind`**：可选；`concept` / `skill` / `causal`。
- **`subject` / `level` / `description` / `tags` / `source`**：可选。
- **`layout_x` / `layout_y`**：可选，画布坐标。

### 创建关系 `POST /api/graph/relations`

```json
{
  "from_node_id": "math/func/a",
  "to_node_id": "math/func/b",
  "relation_type": "prerequisite"
}
```

`relation_type` 须为系统允许的类型（如 `prerequisite`、`part_of`、`related`、`causal` 等，以服务端校验为准）。

### 资料链接 `POST /api/graph/file-links`

```json
{
  "node_id": "math/func/a",
  "relative_path": "资料/示例.pdf"
}
```

路径为**相对项目 `resource/` 目录**的正斜杠路径；**文件必须已存在**，否则返回错误。

### 题目绑定 `POST /api/graph/bindings`

```json
{
  "question_qualified_id": "数学/高考真题/demo_choice_001",
  "node_id": "math/func/a"
}
```

---

## 4. 提取图谱信息（读）

- **全量节点**：`GET /api/graph/nodes` → 使用 `nodes` 与 `kind_counts`。
- **全量关系**：`GET /api/graph/relations` → 使用 `relations`（字段名以响应为准）。
- **单节点**：`GET /api/graph/nodes/{node_id}`。
- **某节点题目**：`GET /api/graph/nodes/{node_id}/questions`。
- **某节点资料**：`GET /api/graph/nodes/{node_id}/files`。

构建「邻接表」时：将每条无向或有向关系按 `from_node_id`、`to_node_id` 加入邻接结构即可（是否无向取决于产品定义；当前画布按无向邻域做聚焦时可两边都连）。

---

## 5. 失败重试与幂等建议

- **4xx**：阅读响应 `detail`；修正参数后重试，**勿盲重试**。
- **5xx / 网络超时**：指数退避重试（如 0.5s、1s、2s），上限 3～5 次。
- **批量写入**：对每条记录记录「已成功」的 `node_id` / `relation_id`，失败可从断点继续；同一 `id` 的节点重复创建会失败，应先 `GET` 或捕获冲突后改更新 `PUT`。

---

## 6. 最小示例

### curl：创建节点与关系

```bash
BASE=http://127.0.0.1:8000
curl -sS -X POST "$BASE/api/graph/nodes" \
  -H "Content-Type: application/json" \
  -d '{"id":"demo/a","canonical_name":"节点甲","aliases":[],"subject":"数学"}'

curl -sS -X POST "$BASE/api/graph/nodes" \
  -H "Content-Type: application/json" \
  -d '{"id":"demo/b","canonical_name":"节点乙","aliases":[],"subject":"数学"}'

curl -sS -X POST "$BASE/api/graph/relations" \
  -H "Content-Type: application/json" \
  -d '{"from_node_id":"demo/a","to_node_id":"demo/b","relation_type":"related"}'
```

### curl：拉取全图

```bash
curl -sS "$BASE/api/graph/nodes"
curl -sS "$BASE/api/graph/relations"
```

### Python：拉取并遍历节点

```python
import json
import urllib.request

BASE = "http://127.0.0.1:8000"

def get_json(path: str):
    with urllib.request.urlopen(BASE + path) as r:
        return json.loads(r.read().decode())

data = get_json("/api/graph/nodes")
for n in data["nodes"]:
    print(n["id"], n.get("canonical_name"), n.get("file_link_count", 0))
```

---

## 7. 与前端图谱页的关系

浏览器中的画布布局由前端根据节点尺寸与力导向参数计算；**持久化坐标**可通过节点上的 `layout_x` / `layout_y` 经 `PUT /api/graph/nodes/{id}` 更新。批量注入时若暂不写坐标，可在界面中「重新整理」生成布局。

---

## 8. 参考代码位置

- 路由与请求体模型：`src/solaire/web/app.py`（`/api/graph/*`）
- 图谱领域模型与持久化：`src/solaire/knowledge_forge/`（详见仓库内实现与 `graph_service` 分工）
- 前端 API 封装：`web/src/api/client.ts`
