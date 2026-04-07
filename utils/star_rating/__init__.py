import os
import streamlit.components.v1 as components

# Create a _component_func
_component_func = components.declare_component(
    "star_rating",
    path=os.path.dirname(os.path.abspath(__file__))
)

def st_star_rating(label="难度星级：", value=0.0, max_stars=6, key=None):
    """
    Create a new instance of "star_rating".
    """
    component_value = _component_func(
        label=label,
        value=value,
        max_stars=max_stars,
        key=key,
        default=value,
        height=35
    )
    return component_value
