"""PrimeBrush — K12 教育绘图库（声明式 YAML → SVG）。

PrimeBrush 是 EducationPaperDesignAutomation 的核心护城河组件之一。
通过声明式 YAML 描述图形，生成高质量 SVG，可嵌入 ExamCompiler 的试卷流水线
或在浏览器端独立运行（未来通过 WebAssembly）。

公共 API：
  parse_primebrush(raw) -> PrimeBrushDoc
  render(doc, *, seed) -> str
"""

from solaire.primebrush.api import PrimeBrushDoc, parse_primebrush, render

__all__ = ["parse_primebrush", "render", "PrimeBrushDoc"]
__version__ = "0.2.0"
