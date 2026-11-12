"""Measure server-side navigation without starting a browser or AI requests."""
from pathlib import Path
import json
import time
import sys

from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    source = (ROOT / "question_bank_app.py").read_text(encoding="utf-8-sig")
    output = ROOT / "reports" / "navigation_profile"
    output.mkdir(parents=True, exist_ok=True)
    # Include Streamlit's pre-execution work, not just the page body.
    import cProfile
    from streamlit.testing.v1.local_script_runner import LocalScriptRunner
    original_run = LocalScriptRunner._run_script

    def profiled_run(runner, rerun_data):
        profiler = cProfile.Profile()
        try:
            return profiler.runcall(original_run, runner, rerun_data)
        finally:
            profiler.dump_stats(str(output / "latest.prof"))

    LocalScriptRunner._run_script = profiled_run
    # AppTest's temporary source must retain the real application root.
    source = source.replace('os.path.dirname(os.path.abspath(__file__))', repr(str(ROOT)))
    app = AppTest.from_string(source, default_timeout=60)
    timings = []
    routes = ["📘\n项目介绍", "📖\n规范说明", "🛠️\n工具箱", "🔍\n全局浏览\n与编辑", "📘\n项目介绍"]
    for index, route in enumerate(routes):
        if index:
            app.radio(key="main_sidebar_radio").set_value(route)
        else:
            app.session_state["main_nav_selection"] = route
            app.session_state["main_sidebar_radio"] = route
        started = time.perf_counter()
        app.run()
        item = {"route": route, "seconds": round(time.perf_counter() - started, 4),
                "errors": [exc.message for exc in app.exception]}
        timings.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
        time.sleep(0.1)
        import shutil
        shutil.copy2(output / "latest.prof", output / f"route_{index}.prof")
    (output / "timings.json").write_text(json.dumps(timings, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
