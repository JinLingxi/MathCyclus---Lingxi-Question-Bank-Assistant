# SQLite Schema 迁移流程

> 目标：后续项目更新时，用户的本地 `data/mathcyclus.sqlite3` 能安全跟随代码升级，同时不丢题库数据、不覆盖图片资源、不需要手工改库。

## 1. 已建立的版本表

`db/schema.sql` 已增加两张基础表：

```text
app_meta
schema_migration
```

`app_meta` 用于保存当前数据库运行状态：

| key | 说明 |
| --- | --- |
| `app_name` | 项目名 |
| `schema_version` | 当前数据库 schema 版本 |
| `schema_baseline` | 当前基线日期 |

`schema_migration` 用于记录已应用的迁移：

| 字段 | 说明 |
| --- | --- |
| `version` | 迁移版本号，例如 `1` |
| `name` | 迁移名称 |
| `checksum` | 迁移 SQL 文件 SHA256 |
| `applied_at` | 应用时间 |

## 2. 迁移文件命名

迁移 SQL 放在：

```text
db/migrations/
```

命名格式：

```text
0001_schema_version_baseline.sql
0002_topic_intro_fields.sql
0003_alter_xxx.sql
```

规则：

- 前四位数字是版本号；
- 版本号只能递增；
- 已发布迁移文件不要改内容；
- 如果要修正 schema，新增下一条迁移，不回改旧迁移；
- 迁移 SQL 必须尽量可重复执行，优先使用 `IF NOT EXISTS`、`INSERT OR IGNORE`、`ON CONFLICT`。

## 3. 命令行入口

新增脚本：

```text
scripts/migrate_schema.py
```

查看状态：

```text
python scripts/migrate_schema.py --status-only
```

dry-run 检查：

```text
python scripts/migrate_schema.py
```

正式应用：

```text
python scripts/migrate_schema.py --apply
```

指定数据库：

```text
python scripts/migrate_schema.py --db data/mathcyclus.sqlite3 --apply
```

## 4. 安全边界

迁移脚本默认安全：

- 不加 `--apply` 时只读检查；
- 应用前默认备份 SQLite；
- 备份放在 `data/backups/`；
- 不删除任何文件；
- 不修改旧 `.tex` 题源；
- 不移动 `assets/questions/` 图片资源；
- 如果已应用迁移的 checksum 和当前文件不一致，拒绝继续。

## 5. 与更新助手的关系

`scripts/update_local_installation.py` 已接入 schema 迁移：

- 更新前先备份本地数据；
- 可选 `git pull --ff-only`；
- 可选安装依赖；
- 更新后运行 `scripts/init_local_workspace.py` 补齐本地目录；
- 然后运行 `scripts/migrate_schema.py`；
- 最后可选运行 `scripts/release_readiness.py --skip-slow`。

普通用户更新推荐：

```text
python scripts/update_local_installation.py --pull --install-deps --run-checks
python scripts/update_local_installation.py --apply --pull --install-deps --run-checks
```

## 6. 当前基线迁移

当前迁移包括一条基线迁移和一条专题字段迁移：

```text
db/migrations/0001_schema_version_baseline.sql
db/migrations/0002_topic_intro_fields.sql
```

`0001_schema_version_baseline.sql` 做的事情：

- 给旧库补 `app_meta`；
- 给旧库补 `schema_migration`；
- 标记 `schema_version = 1`；
- 标记 `schema_baseline = 20260903`；
- 不碰题目表、来源表、图片表和旧 TeX。

`0002_topic_intro_fields.sql` 做的事情：

- 给 `topic` 增加 `problem_intro_tex`，用于专题导出时插入题目部分引言；
- 给 `topic` 增加 `answer_intro_tex`，用于专题导出时插入答案部分引言；
- 给 `topic` 增加 `export_note` 与 `extra_json`，保留专题导出备注和未来扩展信息；
- 不修改 `topic_question` 既有题目关系，也不触碰旧 `.tex` 题源。

## 7. 后续新增字段时的流程

未来如果要给数据库加字段，例如题目图片引用别名、导出偏好或教材栏目扩展，应按下面流程：

1. 修改 `db/schema.sql`，保证新安装用户得到最新完整 schema；
2. 新增 `db/migrations/0002_xxx.sql`，保证老用户可以从旧库升级；
3. 新增或更新服务层读写逻辑；
4. 新增 smoke 测试覆盖旧库升级；
5. 运行：

```text
python -m py_compile services/schema_migration_service.py scripts/migrate_schema.py scripts/smoke_topic_collection_service.py
python scripts/smoke_schema_migration_service.py
python scripts/smoke_topic_collection_service.py
python scripts/release_readiness.py --skip-slow
```

## 8. 当前边界

- Streamlit 工具箱已接入“本地维护与升级”入口；
- 页面内可以检查数据库版本、预览待执行迁移、应用 schema 迁移；
- 真正应用迁移必须输入 `APPLY_SCHEMA_MIGRATION`；
- 命令行入口 `scripts/migrate_schema.py` 继续保留，适合脚本化更新和故障排查；
- 后续独立安装包仍需要更完整的启动器和用户数据目录策略。
