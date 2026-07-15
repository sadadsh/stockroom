"""Hermetic network guard for the enrichment unit suite.

Adding LcscSource (registry source #1) means every pipeline enrich now calls the
free jlcsearch endpoint through the default HttpFetcher. Without a guard the whole
enrich suite would reach tscircuit.com / lcsc.com live on every run, which is slow,
flaky, and dishonest as a "unit" test. This patches the ONE network boundary a
default fetcher uses (_make_session, the curl_cffi session builder) so a fetcher
with no injected session can never open a socket; a raised EnrichError makes
LcscSource / DatasheetSource miss cleanly and the registry walk continues.

Tests that inject their own session or stub fetcher are unaffected (they never call
_make_session). The opt-in live suite (marked live_enrich, deselected by default)
is exempt so it can still catch real scraper rot.
"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_real_network(request, monkeypatch):
    if request.node.get_closest_marker("live_enrich"):
        return

    def _blocked(_impersonate):
        from stockroom.enrich.errors import EnrichError

        raise EnrichError("real network is disabled in the enrich unit suite")

    monkeypatch.setattr("stockroom.enrich.fetch._make_session", _blocked)
