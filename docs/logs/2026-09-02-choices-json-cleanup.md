# choices_json 归一化日志

> 时间：2026-09-02  
> 目标：把历史 `choices_json` 统一为“内部 TeX”存储，保留导出兼容 `\choice{{...}}`。

## 做了什么

- 新增 `services/choice_format_service.py`，统一处理选项的包裹 / 拆包 / 归一化。
- 新增 `scripts/normalize_question_choices_json.py`，支持 dry-run 和 `--apply` 两种模式。
- 新增 `scripts/smoke_question_choices_json_cleanup.py`，验证迁移后数据库与导出链路。
- 更新 `services/export_service.py`，让导出继续走统一的 choice 包裹规则。
- 更新 `scripts/smoke_source_export_service.py`，补齐 unwrap / wrap 回归检查。

## 结果

- 扫描题目数：893
- 需要修改题目数：496
- 需要拆包的选项数：1983
- 已经是内部 TeX 的非空选项数：16
- `question_revision` 新增：496

## 备份与报告

- 备份库：`data/backups/mathcyclus_choices_cleanup_20260902_185555.sqlite3`
- 最终报告：`reports/choices_json_cleanup_20260902_185555.md`

## 校验

- `python scripts/smoke_question_choices_json_cleanup.py --db data/mathcyclus.sqlite3`
- `python scripts/smoke_source_export_service.py --db data/mathcyclus.sqlite3`

## 结论

- 当前正式库已完成 choices 归一化。
- 前端继续填写内部 TeX，导出仍保持 `\choice{{...}}` 兼容，不需要改用户入口。
