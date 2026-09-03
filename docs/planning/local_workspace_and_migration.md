# 本地工作区初始化与数据迁移方案

> 状态：预部署方案。当前用于内部验证，正式 1.0 发布前再决定是否写入 README 主流程。  
> 原则：GitHub 仓库只放程序、schema、脚本、模板和文档；个人题库数据只留在用户本地。

## 1. 目标

本方案解决两个问题：

1. 新用户 clone / 下载项目后，可以一键创建本地运行所需目录和空 SQLite 数据库；
2. 老用户换电脑或备份时，可以把自己的数据库、题目图片、可选旧 TeX 题源打成迁移包，再在另一台机器恢复。

## 2. 不进入 GitHub 的本地数据

以下内容默认视为个人数据或运行生成物，不应提交：

- `data/mathcyclus.sqlite3`
- `data/backups/*`
- `data/indexes/*`
- `assets/questions/*`
- `reports/*`
- `exports/*`
- `utils/题库索引表.csv`
- 旧题源 `.tex` 文件

当前 `.gitignore` 已覆盖上述路径。正式发布前仍需要运行：

```bash
python scripts/release_readiness.py
```

确认没有数据库、报告、导出文件或题目图片泄漏到 Git 状态中。

## 3. 初始化脚本

脚本：

```bash
python scripts/init_local_workspace.py
```

如果是从旧版本升级，初始化目录后还应检查数据库 schema：

```text
python scripts/migrate_schema.py
python scripts/migrate_schema.py --apply
```

作用：

- 创建本地运行目录：
  - `data/`
  - `data/backups/`
  - `data/indexes/`
  - `assets/`
  - `assets/questions/`
  - `exports/`
  - `reports/`
- 创建必要 `.gitkeep`，让空目录结构能留在仓库中；
- 当 `data/mathcyclus.sqlite3` 不存在时，根据 `db/schema.sql` 初始化空数据库；
- 检查关键本地数据路径是否被 Git 忽略；
- 不删除任何文件；
- 不覆盖已有数据库；
- 不修改旧 `.tex` 题源。

常用命令：

```bash
# 只检查将执行什么，不写入
python scripts/init_local_workspace.py --dry-run

# 初始化本地工作区
python scripts/init_local_workspace.py

# 输出机器可读 JSON
python scripts/init_local_workspace.py --json

# 如果忽略规则不完整则返回失败，适合发布前检查
python scripts/init_local_workspace.py --strict-gitignore
```

## 4. 迁移包工具

脚本：

```bash
python scripts/local_data_bundle.py
```

迁移包是私有数据包，不是 GitHub release 附件。默认输出位置在 `data/backups/`，该目录已被忽略。

### 4.1 导出

默认导出：

```bash
python scripts/local_data_bundle.py export
```

默认包含：

- `data/mathcyclus.sqlite3`
- `assets/questions/`
- `utils/题库索引表.csv`

默认不包含：

- `chapters/` 旧 TeX 题源；
- `reports/` 检查报告；
- `exports/` 导出试卷。

如果需要把旧题源也一起迁移：

```bash
python scripts/local_data_bundle.py export --include-legacy-tex
```

如果只想统计，不生成 zip：

```bash
python scripts/local_data_bundle.py export --dry-run
```

### 4.2 检查迁移包

```bash
python scripts/local_data_bundle.py inspect data/backups/mathcyclus_local_bundle_YYYYMMDD_HHMMSS.zip
```

检查内容：

- 包格式；
- 生成时间；
- 文件数量；
- 总字节数；
- 按类型统计；
- 是否包含个人数据；
- 是否应进入 Git。

### 4.3 恢复迁移包

默认只 dry-run，不写文件：

```bash
python scripts/local_data_bundle.py restore data/backups/mathcyclus_local_bundle_YYYYMMDD_HHMMSS.zip
```

真正恢复：

```bash
python scripts/local_data_bundle.py restore data/backups/mathcyclus_local_bundle_YYYYMMDD_HHMMSS.zip --apply
```

安全边界：

- 默认不覆盖已有文件；
- 若目标文件已存在，会报告 conflict 并停止；
- 只有显式加 `--overwrite` 才允许覆盖；
- 不删除目标项目中的任何文件；
- 只允许恢复到项目目录内的受控路径；
- 会拒绝压缩包内的路径穿越。

允许恢复的路径范围：

- `data/mathcyclus.sqlite3`
- `assets/questions/`
- `utils/题库索引表.csv`
- `chapters/`
- `reports/`
- `exports/`

## 5. 图片资产迁移方式

非 TikZ 图片采用“文件 + 数据库关系表”的方式：

- 图片文件位于 `assets/questions/<question_id>/`；
- 图片关系登记在 SQLite 的 `question_asset` 表；
- `question_asset.file_path` 保存项目相对路径；
- TeX 源码中使用 `\questionasset{引用名}` 占位；
- 预览和导出时根据当前题目的 `question_asset` 记录解析到真实图片。

这种方式的好处：

- 数据库不膨胀；
- 图片可以单独备份和迁移；
- 项目相对路径跨电脑可用；
- 后续打安装包时，程序和数据可以分离；
- GitHub 仓库不会包含个人图片。

## 6. 1.0 发布前建议流程

正式发布前建议执行：

```bash
python scripts/init_local_workspace.py --dry-run --strict-gitignore
python scripts/smoke_local_workspace_tools.py
python scripts/release_readiness.py
```

如果需要给自己备份一份本地数据：

```bash
python scripts/local_data_bundle.py export --include-legacy-tex
```

如果只是发布给别人安装：

- 不上传 `data/mathcyclus.sqlite3`；
- 不上传 `assets/questions/` 中的真实图片；
- 不上传 `reports/`；
- 不上传 `exports/`；
- 让用户下载代码后运行 `python scripts/init_local_workspace.py` 创建自己的空库。

## 7. 后续可扩展项

正式安装包阶段可以继续补：

- 图形化首次启动向导；
- 启动时自动检测本地数据库是否存在，不存在则提示初始化；
- 设置页中的“备份本地数据 / 恢复本地数据”按钮；
- 迁移包版本兼容检查；
- schema 迁移脚本 `db/migrations/` 已建立，当前入口为 `scripts/migrate_schema.py`；
- 用户数据目录自定义位置；
- 一键导出“程序配置 + 私有题库数据”的离线备份。
