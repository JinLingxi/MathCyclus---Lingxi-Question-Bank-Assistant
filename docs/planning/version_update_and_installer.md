# 版本更新与安装包方案

> 目标：让用户从 GitHub 下载或更新 MathCyclus 时，能稳定保留自己的本地题库数据、SQLite 数据库、图片资源和 API 配置。

## 1. 核心原则

- GitHub 仓库只放程序源码、数据库 schema、脚本、模板和文档；
- 用户本地数据不进入 GitHub，包括 `data/mathcyclus.sqlite3`、`assets/questions/`、`reports/`、`exports/`、`.env`；
- 每次版本更新前先做本地备份，再更新代码和依赖；
- 更新脚本默认只 dry-run，不自动拉取、不自动安装、不覆盖数据；
- 真实执行必须显式加 `--apply`；
- `git pull` 使用 `--ff-only`，避免自动生成合并提交；
- 工作区有未提交改动时，默认拒绝拉取，防止用户自己改过的文件被冲突打断。

## 2. 新用户安装流程

推荐后续 README 中给出：

```text
git clone <repo-url>
cd <repo>
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts/init_local_workspace.py
.\.venv\Scripts\python.exe -m streamlit run question_bank_app.py
```

`scripts/init_local_workspace.py` 会创建：

- `data/`
- `data/backups/`
- `data/indexes/`
- `assets/questions/`
- `exports/`
- `reports/`
- 空的 `data/mathcyclus.sqlite3`

## 3. 老用户更新流程

推荐先预览：

```text
.\.venv\Scripts\python.exe scripts/update_local_installation.py --pull --install-deps --run-checks
```

确认无阻塞后执行：

```text
.\.venv\Scripts\python.exe scripts/update_local_installation.py --apply --pull --install-deps --run-checks
```

如果用户还在使用旧 `chapters/` TeX 题源，并且希望更新前顺带备份旧题源：

```text
.\.venv\Scripts\python.exe scripts/update_local_installation.py --apply --pull --install-deps --run-checks --include-legacy-tex-backup
```

## 4. 更新助手脚本职责

`scripts/update_local_installation.py` 当前定位是“本地更新助手”，不是完整安装包。

它负责：

- 检查当前 Git 分支、HEAD、upstream 和工作区脏状态；
- 预览本次更新计划；
- 应用更新前备份本地 SQLite、图片资源和 CSV 缓存；
- 应用更新前备份 `.env`、`ocr_prompt.txt`、`.streamlit/secrets.toml` 等配置文件；
- 可选执行 `git pull --ff-only`；
- 可选执行 `python -m pip install -r requirements.txt`；
- 更新后再次运行 `init_local_workspace.py --strict-gitignore`；
- 更新后运行 `migrate_schema.py` 检查或应用数据库 schema 迁移；
- 可选运行 `release_readiness.py --skip-slow`；
- 应用模式下写入 `reports/local_update_*.md/json`。

它不负责：

- 删除任何本地文件；
- 覆盖正式 SQLite 数据库；
- 自动处理 Git 冲突；
- 在未显式 `--apply` 的情况下自动执行数据库 schema 迁移；
- 上传任何本地个人数据。

## 5. 未来安装包方向

后续如果要做 1.0 安装包，建议拆成三层：

### 5.1 GitHub 源码安装

适合熟悉 Python 的用户：

- 使用 `git clone`；
- 使用 `.venv`；
- 使用 `scripts/init_local_workspace.py`；
- 使用 `scripts/update_local_installation.py` 更新。

### 5.2 图形化启动器

适合普通用户：

- 双击启动；
- 自动检测 `.venv`；
- 自动检测依赖；
- 自动创建空库和本地目录；
- 提供“检查更新”“备份本地数据”“恢复迁移包”按钮。

### 5.3 打包版

适合完全不想配置 Python 的用户：

- 使用 PyInstaller 或类似方案打包；
- 首次运行时创建用户数据目录；
- 程序目录和用户数据目录分离；
- 支持导入/导出本地数据迁移包。

## 6. 后续还缺的关键能力

- GUI 内的“检查更新 / 一键备份 / 恢复迁移包”入口；
- README 中面向普通用户的安装和升级说明；
- 发布前自动检查 `.gitignore` 是否继续保护本地私有数据。

## 7. 推荐 1.0 前完成顺序

1. 稳定 SQLite 浏览、编辑、录入、组卷；
2. 数据统计改为 SQLite-first；
3. 完成旧 TeX 到 SQLite 图形化迁移入口实机确认；
4. 把 `scripts/update_local_installation.py` 和 `scripts/migrate_schema.py` 写入 README；
5. 最后考虑是否做图形化启动器或打包版。
