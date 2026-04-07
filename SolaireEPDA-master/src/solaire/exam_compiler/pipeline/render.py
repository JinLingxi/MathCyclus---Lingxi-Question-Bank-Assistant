"""Jinja2 → .tex; latex_escape on metadata, |safe on question LaTeX."""

from __future__ import annotations

from pathlib import Path

from jinja2 import ChoiceLoader, Environment, FileSystemLoader, select_autoescape

from solaire.exam_compiler.choice_layout import choice_option_pairs, resolve_choice_layout
from solaire.exam_compiler.latex_jinja_paths import latex_jinja_loader_dirs
from solaire.exam_compiler.latex_util import build_graphicspath_command, latex_escape_text, latex_safe_label
from solaire.exam_compiler.loaders.questions import LoadedQuestions
from solaire.exam_compiler.pipeline.hydrate import HydratedExam, HydratedQuestion
from solaire.exam_compiler.pipeline.primebrush_expand import expand_hydrated_for_latex


def _jinja_env(loader_dirs: list[Path]) -> Environment:
    loaders = [FileSystemLoader(str(d.resolve())) for d in loader_dirs if d.is_dir()]
    env = Environment(
        loader=ChoiceLoader(loaders),
        autoescape=select_autoescape(enabled_extensions=()),  # no HTML autoescape on .tex
        block_start_string="[%",
        block_end_string="%]",
        variable_start_string="[[",
        variable_end_string="]]",
        comment_start_string="[#",
        comment_end_string="#]",
    )

    def latex_escape_filter(s: object) -> str:
        return latex_escape_text("" if s is None else str(s))

    env.filters["latex_escape"] = latex_escape_filter
    env.filters["safe_label"] = lambda s: latex_safe_label(str(s))
    return env


def _build_section_questions(
    questions: list[HydratedQuestion],
    meta: dict,
) -> list[dict]:
    """Assign global numbering and template-facing fields per question-yaml-by-type.md."""
    qs_out: list[dict] = []
    global_n = 0
    i = 0
    n = len(questions)
    while i < n:
        hq = questions[i]
        q = hq.item
        if q.group_root_id is None:
            global_n += 1
            opt = None
            if q.options:
                opt = dict(sorted(q.options.items()))
            layout = resolve_choice_layout(meta, opt) if opt else "stack"
            opt_pairs = choice_option_pairs(opt) if opt else []
            qs_out.append(
                {
                    "qualified_id": hq.qualified_id,
                    "content": q.content,
                    "options": opt,
                    "choice_layout": layout,
                    "choice_option_items": opt_pairs,
                    "answer": q.answer,
                    "analysis": q.analysis,
                    "type": q.type,
                    "group_id": None,
                    "group_material": None,
                    "show_group_material": False,
                    "group_member_index": None,
                    "display_number": str(global_n),
                    "item_score": hq.item_score,
                }
            )
            i += 1
            continue

        # Contiguous rows from one group file (same qualified_id)
        j = i + 1
        while j < n and questions[j].qualified_id == hq.qualified_id:
            j += 1
        run = questions[i:j]
        u = q.unified
        material = q.group_material or ""

        if u is False:
            global_n += 1
            major = global_n
            for k, hqk in enumerate(run):
                qk = hqk.item
                sub_i = k + 1
                dn = f"{major}.{sub_i}"
                body = qk.content
                if k == 0:
                    body = (
                        f"\\noindent\\textbf{{{major}}}.\\par\\smallskip\n"
                        f"{material}\n"
                        f"\\par\\smallskip\n"
                        f"\\textbf{{{dn}}}\\quad "
                    ) + body
                else:
                    body = f"\\textbf{{{dn}}}\\quad " + body
                opt = None
                if qk.options:
                    opt = dict(sorted(qk.options.items()))
                layout = resolve_choice_layout(meta, opt) if opt else "stack"
                opt_pairs = choice_option_pairs(opt) if opt else []
                qs_out.append(
                    {
                        "qualified_id": hqk.qualified_id,
                        "content": body,
                        "options": opt,
                        "choice_layout": layout,
                        "choice_option_items": opt_pairs,
                        "answer": qk.answer,
                        "analysis": qk.analysis,
                        "type": qk.type,
                        "group_id": q.group_root_id,
                        "group_material": material if k == 0 else None,
                        "show_group_material": False,
                        "group_member_index": sub_i,
                        "display_number": dn,
                        "item_score": hqk.item_score,
                    }
                )
            i = j
            continue

        # unified is a concrete question type string: material before first sub-question; each sub uses one global number
        assert isinstance(u, str)
        for k, hqk in enumerate(run):
            qk = hqk.item
            global_n += 1
            dn = str(global_n)
            body = qk.content
            if k == 0 and material:
                body = (
                    f"\\par\\vspace{{0.3em}}\\noindent\\begingroup\\small\\textbf{{【材料】}}\\endgroup\\par\n"
                    f"\\noindent {material}\n\\par\\vspace{{0.35em}}\n"
                ) + body
            opt = None
            if qk.options:
                opt = dict(sorted(qk.options.items()))
            layout = resolve_choice_layout(meta, opt) if opt else "stack"
            opt_pairs = choice_option_pairs(opt) if opt else []
            qs_out.append(
                {
                    "qualified_id": hqk.qualified_id,
                    "content": body,
                    "options": opt,
                    "choice_layout": layout,
                    "choice_option_items": opt_pairs,
                    "answer": qk.answer,
                    "analysis": qk.analysis,
                    "type": qk.type,
                    "group_id": q.group_root_id,
                    "group_material": material if k == 0 else None,
                    "show_group_material": False,
                    "group_member_index": k + 1,
                    "display_number": dn,
                    "item_score": hqk.item_score,
                }
            )
        i = j

    return qs_out


def render_tex(
    hydrated: HydratedExam,
    template_yaml_dir: Path,
    latex_base: str,
    *,
    show_answers: bool,
) -> str:
    dirs = latex_jinja_loader_dirs(template_yaml_dir, latex_base)
    env = _jinja_env(dirs)
    tpl = env.get_template(latex_base)

    meta = hydrated.metadata
    graphic_paths: list[Path] = []
    seen_gp: set[Path] = set()
    for root in hydrated.graphicspath_roots:
        r = root.resolve()
        for p in ((r / "image").resolve(), r):
            if p not in seen_gp:
                seen_gp.add(p)
                graphic_paths.append(p)
    graphicspath_cmd = build_graphicspath_command(graphic_paths)

    sections_data = []
    for sec in hydrated.sections:
        qs = _build_section_questions(sec.questions, meta)
        sections_data.append(
            {
                "section_id": sec.section_id,
                "type": sec.type,
                "score_per_item": sec.score_per_item,
                "questions": qs,
                "describe": sec.describe,
            }
        )

    return tpl.render(
        metadata=meta,
        exam_id=hydrated.exam_id,
        graphicspath_command=graphicspath_cmd,
        sections=sections_data,
        show_answers=show_answers,
        latex_escape=latex_escape_text,
    )


def write_student_teacher_tex(
    hydrated: HydratedExam,
    template_yaml_dir: Path,
    latex_base: str,
    work_dir: Path,
    loaded: LoadedQuestions,
) -> tuple[Path, Path]:
    work_dir.mkdir(parents=True, exist_ok=True)
    expand_hydrated_for_latex(hydrated, loaded)
    student_tex = work_dir / "student_paper.tex"
    teacher_tex = work_dir / "teacher_paper.tex"
    student_tex.write_text(
        render_tex(hydrated, template_yaml_dir, latex_base, show_answers=False),
        encoding="utf-8",
    )
    teacher_tex.write_text(
        render_tex(hydrated, template_yaml_dir, latex_base, show_answers=True),
        encoding="utf-8",
    )
    return student_tex, teacher_tex
