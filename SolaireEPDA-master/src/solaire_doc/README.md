# 应用内手册（正文源）

本目录为 **Solaire Web 内手册** 的单一事实来源：`help-manifest.json` 列出可访问的篇目与路径，后端仅允许读取清单中的文件，供前端渲染。可选字段 **`section`**：`intro` | `guide` | `advanced`，对应侧栏三组；未写时按 `audience` 推断（`ai`→`advanced`，`dev`→`advanced`，其余用户向→`guide`）。

## 子目录

- **`introduction/`**：侧栏「介绍」篇目（如组卷系统概念）。
- **`tutorial/`**：侧栏「介绍/使用教程」入口与上手路径（普通使用者）。
- **`user/`**：侧栏「使用说明」——面向老师与终端使用者（插图、流程图、题库交换、公式、知识图谱页等）。
- **`developer/`**：开发者文档（工程结构、联调、分发与部署实践）。
- **`advanced/`**：侧栏「高级使用说明」——面向开发者 / 助手（`questions.yaml`、`template.yaml`、项目文件与 HTTP 接口总览等）。
- **`assets/`**：手册内嵌配图（如 PrimeBrush 示例 SVG，路径形如 `assets/primebrush/…`），由 `GET /api/help/asset/...` 提供，**不在** `help-manifest.json` 中逐条登记；路径须位于 `assets/` 下且后缀为常见图片格式。

## 与根目录 `docs/` 的关系

- **`docs/`**：仓库内的开发说明、架构、计划、验收清单等，**不**作为应用内嵌正文的维护位置。
- **`src/solaire_doc/`**：随应用发布的手册正文；修改此处 Markdown 即可更新产品内展示（具体加载方式见后端实现）。
