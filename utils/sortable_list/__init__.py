import os
import streamlit.components.v1 as components

_component_func = components.declare_component(
    "exam_sortable_list",
    path=os.path.dirname(os.path.abspath(__file__)),
)


def st_sortable_list(items, key=None):
    return _component_func(items=items, key=key, default=None, height=max(160, min(520, 70 * len(items) + 24)))