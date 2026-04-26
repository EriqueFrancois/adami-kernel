from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
async def _cleanup_background_tasks() -> None:
    """Cancel leaked asyncio tasks after each async test.

    Some tests (and the code under test) may spawn background tasks via
    `asyncio.create_task()` without a strict lifecycle owner. If those tasks
    survive test teardown, pytest (and the GitHub Actions runner) can hang or
    emit `ResourceWarning: unclosed event loop`.
    """
    yield

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        # Not running inside an event loop (sync test or already torn down).
        return

    current = asyncio.current_task(loop=loop)
    pending = [t for t in asyncio.all_tasks(loop=loop) if t is not current and not t.done()]
    if not pending:
        return

    for t in pending:
        t.cancel()

    await asyncio.gather(*pending, return_exceptions=True)

