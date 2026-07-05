"""SQS worker CLI — run as a separate process/container from the API."""

from __future__ import annotations

import asyncio

from app.workers.consumer import run_worker


def main() -> None:
    asyncio.run(run_worker())


if __name__ == "__main__":
    main()
