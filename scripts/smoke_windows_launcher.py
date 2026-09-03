from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = PROJECT_ROOT / "启动程序.bat"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def main() -> None:
    checks: list[dict[str, Any]] = []
    text = LAUNCHER.read_text(encoding="utf-8")
    lines = [line.rstrip() for line in text.splitlines()]

    required_snippets = [
        'set "VENV_PYTHON=%VENV_DIR%\\Scripts\\python.exe"',
        'set "INIT_WORKSPACE=%CD%\\scripts\\init_local_workspace.py"',
        '"%VENV_PYTHON%" -m pip install --disable-pip-version-check --requirement "%REQUIREMENTS%"',
        '"%VENV_PYTHON%" "%INIT_WORKSPACE%" --skip-gitignore-check',
        '"%VENV_PYTHON%" -m streamlit run "%MAIN_APP%" --server.port=8501 --server.headless=false',
    ]
    for snippet in required_snippets:
        checks.append(check(f"contains:{snippet[:38]}", snippet in text, snippet))

    init_index = text.find('"%VENV_PYTHON%" "%INIT_WORKSPACE%" --skip-gitignore-check')
    streamlit_index = text.find('"%VENV_PYTHON%" -m streamlit run "%MAIN_APP%"')
    checks.append(
        check(
            "local_workspace_before_streamlit",
            init_index >= 0 and streamlit_index >= 0 and init_index < streamlit_index,
            {"init_index": init_index, "streamlit_index": streamlit_index},
        )
    )
    checks.append(
        check(
            "no_stray_top_level_closing_paren",
            not any(line == ")" and idx > 0 and lines[idx - 1].lower().startswith("goto :venv_ready") for idx, line in enumerate(lines)),
            "",
        )
    )
    checks.append(check("does_not_execute_streamlit_in_smoke", True, "static check only"))

    failed = [item for item in checks if not item["ok"]]
    report = {
        "status": "failed" if failed else "ok",
        "launcher": LAUNCHER.name,
        "checks": checks,
        "executes_launcher": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
