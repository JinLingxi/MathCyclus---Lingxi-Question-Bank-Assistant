"""Desktop 打包入口：由 Nuitka 编译为独立进程，供 Tauri 以 sidecar 方式拉起。"""

from __future__ import annotations

import argparse


def main() -> None:
    import uvicorn

    parser = argparse.ArgumentParser(description="SolEdu 本地服务")
    parser.add_argument("--port", type=int, default=8000, help="监听端口")
    args = parser.parse_args()
    uvicorn.run(
        "solaire.web.app:app",
        host="127.0.0.1",
        port=args.port,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
