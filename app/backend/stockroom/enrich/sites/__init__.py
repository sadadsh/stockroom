"""Compatibility shim (S5): the per-site product adapters now live in
`stockroom.scrape.extract.sites` (the single reviewed-clean source). Re-exported here so
existing `stockroom.enrich.sites` importers keep resolving with no duplicate to drift."""

from stockroom.scrape.extract.sites import SITE_ADAPTERS as SITE_EXTRACTORS  # noqa: F401
from stockroom.scrape.extract.sites.digikey_web import DigiKeyWebSite  # noqa: F401
from stockroom.scrape.extract.sites.lcsc import LcscSite  # noqa: F401
from stockroom.scrape.extract.sites.mouser_web import MouserWebSite  # noqa: F401
