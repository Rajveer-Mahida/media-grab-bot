from bot.engine.pacing import Pacer


class FakeClock:
    def __init__(self, t=100.0):
        self.t = t
        self.sleeps = []

    def __call__(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def make(clock, jitter_value=2.0):
    return Pacer(5.0, 3.0, clock=clock, sleep=clock.sleep, rand=lambda a, b: jitter_value)


async def test_pacer_first_wait_immediate():
    c = FakeClock()
    await make(c).wait()
    assert c.sleeps == []


async def test_pacer_enforces_interval_plus_jitter():
    c = FakeClock()
    p = make(c)
    await p.wait()
    c.t += 1.0
    await p.wait()
    assert c.sleeps == [6.0]


async def test_pacer_no_sleep_when_interval_elapsed():
    c = FakeClock()
    p = make(c)
    await p.wait()
    c.t += 20
    await p.wait()
    assert c.sleeps == []


def test_pacer_pause_and_remaining():
    c = FakeClock(100.0)
    p = make(c)
    assert p.paused_for() == 0
    p.pause(600)
    assert p.paused_for() == 600
    c.t = 400.0
    assert p.paused_for() == 300
    c.t = 800.0
    assert p.paused_for() == 0
