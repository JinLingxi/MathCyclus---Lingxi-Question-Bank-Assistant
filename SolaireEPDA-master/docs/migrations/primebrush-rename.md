# PrimeBrush 命名迁移说明

本仓库已统一使用 **PrimeBrush** 作为教育绘图能力的唯一对外名称。若您本地的考试项目是在较早版本下创建或从 ZIP 交换包导入的，可能仍含有旧围栏、旧 metadata 键名或旧插图文件名，需要做一次迁移后再用当前版本打开与导出。

## 对外契约（当前版本）

- 代码围栏第一行：`` ```primebrush ``
- 围栏内 YAML 顶层根键：`primebrush:`
- 模板或试卷 metadata 中控制 PDF 插图宽度的键：`primebrush_pdf`
- 题库预览/展开后正文中的 Web 占位前缀：`:::PRIMEBRUSH_IMG:`
- 资源目录下由流水线生成的插图文件前缀：`primebrush_*.svg` / `primebrush_*.png`（位于各题集下的 `resource/.../image/`）

## 迁移方式

在**项目根目录**（含 `resource/`、`templates/` 等）执行：

```bash
python scripts/migrate_picazzo_to_primebrush.py <项目根目录>
```

加 `--dry-run` 可只打印将要修改的文件而不写盘。

脚本会处理：围栏与根键、metadata 键、正文占位符、路径中的旧文件名前缀，并重命名 `resource/**/image/` 下匹配的旧插图文件。

## 验证建议

迁移完成后，在本仓库环境中对该项目执行一次组卷校验与 PDF 导出抽样；若仍有异常，请对照上表检查是否仍有未替换的文本或孤立旧文件。
