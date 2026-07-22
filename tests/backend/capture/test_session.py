from pathlib import Path

from stockroom.capture.requirements import Requirement
from stockroom.capture.session import CaptureSession, new_token

R = Requirement


def _session(needs, *, now=1000.0, ttl=300.0):
    return CaptureSession.start("part-1", needs, now=now, token="tok", ttl=ttl)


def test_new_token_is_unique_hex():
    a, b = new_token(), new_token()
    assert a != b and len(a) >= 8


def test_start_sets_deadline():
    s = _session([R.KICAD_SYMBOL], now=1000.0, ttl=180.0)
    assert s.deadline == 1180.0
    assert not s.is_expired(1179.0)
    assert s.is_expired(1180.0)


def test_record_returns_newly_satisfied_and_dedups():
    s = _session([R.KICAD_SYMBOL, R.KICAD_FOOTPRINT])
    newly = s.record([R.KICAD_SYMBOL], Path("/tmp/a.kicad_sym"))
    assert newly == [R.KICAD_SYMBOL]
    assert s.record([R.KICAD_SYMBOL], Path("/tmp/a.kicad_sym")) == []


def test_record_ignores_requirements_not_needed():
    s = _session([R.KICAD_SYMBOL])
    assert s.record([R.ALTIUM_SYMBOL], Path("/tmp/x.SchLib")) == []
    assert R.ALTIUM_SYMBOL not in s.received


def test_completeness_and_remaining():
    s = _session([R.KICAD_SYMBOL, R.ALTIUM_SYMBOL])
    s.record([R.KICAD_SYMBOL], Path("/a"))
    assert not s.is_complete()
    assert s.remaining() == frozenset({R.ALTIUM_SYMBOL})
    assert s.kicad_complete() and not s.altium_complete()
    s.record([R.ALTIUM_SYMBOL], Path("/b"))
    assert s.is_complete() and s.altium_complete()


def test_tool_complete_true_when_no_needs_in_that_tool():
    s = _session([R.KICAD_SYMBOL])
    # No Altium requirements needed -> altium is trivially complete.
    assert s.altium_complete()


def test_stop_sets_flag():
    s = _session([R.KICAD_SYMBOL])
    assert s.stop_flag["stop"] is False
    s.stop()
    assert s.stop_flag["stop"] is True
