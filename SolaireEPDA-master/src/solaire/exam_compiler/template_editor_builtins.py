"""Keys edited by the template workspace built-in form (single source for API + frontend)."""

from __future__ import annotations

# Order is stable for JSON arrays consumed by the web UI.
TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED: tuple[str, ...] = (
    "margin_cm",
    "body_font_size_pt",
    "show_binding_line",
    "show_name_column",
    "mermaid_pdf",
    "primebrush_pdf",
)

TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS: frozenset[str] = frozenset(TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED)
