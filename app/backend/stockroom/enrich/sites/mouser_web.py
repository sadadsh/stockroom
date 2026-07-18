"""Compatibility shim (S5) -> stockroom.scrape.extract.sites.mouser_web (single source)."""

from stockroom.scrape.extract.sites.mouser_web import (  # noqa: F401
    MouserWebSite,
    _extract_price_breaks,
    _extract_stock,
    _extract_tariff_rate,
)
