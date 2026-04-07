"""EduAnalysis: learning analytics core for tool-calling and human APIs."""

from .contracts import TOOL_SPECS
from .core import invoke_tool, list_tools

__all__ = ["TOOL_SPECS", "invoke_tool", "list_tools"]
