"""Run downloader subprocesses with a hard timeout."""
from __future__ import annotations

import asyncio
import os
import signal
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .errors import Failed


@dataclass
class ProcResult:
    returncode: int
    stdout: str
    stderr: str


ProcRunner = Callable[[list[str], float], Awaitable[ProcResult]]


async def run(args: list[str], timeout: float = 300) -> ProcResult:
    """Run `args`; kill the whole process group and raise Failed on timeout."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
    except OSError as exc:
        raise Failed(f"couldn't start {os.path.basename(args[0])}: {exc.strerror}") from None
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError) as exc:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        await proc.wait()
        if isinstance(exc, asyncio.CancelledError):
            raise
        raise Failed(f"timed out after {int(timeout)}s") from None
    return ProcResult(
        proc.returncode if proc.returncode is not None else -1,
        out.decode("utf-8", errors="replace"),
        err.decode("utf-8", errors="replace"),
    )
