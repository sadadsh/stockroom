"""Registered per-site extractors, tried after the generic structured-data
layers so they fill only site-specific extras the generic cascade missed."""

from __future__ import annotations

from stockroom.enrich.sites.digikey_web import DigiKeyWebSite
from stockroom.enrich.sites.lcsc import LcscSite
from stockroom.enrich.sites.mouser_web import MouserWebSite

SITE_EXTRACTORS = (LcscSite(), MouserWebSite(), DigiKeyWebSite())
