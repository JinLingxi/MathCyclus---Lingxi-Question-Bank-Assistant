# 版本更新与安装包方案

> 目标：让用户从 GitHub 下载或更新 MathCyclus 时，能稳定保留自己的本地题库数据、SQLite 数据库、图片资源和 API 配置。

## 1. 核心原则

- GitHub 仓库只放程序源码、数据库 schema、脚本、模板和文档；
- 用户本地数据不进入 GitHub，包括 `data/mathcyclus.sqlite3`、`data/local_preferences.json`、`db/seed/*.csv`、`assets/questions/`、`reports/`、`exports/`、`.env`；
- 源码 zip 或安装包的程序部分必须通过白名单脚本生成，不能直接压缩整个项目目录；
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
- 后续使用中生成的 `data/local_preferences.json`

Windows 一键启动器 `启动程序.bat` 已先行接入本地初始化：依赖安装完成后会运行 `scripts/init_local_workspace.py --skip-gitignore-check`，用于补齐 `data/`、`assets/questions/`、`exports/`、`reports/` 和空 SQLite 库；该步骤不会覆盖已有数据库。

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

### 5.0 程序包白名单

程序包只从白名单生成：

```text
python scripts/build_source_release_package.py --json
python scripts/build_source_release_package.py --create
```

白名单包职责：

- 只携带程序、schema、脚本、模板、文档和必要 UI 资源；
- 排除 `.env`、本地 SQLite、迁移复核 seed、题目图片、导出文件、报告、旧 `chapters/` 题源、Python 缓存和 LaTeX 编译产物；
- 允许 `data/`、`assets/questions/`、`reports/`、`exports/`、`chapters/` 的 `.gitkeep` 占位；
- 把被排除的本地产物计入 `excluded_count`，但不因此阻塞打包；
- 对核心白名单文件缺失或异常命中 deny 规则时返回 blocked。

本地数据不通过源码包传播；用户换电脑或备份数据时应使用：

```text
python scripts/local_data_bundle.py export
```

也就是说，未来安装包至少要分清两类包：

- 程序包：可上传 GitHub release；
- 本地数据迁移包：只给用户自己保存或私下迁移，不上传 GitHub。

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

当前 Streamlit 工具箱已先行接入轻量图形化入口：

- `工具箱 → 本地维护与升级`；
- 支持检查/应用 SQLite schema 迁移；
- 支持预览/执行源码版本地更新；
- 支持导出、检查和恢复本地数据迁移包；
- 真正写入动作均需要确认文本，避免误操作。
- 发布前总检查已接入 `smoke_update_local_installation.py`，用于验证本地更新助手的 dry-run 计划不会拉取、安装、写报告或覆盖本地数据。

### 5.3 打包版

适合完全不想配置 Python 的用户：

- 使用 PyInstaller 或类似方案打包；
- 首次运行时创建用户数据目录；
- 程序目录和用户数据目录分离；
- 支持导入/导出本地数据迁移包。

## 6. 后续还缺的关键能力

- 独立于 Streamlit 的图形化启动器；
- 打包版用户数据目录迁移和版本兼容检查；
- 发布前审计已经被 Git 跟踪的旧数据，并用 `scripts/audit_tracked_private_files.py --apply --confirm KEEP_LOCAL` 移除跟踪但保留本地文件。

## 7. 推荐 1.0 前完成顺序

1. 稳定 SQLite 浏览、编辑、录入、组卷；
2. 数据统计已改为 SQLite-first，CSV/旧 TeX 只保留旧安装兜底；
3. 旧 TeX 到 SQLite 图形化迁移入口已接入工具箱，包含预览库、提升检查和强确认正式提升；
4. 运行 `scripts/audit_tracked_private_files.py`，清理历史已跟踪的旧题源/导出文件；
5. `scripts/update_local_installation.py`、`scripts/migrate_schema.py` 和白名单打包命令已写入 README，并已纳入发布前 smoke；
6. 最后考虑是否做独立图形化启动器或打包版。
