from __future__ import annotations

import sys

import uvicorn

from .app import create_app
from .config import Settings


def main() -> None:
    try:
        settings = Settings.from_env()
        settings.validate_for_startup()
    except ValueError as exc:
        print(f"AstrAutoAnima Hub configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
    uvicorn.run(
        create_app(settings),
        host=settings.host,
        port=settings.port,
        log_level="info",
        access_log=True,
    )


if __name__ == "__main__":
    main()

