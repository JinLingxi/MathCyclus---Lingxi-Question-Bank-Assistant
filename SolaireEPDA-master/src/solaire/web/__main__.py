"""Run Uvicorn: ``python -m solaire.web`` or ``solaire-web``."""

from __future__ import annotations


def main() -> None:
    import uvicorn

    uvicorn.run("solaire.web.app:app", host="127.0.0.1", port=8000, reload=False)


if __name__ == "__main__":
    main()
