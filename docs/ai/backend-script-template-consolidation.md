# 后台、历史脚本与讲义模板整理

## 后台重复逻辑

services/export_service.py 的图片占位正则、引用提取、别名、图形路径查找改为复用 services/asset_service.py。导出模块继续暴露原有函数名与参数，UI 的 import 和调用不变。正式资源导出只查 file_path，不拿草稿 source_path 或 planned_file_path 替代缺失的正式资源。

includegraphics 和 questionasset 两个图片复制入口合用 _copy_export_figure，保留原文件名、同名冲突时 -2/-3 等后缀，以及原来的报告结构。没有大规模拆分主程序，也没有改默认导出内容或数据库。回归覆盖中文与绝对/相对图形路径、选项引用、同名图片冲突、原文件字节保留，以及现有试卷/专题/筛选/旧 TeX 导出。

## 历史脚本收口

scripts/archive_maintenance_sources.py 通过静态目录和调用图建立历史源码归档。193 个历史候选脚本与 9 个关联脚本形成 202 个源文件清单；归档包含原路径、SHA-256、静态关联方、写入线索和边界说明。逐文件解压读取、哈希和 AST 解析验证，不运行脚本。

本次只读预演为 reports/maintenance_sources_preflight_20261103.json，已执行清单为 reports/maintenance_sources_archived_20261103.json，归档为 data/backups/cold_archives/maintenance_sources_20261103.zip。全部原脚本保留原位置，未删除或改造一次性脚本的行为，避免破坏已有调用或工作区外的手工维护流程。

重新预演可使用虚拟环境 Python 模块 scripts.archive_maintenance_sources，指定 --archive 新ZIP路径 --report 新JSON路径。只有显式 --apply 才创建 ZIP，已有归档/报告不覆盖。归档仅包含 scripts 的源码和能静态发现的本地脚本依赖，不包含服务源码、实际题源或凭据，不能独立执行历史录题任务；完整源码仍需项目版本库保留。静态调用图不能穷尽动态引用，因此不把候选认定为无用。

## 可选讲义/训练导出

新服务 services/handout_export_service.py 和入口 scripts/export_handout.py 生成独立新目录，默认导出 UI 不变。模板、使用方法和已验证的 PDF 见 templates/handouts/README.md。知识回顾、方法提示、易错提醒、拓展思考采用语义环境，先验证 tcolorbox 实现。

四份合成样张以及两份正式题样本均通过 XeLaTeX 编译、答案隐藏、跨页、图片行宽和日志检查。合成黑白样张光栅化后没有彩色像素。正式样本成功带出两张图片，无答案/解析的题目不要求补录。

lucide-admonitions 尚未安装且网络不可用，因此其实际盒子 API、图标依赖和中文兼容仍待验证。这一项未冒充完成；现有样张和导出工具可独立使用，未来接入 Lucide 时不必改题目原始数据。

本轮未修改 UI、正式题、草稿、审核状态、旧图或原始 TeX；只增加可选输出、历史源码归档和小范围后台复用。
