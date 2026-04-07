"""LaTeX Jinja 模板路径解析（独立于 pipeline 包，避免与 template_loader 循环导入）。"""

from __future__ import annotations

from pathlib import Path


def bundled_latex_dir() -> Path:
    """内置 .tex.j2 所在目录（随包分发）。"""
    return Path(__file__).resolve().parent / "templates" / "latex"


def latex_jinja_loader_dirs(template_yaml_dir: Path, latex_base: str) -> list[Path]:
    """
    Jinja ChoiceLoader 搜索路径：模板 YAML 所在目录优先，其次内置目录。
    这样 latex_base 仅存在于内置目录时也能渲染，且项目内可放同名 fragment 覆盖 ``include``。
    """
    project_dir = template_yaml_dir.resolve()
    bundled = bundled_latex_dir()
    in_project = (project_dir / latex_base).is_file()
    in_bundled = (bundled / latex_base).is_file()
    if not in_project and not in_bundled:
        raise FileNotFoundError(
            f"latex_base not found: {latex_base!r} (tried {project_dir} and {bundled})"
        )
    ordered: list[Path] = []
    if project_dir.is_dir():
        ordered.append(project_dir)
    if bundled.is_dir() and bundled.resolve() not in ordered:
        ordered.append(bundled.resolve())
    return ordered


def list_shipped_latex_j2_names() -> list[str]:
    """内置可用的主模板文件名列表（供 Web 下拉）。"""
    d = bundled_latex_dir()
    if not d.is_dir():
        return []
    return sorted(p.name for p in d.glob("*.tex.j2"))
