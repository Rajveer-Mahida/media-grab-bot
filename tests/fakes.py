"""Test doubles shared across tests."""
from __future__ import annotations

import json
from pathlib import Path

from bot.engine.proc import ProcResult


class FakeRun:
    """Scripted ProcRunner. Each step: (files_to_create, returncode, stdout_template, stderr, metadata).

    stdout_template may use {wd} for the -D / -o directory found in args.
    """

    def __init__(self, *steps):
        self.steps = list(steps)
        self.calls: list[list[str]] = []
        self.timeouts: list[float] = []

    @staticmethod
    def workdir(args: list[str]) -> Path:
        if "-D" in args:
            return Path(args[args.index("-D") + 1])
        out = args[args.index("-o") + 1]
        return Path(out).parent

    async def __call__(self, args, timeout):
        self.calls.append(list(args))
        self.timeouts.append(timeout)
        files, rc, stdout, stderr, metadata = self.steps.pop(0)
        wd = self.workdir(args)
        for name in files:
            (wd / name).write_bytes(b"x" * 10)
        if metadata is not None:
            (wd / "meta.json").write_text(json.dumps(metadata))
        return ProcResult(rc, stdout.format(wd=wd), stderr)


def step(files=(), rc=0, stdout="", stderr="", metadata=None):
    return (list(files), rc, stdout, stderr, metadata)
