from stockroom.enrich.ratelimit import SlidingWindowLimiter


class _FakeClock:
    def __init__(self):
        self.t = 0.0
        self.slept = []

    def now(self):
        return self.t

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.t += seconds  # advancing time is what a real sleep does


def test_bursts_up_to_the_limit_without_sleeping():
    clk = _FakeClock()
    lim = SlidingWindowLimiter(limit=3, window=60.0, clock=clk.now, sleeper=clk.sleep)
    for _ in range(3):
        lim.acquire()
    assert clk.slept == []  # first `limit` calls burst freely


def test_the_next_call_sleeps_until_the_oldest_leaves_the_window():
    clk = _FakeClock()
    lim = SlidingWindowLimiter(limit=2, window=60.0, clock=clk.now, sleeper=clk.sleep)
    lim.acquire()          # t=0
    clk.t = 10.0
    lim.acquire()          # t=10
    clk.t = 20.0
    lim.acquire()          # window full (2 in [0,60]); must wait for t=0 to expire
    # oldest was at t=0, window 60, so sleep ~ 60 - (20 - 0) = 40 (+ the 0.1 nudge)
    assert clk.slept
    assert abs(clk.slept[0] - 40.1) < 0.001


def test_pops_the_oldest_so_the_window_slides():
    clk = _FakeClock()
    lim = SlidingWindowLimiter(limit=1, window=10.0, clock=clk.now, sleeper=clk.sleep)
    lim.acquire()          # t=0
    clk.t = 5.0
    lim.acquire()          # full; sleep 10 - 5 + 0.1 = 5.1, then record at t=10.1
    clk.t = 21.0
    lim.acquire()          # the t=10.1 call is > 10s old at t=21, so no sleep
    assert len(clk.slept) == 1
