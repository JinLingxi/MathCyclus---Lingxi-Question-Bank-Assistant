# 独立讲义与训练模板

这是可选模板，不替换现有界面、MathCyclus_book.cls、main.tex 或 Test Paper Group 下的原模板。

## 生成与编译

在项目根目录运行：

```powershell
.venv\Scripts\python.exe scripts/export_handout.py --sample --output exports/handout_demo
.venv\Scripts\python.exe scripts/export_handout.py --sample --training --monochrome --output exports/training_demo
.venv\Scripts\python.exe scripts/export_handout.py --question-id Q000001 --question-id Q001205 --output exports/selected_handout
```

输出目录必须不存在；--sample 和 --question-id 只能选择一种。默认只读正式题，不读取未批准草稿，也不修改题目数据。--db 可指定另一份 SQLite。图片缺失时终止，不发布半成品目录；多次导出不会覆盖已有资料。

进入生成的目录后运行 xelatex -interaction=nonstopmode -halt-on-error -no-shell-escape main.tex。需要 ctexart、amsmath、graphicx、adjustbox、enumitem、xparse、tcolorbox 等依赖；本机 TeX Live 2024 + XeLaTeX 已验证。题目含额外自定义宏、外部字体或特殊绘图包时仍需补相应依赖；本样张不代表任意历史 TeX 都已完成兼容测试。

## 样式与模式

- MCRecall：知识回顾。
- MCMethod：方法提示。
- MCWarning：易错提醒。
- MCExtension：拓展思考。

四种环境均可使用可选的中文标题。默认彩色、低饱和度、细侧线，可跨页；--monochrome 使用灰阶标题和线条，不自动改变用户图片的颜色。--training 在生成 PDF 时隐藏 answer/solutions 并保留书写空间；源 TeX 仍可包含答案，不作为去除答案数据的脱敏方式。原题无答案和解析时允许为空，不补写内容。

题干和选项复用现有 TeX 导出，图片复制和引用查找统一走已有服务。模板将图片限制在当前行宽以内；过长公式需由原作者用 aligned 等合理分行，不做可能改变数学语义的自动拆式。

## Lucide 状态

当前后端为 tcolorbox，并非 lucide-admonitions 的实现。本机 kpsewhich 未找到 lucide-admonitions.sty 或 lucide.sty，网络下载请求受环境限制，不能核验其环境命令和依赖。因此不伪造 API、不静默加载未知宏包，也未修改全局 TeX 安装。未来取得官方文档与依赖后，可在这些语义环境后接入 Lucide 图标/盒子，并重新执行同一组样张验证。

## 本次验证产物

reports/handout_template_validation 下有彩色/黑白讲义、彩色/黑白训练四套合成样张，以及 formal_handout、formal_training 两份正式题只读导出样本。每个目录包含 main.tex、body.tex、样式文件和已编译 main.pdf。合成样张重点覆盖中文标题、分式、长公式主动分行、选项、向量图、空答案和长提示框跨页；正式样本包含 Q000001、Q001205、Q000896，以及两张真实配图。

验证报告 reports/handout_template_validation_checks_20261103.json 核对六份 PDF 的内容完整、训练版答案隐藏、跨页内容、灰阶像素、图像边界与编译日志的溢出/缺字。可运行 scripts/verify_handout_samples.py --directory reports/handout_template_validation --output 新报告.json 重查。
