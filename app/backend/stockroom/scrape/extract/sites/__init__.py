"""Per-domain product adapters (scrape layer), tried after the generic structured
cascade to fill only site-specific extras. Copied from the proven enrich/sites/* that
produced the 88-part corpus; behavior-identical. The enrich duplicates are retired in
S5 (this milestone's one logged transient)."""

from __future__ import annotations

from stockroom.scrape.extract.sites.digikey_web import DigiKeyWebSite
from stockroom.scrape.extract.sites.lcsc import LcscSite
from stockroom.scrape.extract.sites.mouser_web import MouserWebSite

SITE_ADAPTERS = (LcscSite(), MouserWebSite(), DigiKeyWebSite())
