# 1.0 发布文件清单与本地数据边界

> 目的：在推送 GitHub 或准备安装包前，快速确认仓库只包含程序、schema、脚本、模板和文档，不包含个人题库数据。

## 1. 应进入 Git 的内容

这些内容属于项目源码或可复现配置，应该随版本发布：

- `question_bank_app.py`：Streamlit 主应用。
- `services/`：SQLite 数据库服务、导入服务、导出服务、专题服务、回溯服务、本地偏好服务、录入解析服务等。
- `scripts/`：本地初始化、schema migration、旧库迁移、数据包迁移、审计、smoke、发布检查脚本。
- `db/schema.sql`：空库基线 schema。
- `db/migrations/`：正式 schema 迁移文件，例如 `0002_topic_intro_fields.sql`。
- `docs/planning/`：重构规划、迁移流程、安装更新流程、发布清单。
- `templates/`：可复用模板。
- `utils/`：可复用工具函数，但不包含本地索引数据库。
- `README.md`、`env.example`、`.gitignore`、`requirements.txt`、`启动程序.bat`。

## 2. 不应进入 Git 的内容

这些是个人数据、生成产物、缓存或本地环境，必须只留在用户电脑上：

- `.env`、`.env.*`：API Key 和私有配置，`env.example` 例外。
- `data/mathcyclus.sqlite3`、`data/*.sqlite3`、`data/*.db`：正式题库和本地数据库。
- `data/local_preferences.json`：本机 UI 偏好。
- `data/backups/`：本地迁移包和备份。
- `db/seed/*.csv`、`db/seed/*.json`：基于个人题库生成的迁移复核种子、人工校正表和检查清单。
- `assets/questions/`：每道题的非 TikZ 图片资源。
- `reports/`：审计和发布检查报告。
- `exports/`、`cloze_exports/`、`Test Paper Group/导出文件/`：导出文件。
- `utils/semantic_index.sqlite3`、`utils/local_stats.sqlite3`、`utils/operation_log.sqlite3`：可重建索引和本机统计。
- `.venv/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`：运行环境与缓存。
- `*.pdf`、历史备份文件、临时同步目录和旧实验目录。
- 真实题库 `.tex` 源题文件，默认按 `*-G-*.tex`、`*-M-*.tex` 等规则忽略。

## 3. 白名单源码发布包

以后做源码版 zip 或安装包的“程序部分”时，不直接压缩整个项目目录，而是必须走白名单脚本：

```text
python scripts/build_source_release_package.py --json
python scripts/build_source_release_package.py --create
```

白名单发布包只允许进入：

- 根目录必要源码与配置：`question_bank_app.py`、`requirements.txt`、`env.example`、`README.md`、`.gitignore`、启动脚本等；
- `services/`、`scripts/`、`db/`、`docs/`、`templates/`、`utils/`、`fig/`、`cover/`；
- `Test Paper Group/主题模板/` 中的模板源码；
- `data/`、`db/seed/`、`assets/questions/`、`exports/`、`reports/`、`chapters/` 的 `.gitkeep` 占位文件。

即使上述目录中存在本地缓存或生成产物，发布包也必须排除：

- `.env`、API key、本机配置；
- `data/*.sqlite3`、`*.db`、SQLite WAL/SHM；
- `db/seed/*.csv`、`db/seed/*.json` 这类从个人题库生成的迁移复核数据；
- `assets/questions/**` 的真实题目图片；
- `reports/**`、`exports/**`、`cloze_exports/**`；
- `chapters/**` 旧 TeX 题源和旧图片；
- `__pycache__/**`、`*.pyc`、LaTeX 编译产物、PDF。

判断标准：

- `status=ok`：可以创建源码包；
- `excluded_count>0`：只是说明本地存在被排除的缓存/生成文件，不是阻塞；
- `blocked_included>0` 或 `missing_required>0`：说明白名单核心文件异常，不能打包。

## 4. 已跟踪旧文件清理

`.gitignore` 只能阻止“新文件”进入 Git，不能自动移除已经被 Git 跟踪过的旧文件。因此提交前必须单独审计：

```text
python scripts/audit_tracked_private_files.py
python scripts/audit_tracked_private_files.py --commands
python scripts/audit_tracked_private_files.py --apply --confirm KEEP_LOCAL
```

当前策略：

- 只读审计脚本默认不修改 Git；
- 如果输出 `tracked_cleanup_count>0`，说明仍有旧题源、旧导出或本地数据被 Git 跟踪；
- 真正清理时使用脚本输出的 `git rm --cached -- "路径"`；
- 如果不想逐条复制命令，可以直接运行 `python scripts/audit_tracked_private_files.py --apply --confirm KEEP_LOCAL`；
- `git rm --cached` 只从 Git 索引移除文件，不删除电脑上的本地文件；
- 执行后再运行 `git status --short`，确认这些文件显示为 staged deletion；
- 提交这一批 deletion 后，后续推送才不会继续把这些旧文件放进仓库当前版本。

目前优先清理对象：

- `chapters/**`：旧 TeX 题源与旧题目图片，本地可继续保留；
- `Test Paper Group/导出文件/**`：历史导出的试卷/讲义成品；
- `db/seed/**`：基于个人题库生成的迁移复核 CSV/JSON，仅保留 `.gitkeep`；
- 将来如果发现 `data/**`、`assets/questions/**`、`reports/**`、`exports/**` 被跟踪，也按同一策略移除跟踪。

## 5. 当前检查结果

最近一次检查命令：

```text
python scripts/check_project_hygiene.py
python scripts/release_readiness.py --skip-slow
python scripts/smoke_source_release_package.py
python scripts/audit_tracked_private_files.py
```

当前口径：

- `check_project_hygiene.py`：`status=warning`，`blockers=0`。
- `release_readiness.py --skip-slow`：`status=warning`，`failed=0`。
- warning 来源：当前工作区存在真实未提交改动，需要人工确认文件清单。
- 未发现未被忽略的正式 SQLite 数据库、报告文件或题目图片目录。
- 当前仍存在历史上已经被 Git 跟踪的 `chapters/**`、`Test Paper Group/导出文件/**` 与 `db/seed/**`；这类文件需要用 `git rm --cached` 从 Git 当前版本移除，但本地文件不删除。
- 检查生成的 `reports/*.json`、`reports/*.md` 属于本地临时报表，验证后应清理，不随 commit 提交。

## 6. 推送前建议流程

```text
git status --short --untracked-files=all
python scripts/init_local_workspace.py --dry-run --strict-gitignore
python scripts/build_source_release_package.py --json
python scripts/audit_tracked_private_files.py
python scripts/release_readiness.py --skip-slow
```

人工确认：

- 新增 `services/*.py`、`scripts/smoke_*.py`、`db/migrations/*.sql` 是否都应纳入本版。
- `data/`、`assets/questions/`、`reports/`、`exports/` 下是否没有待提交文件。
- `.env` 是否仍被忽略。
- `启动程序.bat` 的 diff 是否只包含启动前初始化逻辑。
- 如果 `audit_tracked_private_files.py` 仍提示旧文件被跟踪，先决定是否执行 `git rm --cached` 清理。
- 如果要推私有开发分支，先确认分支名和远端，例如 `sqlite-rebuild-dev`。

## 7. 安装包/迁移包边界

未来如果做安装包或给他人部署：

- GitHub release 只放程序包，不放个人题库数据库和图片。
- 用户自己的数据库、图片、偏好、导出和报告通过本地迁移包处理。
- 本地迁移包默认输出到 `data/backups/`，不作为 GitHub 附件。
- 新用户首次启动通过 `scripts/init_local_workspace.py` 创建空目录和空库。
- 老用户更新后通过 schema migration 和旧 TeX 导入工具迁移数据。
- 程序包必须由 `scripts/build_source_release_package.py --create` 生成；本地数据包必须由 `scripts/local_data_bundle.py export` 单独生成，两者不能混用。
