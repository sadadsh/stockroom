from stockroom.scrape.crawl.governor import (
    BREAKER_THRESHOLD, MAX_RATE, MIN_RATE, HostGovernor,
)


class _Clock:
    def __init__(self, t=1000.0):
        self.t = t

    def __call__(self):
        return self.t


def test_starts_at_full_speed_no_ramp():
    clk = _Clock()
    g = HostGovernor(clock=clk)
    assert g.rate == MAX_RATE
    assert g.next_available() == clk.t  # a request is allowed immediately, no slow start


def test_bucket_drains_then_next_token_is_in_the_future():
    clk = _Clock()
    g = HostGovernor(clock=clk)
    for _ in range(int(g.tokens)):  # drain the burst bucket
        assert g.next_available() <= clk.t
        g.consume()
    assert g.next_available() > clk.t  # must now wait for a refill


def test_block_tightens_rate_and_counts():
    clk = _Clock()
    g = HostGovernor(clock=clk)
    r0 = g.rate
    g.on_block()
    assert g.rate < r0 and g.rate >= MIN_RATE
    assert g.consec_blocks == 1


def test_circuit_breaker_trips_after_threshold_blocks():
    clk = _Clock()
    g = HostGovernor(clock=clk)
    for _ in range(BREAKER_THRESHOLD):
        g.on_block()
    assert g.consec_blocks == BREAKER_THRESHOLD
    assert g.next_available() > clk.t          # host is cooling down
    assert g.cooldown_until > clk.t


def test_retry_after_wins_over_computed_cooldown():
    clk = _Clock()
    g = HostGovernor(clock=clk)
    g.on_block(retry_after=120.0)
    assert g.cooldown_until >= clk.t + 120.0   # honor the server's Retry-After


def test_success_loosens_and_clears_an_expired_breaker():
    clk = _Clock()
    g = HostGovernor(clock=clk)
    for _ in range(BREAKER_THRESHOLD):
        g.on_block()
    low = g.rate
    clk.t = g.cooldown_until + 1.0             # the cooldown has elapsed (natural recovery)
    g.on_success()
    assert g.rate > low
    assert g.consec_blocks == 0
    assert g.cooldown_until <= clk.t           # an EXPIRED breaker is cleared on recovery
    assert g.next_available() == clk.t
