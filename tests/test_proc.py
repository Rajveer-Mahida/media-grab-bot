import sys
import time

import pytest

from bot.engine.errors import Failed
from bot.engine.proc import run


async def test_run_captures_output():
    r = await run([sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"], 30)
    assert (r.returncode, r.stdout.strip(), r.stderr.strip()) == (3, "out", "err")


async def test_run_timeout_kills_and_raises():
    t0 = time.monotonic()
    with pytest.raises(Failed, match="timed out after 1s"):
        await run([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1)
    assert time.monotonic() - t0 < 5


async def test_run_timeout_kills_child_processes(tmp_path):
    marker = tmp_path / "child-alive"
    child = f"import time; time.sleep(3); open({str(marker)!r}, 'w')"
    code = f"import subprocess, sys, time; subprocess.Popen([sys.executable, '-c', {child!r}]); time.sleep(30)"
    with pytest.raises(Failed):
        await run([sys.executable, "-c", code], timeout=1)
    time.sleep(3.5)
    assert not marker.exists()


async def test_run_missing_binary_is_failed():
    with pytest.raises(Failed):
        await run(["/nonexistent/binary"], 5)
