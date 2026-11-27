"""Space out Instagram requests and pause after rate limiting."""
from __future__ import annotations

import asyncio
import random
import time


class Pacer:
    def __init__(self, min_interval: float = 5.0, jitter: float = 3.0, *,
                 clock=time.monotonic, sleep=asyncio.sleep, rand=random.uniform):
        self._min = min_interval
        self._jitter = jitter
        self._clock = clock
        self._sleep = sleep
        self._rand = rand
        self._last: float | None = None
        self._paused_until = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        """Sleep until at least min_interval + jitter has passed since the last wait."""
        async with self._lock:
            if self._last is not None:
                gap = self._min + self._rand(0, self._jitter)
                remaining = self._last + gap - self._clock()
                if remaining > 0:
                    await self._sleep(remaining)
            self._last = self._clock()

    def pause(self, seconds: float = 600) -> None:
        self._paused_until = self._clock() + seconds

    def paused_for(self) -> float:
        return max(0.0, self._paused_until - self._clock())
