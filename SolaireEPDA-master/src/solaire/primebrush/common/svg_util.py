from __future__ import annotations

import html
import xml.etree.ElementTree as ET


def escape_text(s: str) -> str:
    return html.escape(s, quote=False)


def svg_root(
    width: float,
    height: float,
    inner: str,
    *,
    xmlns: str = "http://www.w3.org/2000/svg",
) -> str:
    return (
        f'<svg xmlns="{xmlns}" width="{width:.2f}" height="{height:.2f}" '
        f'viewBox="0 0 {width:.2f} {height:.2f}">\n{inner}\n</svg>'
    )


def element_to_string(elem: ET.Element) -> str:
    return ET.tostring(elem, encoding="unicode", default_namespace=None)
