from __future__ import annotations

from typing import Any

ToolSpec = dict[str, Any]

SCRIPT_RUNTIME_API: dict[str, Any] = {
    "functions": ["get_rawdata", "get_graph"],
    "chart_classes": ["BaseChart", "HistogramChart", "PieChart"],
    "result_compatibility": ["BaseChart instance", "legacy dict RESULT"],
}

EXECUTOR_DEFAULT_LIMITS: dict[str, int] = {
    "timeout_seconds": 6,
    "max_output_bytes": 20000,
    "max_cpu_seconds": 6,
    "max_memory_mb": 256,
    "max_concurrent_jobs": 2,
}

EXECUTOR_ALLOWED_IMPORTS: set[str] = {
    "math",
    "statistics",
    "json",
    "datetime",
    "itertools",
    "functools",
    "collections",
    "re",
    "decimal",
    "fractions",
    "random",
}

EXECUTOR_BLOCKED_IMPORT_PREFIXES: tuple[str, ...] = (
    "subprocess",
    "socket",
    "os",
    "pathlib",
    "ctypes",
    "multiprocessing",
    "threading",
    "asyncio",
    "importlib",
    "builtins",
    "sys",
)

EXECUTOR_SAFE_BUILTINS: tuple[str, ...] = (
    "__build_class__",
    "abs",
    "all",
    "any",
    "bool",
    "Exception",
    "dict",
    "enumerate",
    "filter",
    "float",
    "hasattr",
    "int",
    "isinstance",
    "len",
    "list",
    "map",
    "max",
    "min",
    "object",
    "pow",
    "print",
    "range",
    "reversed",
    "round",
    "set",
    "sorted",
    "str",
    "sum",
    "tuple",
    "ValueError",
    "zip",
)


TOOL_SPECS: list[ToolSpec] = [
    {
        "name": "analysis.list_datasets",
        "schema_version": "1.0",
        "description": "List available exam datasets from result directory.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {
            "type": "object",
            "properties": {"datasets": {"type": "array"}},
            "required": ["datasets"],
        },
    },
    {
        "name": "analysis.list_builtins",
        "schema_version": "1.0",
        "description": "List builtin analysis pipelines.",
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
        "output_schema": {
            "type": "object",
            "properties": {"builtins": {"type": "array"}},
            "required": ["builtins"],
        },
    },
    {
        "name": "analysis.run_builtin",
        "schema_version": "1.0",
        "description": "Run a builtin analyzer and return a job.",
        "input_schema": {
            "type": "object",
            "properties": {
                "builtin_id": {"type": "string"},
                "exam_id": {"type": "string"},
                "batch_id": {"type": "string"},
                "recompute": {"type": "boolean"},
                "request_id": {"type": "string"},
            },
            "required": ["builtin_id", "exam_id", "batch_id"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "status": {"type": "string"},
                "output": {"type": "object"},
                "error_code": {"type": "string"},
                "error": {"type": "string"},
            },
            "required": ["job_id", "status"],
        },
    },
    {
        "name": "analysis.save_script",
        "schema_version": "1.0",
        "description": "Create or update a script document.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script_id": {"type": "string"},
                "name": {"type": "string"},
                "language": {"type": "string"},
                "code": {"type": "string"},
            },
            "required": ["name", "code"],
            "additionalProperties": False,
        },
        "output_schema": {"type": "object", "properties": {"script": {"type": "object"}}, "required": ["script"]},
    },
    {
        "name": "analysis.run_script",
        "schema_version": "1.0",
        "description": "Run a script job in restricted Python sandbox.",
        "input_schema": {
            "type": "object",
            "properties": {
                "script_id": {"type": "string"},
                "exam_id": {"type": "string"},
                "batch_id": {"type": "string"},
                "request_id": {"type": "string"},
            },
            "required": ["script_id", "exam_id", "batch_id"],
            "additionalProperties": False,
        },
        "output_schema": {
            "type": "object",
            "properties": {
                "job_id": {"type": "string"},
                "status": {"type": "string"},
                "error_code": {"type": "string"},
                "error": {"type": "string"},
                "output": {"type": "object"},
            },
            "required": ["job_id", "status"],
        },
    },
    {
        "name": "analysis.get_job",
        "schema_version": "1.0",
        "description": "Get one analysis job with output reference.",
        "input_schema": {
            "type": "object",
            "properties": {"job_id": {"type": "string"}},
            "required": ["job_id"],
            "additionalProperties": False,
        },
        "output_schema": {"type": "object", "properties": {"job": {"type": "object"}}, "required": ["job"]},
    },
]
