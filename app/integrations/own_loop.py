"""Run a Playwright coroutine on its own event loop, in a worker thread (D-117).

Playwright starts a driver subprocess. On Windows, `uvicorn --reload` serves on a SelectorEventLoop, which can't
start subprocesses (`NotImplementedError`), so the live page capture and the demo's PayPal window failed there.
A fresh loop in a thread (a Proactor loop on Windows) works under any server, and the server's loop stays free.
"""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Awaitable, Callable
from typing import Any, TypeVar

T = TypeVar("T")


def _run(coro_fn: Callable[..., Awaitable[T]], args: tuple[Any, ...], kwargs: dict[str, Any]) -> T:
    factory = asyncio.ProactorEventLoop if sys.platform == "win32" else None
    with asyncio.Runner(loop_factory=factory) as runner:
        return runner.run(coro_fn(*args, **kwargs))  # type: ignore[arg-type]


async def run_on_own_loop(coro_fn: Callable[..., Awaitable[T]], *args: Any, **kwargs: Any) -> T:
    return await asyncio.to_thread(_run, coro_fn, args, kwargs)
