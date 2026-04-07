"""ExamCompiler 公共 API 门面（Facade）。

web 层及外部模块只从此文件导入 exam_compiler 的符号，
不得深入 exam_compiler 的内部子包（pipeline/、loaders/ 等）。

维护约定：
- 新增对外接口时，在此文件 __all__ 中登记，并在 ARCHITECTURE.md 的"已登记的跨模块依赖"表格更新。
- 删除或重命名接口时，先在此文件中标记 deprecated，保留一个版本后再删除。
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# 领域模型（可序列化 Pydantic 模型）
# --------------------------------------------------------------------------
from solaire.exam_compiler.models import (
    BankRecord,
    ExamConfig,
    ExamTemplate,
    QuestionGroupRecord,
    QuestionItem,
    QuestionLibraryRef,
    SelectedSection,
    parse_bank_root,
    question_group_to_author_dict,
    question_item_to_author_dict,
    strip_hydrate_fields,
)

# --------------------------------------------------------------------------
# 加载器
# --------------------------------------------------------------------------
from solaire.exam_compiler.loaders.questions import (
    iter_question_files,
    load_all_questions,
    load_questions_from_yaml_file,
)
from solaire.exam_compiler.loaders.template_loader import (
    load_template,
    resolve_template_yaml_path,
)

# --------------------------------------------------------------------------
# 流水线（Pipeline）
# --------------------------------------------------------------------------
from solaire.exam_compiler.pipeline.build import build_exam_pdfs, precheck_exam_latex_build
from solaire.exam_compiler.pipeline.validate import validate_exam
from solaire.exam_compiler.pipeline.compile_tex import (
    LatexmkError,
    format_latexmk_failure_message,
)
from solaire.exam_compiler.pipeline.diagram_expand import expand_diagram_fences_in_text
from solaire.exam_compiler.pipeline.primebrush_expand import strip_primebrush_fences_for_preview
from solaire.exam_compiler.pipeline.math_fragment_check import analyze_math_static_for_loaded

# --------------------------------------------------------------------------
# 模板编辑器相关
# --------------------------------------------------------------------------
from solaire.exam_compiler.template_editor_builtins import (
    TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED,
)
from solaire.exam_compiler.template_metadata_materialize import (
    materialize_metadata_defaults_for_editor,
)
from solaire.exam_compiler.template_parsed_models import (
    EditorMetadataDefaultsBody,
    TemplateParsedResponse,
)

# --------------------------------------------------------------------------
# LaTeX 基础设施
# --------------------------------------------------------------------------
from solaire.exam_compiler.latex_jinja_paths import (
    bundled_latex_dir,
    latex_jinja_loader_dirs,
    list_shipped_latex_j2_names,
)
from solaire.exam_compiler.latex_metadata_ui import load_latex_metadata_ui_fields

__all__ = [
    # 领域模型
    "BankRecord",
    "ExamConfig",
    "ExamTemplate",
    "QuestionGroupRecord",
    "QuestionItem",
    "QuestionLibraryRef",
    "SelectedSection",
    "parse_bank_root",
    "question_group_to_author_dict",
    "question_item_to_author_dict",
    "strip_hydrate_fields",
    # 加载器
    "iter_question_files",
    "load_all_questions",
    "load_questions_from_yaml_file",
    "load_template",
    "resolve_template_yaml_path",
    # 流水线
    "build_exam_pdfs",
    "precheck_exam_latex_build",
    "validate_exam",
    "LatexmkError",
    "format_latexmk_failure_message",
    "expand_diagram_fences_in_text",
    "strip_primebrush_fences_for_preview",
    "analyze_math_static_for_loaded",
    # 模板编辑器
    "TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED",
    "materialize_metadata_defaults_for_editor",
    "EditorMetadataDefaultsBody",
    "TemplateParsedResponse",
    # LaTeX 基础设施
    "bundled_latex_dir",
    "latex_jinja_loader_dirs",
    "list_shipped_latex_j2_names",
    "load_latex_metadata_ui_fields",
]
