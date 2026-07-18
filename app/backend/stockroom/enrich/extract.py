"""Compatibility shim (S5): the extraction cascade now lives in `stockroom.scrape.extract`
(the reviewed-clean single source, with microdata/__NUXT__ + the S3-review fixes). This
re-exports it so existing `stockroom.enrich.extract` importers resolve to that ONE source
with no duplicate to drift. The pipeline consumes it (upgraded to the scrape cascade)."""

from stockroom.scrape.extract import (  # noqa: F401
    SiteExtractor,
    extract_all,
    extract_jsonld_product,
    extract_next_data,
    extract_opengraph,
)
from stockroom.scrape.extract.structured import _looks_like_datasheet_url  # noqa: F401
