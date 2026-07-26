from stockroom.scrape.stealth.fingerprint import (
    Fingerprint,
    FingerprintRotator,
    default_fingerprints,
)


def test_defaults_are_real_curl_cffi_targets():
    fps = default_fingerprints()
    assert len(fps) >= 3
    targets = {fp.impersonate for fp in fps}
    # every default must be a target curl_cffi 0.15 actually supports
    import typing

    from curl_cffi.requests.session import BrowserTypeLiteral

    supported = set(typing.get_args(BrowserTypeLiteral))
    assert targets <= supported
    # chrome fingerprints carry a matching sec-ch-ua header
    chrome = next(fp for fp in fps if fp.impersonate.startswith("chrome"))
    assert "sec-ch-ua" in chrome.headers


def test_rotate_is_round_robin():
    a = Fingerprint("chrome146", {"h": "1"})
    b = Fingerprint("edge101", {"h": "2"})
    r = FingerprintRotator([a, b])
    assert r.current() is a
    assert r.rotate() is b
    assert r.rotate() is a  # wraps
    assert r.current() is a


def test_empty_fingerprints_is_rejected():
    import pytest

    with pytest.raises(ValueError):
        FingerprintRotator([])
