"""Read native Word equations without flattening them into plain text.

This adapter does not segment questions or write to the question bank. Unsupported
equations stay visible as review markers with their original XML in diagnostics.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"m": M, "w": W}


class UnsupportedWordFormula(ValueError):
    pass


def omml_to_latex(node: ET.Element) -> str:
    """Convert a deliberately bounded OMML subset; never silently drop nodes."""
    tag = node.tag.rsplit("}", 1)[-1]
    def part(name):
        child = node.find("m:" + name, NS)
        if child is None:
            raise UnsupportedWordFormula("缺少公式结构：" + name)
        return omml_to_latex(child)

    if tag == "t":
        text = node.text or ""
        replacements = {"\\": r"\backslash " , "{": r"\{", "}": r"\}",
                        "%": r"\%", "#": r"\#", "&": r"\&",
                        "_": r"\_", "$": r"\$", "^": r"\hat{}"}
        return "".join(replacements.get(c, c) for c in text)
    if tag in {"oMath", "oMathPara", "e", "num", "den", "sup", "sub", "deg", "r"}:
        return "".join(omml_to_latex(c) for c in node)
    if tag in {"rPr", "ctrlPr", "oMathParaPr"}:
        return ""
    if tag == "f":
        kind = node.find("m:fPr/m:type", NS)
        if kind is not None and kind.get("{" + M + "}val", "bar") != "bar":
            raise UnsupportedWordFormula("暂不支持此分式排版")
        return r"\frac{" + part("num") + "}{" + part("den") + "}"
    if tag in {"sSup", "sSub", "sSubSup"}:
        base = "{" + part("e") + "}"
        if tag != "sSup":
            base += "_{" + part("sub") + "}"
        if tag != "sSub":
            base += "^{" + part("sup") + "}"
        return base
    if tag == "rad":
        hide = node.find("m:radPr/m:degHide", NS)
        hidden = hide is not None and hide.get("{" + M + "}val", "1") in {"1", "true", "on"}
        deg_node = node.find("m:deg", NS)
        degree = "" if hidden or deg_node is None else omml_to_latex(deg_node)
        return r"\sqrt" + ("[" + degree + "]" if degree else "") + "{" + part("e") + "}"
    raise UnsupportedWordFormula("暂不支持 Word 公式节点：" + tag)


def read_docx_formula_paragraphs(path: str | Path) -> dict:
    """Return ordered paragraph TeX and diagnostics for human transcription."""
    source = Path(path)
    diagnostics = []
    paragraphs = []
    equation_count = 0
    with ZipFile(source) as archive:
        info = archive.getinfo("word/document.xml")
        if info.file_size > 20 * 1024 * 1024:
            raise ValueError("Word 主文档过大，需拆分后处理")
        raw = archive.read(info)
        if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
            raise ValueError("不支持带 DTD 的 Word XML")
        root = ET.fromstring(raw)
        body = root.find("w:body", NS)
        if body is None:
            raise ValueError("Word 文档缺少正文")

        def render(node, paragraph_index):
            nonlocal equation_count
            if node.tag == "{" + M + "}oMath":
                equation_count += 1
                try:
                    return "$" + omml_to_latex(node) + "$"
                except UnsupportedWordFormula as exc:
                    marker = f"[公式待复核 {equation_count}]"
                    diagnostics.append({"kind": "unsupported_omml", "paragraph_index": paragraph_index,
                                        "marker": marker, "reason": str(exc),
                                        "xml": ET.tostring(node, encoding="unicode")})
                    return marker
            if node.tag == "{" + W + "}t":
                return node.text or ""
            if node.tag in {"{" + W + "}br", "{" + W + "}cr"}:
                return "  \n"
            if node.tag == "{" + W + "}tab":
                return "\t"
            if node.tag.rsplit("}", 1)[-1] in {"object", "drawing", "pict", "AlternateContent"}:
                marker = "[嵌入对象或图片待复核]"
                diagnostics.append({"kind": "embedded_object", "paragraph_index": paragraph_index,
                                    "reason": "图片及 MathType/OLE 对象需要原文件人工核对"})
                return marker
            if node.tag in {"{" + W + "}del", "{" + W + "}moveFrom"}:
                return ""
            return "".join(render(child, paragraph_index) for child in node)

        def iter_paragraphs(node):
            for child in node:
                if child.tag == "{" + W + "}p":
                    yield child
                elif child.tag not in {"{" + W + "}del", "{" + W + "}moveFrom"}:
                    yield from iter_paragraphs(child)

        for index, paragraph in enumerate(iter_paragraphs(body)):
            paragraphs.append({"paragraph_index": index, "tex": render(paragraph, index)})
        extra_parts = [name for name in archive.namelist()
                       if name.startswith(("word/header", "word/footer", "word/footnotes", "word/endnotes"))
                       and name.endswith(".xml")]
        if extra_parts:
            diagnostics.append({"kind": "other_document_parts", "parts": extra_parts,
                                "reason": "本次仅提取正文；页眉页脚和注释另行核对"})
    return {"source_path": str(source.resolve()), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "paragraphs": paragraphs, "equation_count": equation_count,
            "diagnostics": diagnostics, "requires_human_review": True}
