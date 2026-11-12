# 外部题库设计吸收与落地边界

本轮参考本地 JudgePeach/math-question-bank 源码归档，独立实现适合现有 SQLite、Streamlit 和 TeX 工作流的改进。源码评估见 reports/external_review/JudgePeach-MathBank-源码评估.md。外部代码采用 AGPL v3，本轮没有复制其实现。编辑器与组卷组件交互按用户要求留待单独讨论。

## 已接入现有流程

- 查重的完全相同分类同时核对题干、选项内容与顺序、题型，并对配图保留人工核对要求。归一化排名不等于数学等价证明，未识别的 TeX 命令差异也不直接判为完全相同。
- 审核页在现有相似题 ID 链接旁提供数字、变量、关系符号、条件词、区间或选项的差异提示。维持点击 ID 查看悬浮预览。
- CSV 扫描入口统一调用同一分类规则，取消仅凭归一化题干哈希直接判重复的旁路。来源位置冲突与内容相似分别报告。
- 资源引用检查覆盖选择题选项。登记了 SHA-256 的图片如果内容变化或无法读取，会阻止草稿审核、提交，并在正式题质量检查中报告。新建草稿资产登记文件哈希，旧资产不批量改写。
- PDF 候选转入草稿时保留 alias、原始 PDF、页码、裁剪框、坐标单位、题目归属。教材来源 book_links 和知识板块 knowledge_areas 在 get_question_bundle 中分别返回；知识板块保留 source、confidence、is_primary，不推断人工确认状态。

## 来源与裁剪复核协议

services/source_review_service.py 提供 make_source_review 与 validate_source_review，供导入脚本或后续界面调用。目前没有新增视觉复核表单，也没有替历史资产自动补已通过记录。

资产 extra.source_region 需含 source_path、从零开始的 page_index、四坐标 box、anchor_id；coordinate_space 支持 pdf_points 或 page_pixels，缺省为 pdf_points。像素坐标仅对对应页面渲染有效，调用方应保留渲染参数或页面文件。

make_source_review 接收明确复核人和四项布尔观察：complete_figure（图形完整）、readable_labels（标注清楚）、no_foreign_content（无其他题目内容）、correct_anchor（归属正确）。返回值存入同一 extra 的 source_review。它记录调用方提供的观察，不执行图像语义判断，也不是身份认证或防篡改签名。

来源文件字节、图片字节、页码、裁剪坐标、坐标单位或归属变化，记录失效。已有 source_review 的资产在常规资源检查中验证；失效、不完整或未通过的记录阻止提交。没有记录的历史资产保持原有审核流程，不把缺记录视为视觉通过。

## Word 公式提取工具

在项目根目录使用虚拟环境 Python 运行 scripts/inspect_word_formulas.py，位置参数为原 DOCX 文件，--output 指定新的 JSON 报告路径。输出路径必须尚不存在。

工具只读 DOCX 正文。报告包含原文件 SHA-256、按文档顺序的段落、公式数和诊断。原生 OMML 支持普通文本、横线分式、根式、上下标及其嵌套。显式换行输出两个空格加换行，不使用 TeX 的 par 命令。

暂不支持的 OMML（如矩阵、复杂积分或分段结构）保留待复核标记和原始 XML；图片、MathType/OLE 对象保留显式诊断，不执行对象。页眉页脚、脚注与尾注另行核对。它尚未接入上传界面或自动分题，不生成已批准草稿，不提供 DOCX 导出。当前环境未安装 Pandoc，也未完成真实 Word 应用端导出验证。

## 验收与不变量

unittest 模块：test_question_similarity_review、test_source_review、test_word_formulas、test_knowledge_source_separation。覆盖选项变化、图像选项、区间差异、审核后换图禁止提交、来源证据失效、Word 嵌套公式与不支持对象，以及教材/知识板块独立性。审核页、资源、质量、相似度、来源关系与统计另有冒烟脚本。

人工二次审核仍是正式入库前提；答案和解析允许为空；不自动合并、删除重复题；不批量改变历史相似报告。本轮未修改正式题数据，未执行题目入库。
