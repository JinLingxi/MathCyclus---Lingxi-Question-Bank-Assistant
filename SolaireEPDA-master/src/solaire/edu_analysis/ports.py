"""Dependency injection ports for edu_analysis.

此模块定义 edu_analysis 所需的外部数据访问接口（Protocol），
由 web 层在启动时注入实现，edu_analysis 内部不直接导入 web 层。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ResultDataPort(Protocol):
    """Interface for accessing exam result data.

    web 层的 result_service 须实现此协议并通过 configure() 注入。
    """

    def list_exam_results(self, project_root: Path) -> list[dict[str, Any]]:
        """Return list of past exams (newest first) with basic metadata."""
        ...

    def compute_statistics(
        self,
        project_root: Path,
        exam_id: str,
        batch_id: str,
    ) -> dict[str, Any]:
        """Compute and return statistics for a score batch."""
        ...

    def get_score_analysis(
        self,
        project_root: Path,
        exam_id: str,
        batch_id: str,
    ) -> dict[str, Any]:
        """Return cached analysis for a score batch (recompute if stale)."""
        ...


class _NotConfiguredPort:
    """Placeholder that raises a clear error if the port is not configured."""

    def list_exam_results(self, project_root: Path) -> list[dict[str, Any]]:
        raise RuntimeError(
            "edu_analysis result data port not configured. "
            "Call solaire.edu_analysis.configure(result_port=...) before use."
        )

    def compute_statistics(
        self,
        project_root: Path,
        exam_id: str,
        batch_id: str,
    ) -> dict[str, Any]:
        raise RuntimeError(
            "edu_analysis result data port not configured. "
            "Call solaire.edu_analysis.configure(result_port=...) before use."
        )

    def get_score_analysis(
        self,
        project_root: Path,
        exam_id: str,
        batch_id: str,
    ) -> dict[str, Any]:
        raise RuntimeError(
            "edu_analysis result data port not configured. "
            "Call solaire.edu_analysis.configure(result_port=...) before use."
        )


# 模块级单例，由 web 层在启动时通过 configure() 注入
_result_data_port: ResultDataPort = _NotConfiguredPort()  # type: ignore[assignment]


def configure(result_port: ResultDataPort) -> None:
    """Configure the result data port. Must be called before any analysis operations.

    web 层在应用启动时调用此函数注入实现：
        from solaire.edu_analysis.ports import configure
        configure(result_port=ResultServiceAdapter())
    """
    global _result_data_port
    _result_data_port = result_port


def get_result_port() -> ResultDataPort:
    """Return the configured result data port."""
    return _result_data_port
