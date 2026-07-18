"""Compatibility shim (S5) -> stockroom.scrape.extract.sites.lcsc (single source)."""

from stockroom.scrape.extract.sites.lcsc import (  # noqa: F401
    LcscProduct,
    LcscSite,
    parse_lcsc_product,
)
