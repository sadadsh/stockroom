"""Build a file-less passive PartRecord from just an MPN or a distributor URL.

The owner's "drop the MPN, no files" path for passives: a resistor/capacitor/
inductor decodes offline (value/tolerance/package/power) and its symbol/footprint/3D
are KiCad STOCK references (already installed), so nothing is downloaded or dropped.
The only online-sourced fields are the datasheet URL and the purchase link; the buy
link is Mouser (Mouser hard-blocks scraping, so its identity is read from the URL
path, never fetched, and a bare MPN gets a constructed Mouser search link).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import quote, unquote, urlsplit

from stockroom.enrich.passive import detect_passive, parse_passive_mpn, resolve_passive_assets
from stockroom.ingest.errors import IngestError
from stockroom.model.part import Datasheet, LibRef, PartRecord, Provenance, Purchase

_KIND_CATEGORY: dict[str, str] = {
    "resistor": "Resistors",
    "capacitor": "Capacitors",
    "inductor": "Inductors",
    "ferrite": "Ferrite Beads",
}


class PassiveAddError(IngestError):
    """The input is not an auto-addable passive (undecodable MPN, or no stock asset)."""


@dataclass
class PassiveBuild:
    record: PartRecord
    stock_present: bool
    gaps: list[str] = field(default_factory=list)


def mouser_search_url(mpn: str) -> str:
    """A deterministic Mouser buy-link for a bare MPN (no API, no scraping): the
    keyword search that lands on the part's Mouser page."""
    return f"https://www.mouser.com/c/?q={quote(mpn)}"


def parse_mouser_product_url(url: str) -> tuple[str, str] | None:
    """Read (manufacturer, mpn) from a Mouser product URL path
    (/ProductDetail/<Manufacturer>/<MPN>). The path is the reliable, no-network source
    of identity (Mouser blocks scraping). Returns None if the URL is not a Mouser
    product-detail link."""
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    if not (host == "mouser.com" or host.endswith(".mouser.com")):
        return None
    segments = [s for s in parts.path.split("/") if s]
    if "ProductDetail" not in segments:
        return None
    tail = segments[segments.index("ProductDetail") + 1:]
    if len(tail) >= 2:
        return unquote(tail[0]), unquote(tail[1])
    if len(tail) == 1:
        return "", unquote(tail[0])
    return None


def _split_lib_id(lib_id: str) -> tuple[str, str]:
    lib, _, name = lib_id.partition(":")
    return lib, name


def _passive_display_name(spec) -> str:
    """A human name that says what the passive IS, e.g. "1.1 kOhm 1% 0603 Resistor",
    so the library list is readable instead of a wall of MPNs (the MPN stays in the
    mpn field for search + the id)."""
    kind = {"resistor": "Resistor", "capacitor": "Capacitor",
            "inductor": "Inductor"}.get(spec.kind, spec.kind.title())
    parts = [p for p in (spec.value, spec.tolerance, spec.package) if p]
    parts.append(kind)
    return " ".join(parts)


def build_passive_record(
    source: str,
    *,
    category: str | None = None,
    manufacturer: str | None = None,
    datasheet_url: str | None = None,
    purchase_part_number: str | None = None,
    footprints_root=None,
) -> PassiveBuild:
    """Build (but do not commit) a passive PartRecord from `source` (a bare MPN or a
    Mouser product URL). Raises PassiveAddError if the MPN is not a decodable passive
    or no KiCad stock footprint resolves. `gaps` lists the passport fields still
    missing (typically just the datasheet when no URL is supplied)."""
    source = (source or "").strip()
    if not source:
        raise PassiveAddError("no MPN or URL provided")

    purchase_url = ""
    mpn = source
    mfr = (manufacturer or "").strip()
    if source.lower().startswith("http"):
        parsed = parse_mouser_product_url(source)
        if parsed is None:
            raise PassiveAddError(
                "only a bare MPN or a Mouser product URL "
                "(/ProductDetail/<Manufacturer>/<MPN>) is supported"
            )
        url_mfr, mpn = parsed
        if not mfr:
            mfr = url_mfr
        purchase_url = source  # the pasted link is the buy-link verbatim

    spec = parse_passive_mpn(mpn)
    if spec is None:
        raise PassiveAddError(
            f"could not decode a passive from {mpn!r}; only R/C/L MPNs are auto-added "
            "without files"
        )
    mpn = spec.mpn  # the cleaned, distributor-prefix-stripped MPN
    if not mfr:
        mfr = spec.manufacturer
    if not purchase_url:
        purchase_url = mouser_search_url(mpn)

    resolved = resolve_passive_assets(spec.kind, spec.package, footprints_root)
    if resolved is None:
        raise PassiveAddError(
            f"could not resolve a KiCad stock footprint for {mpn!r} "
            f"(package {spec.package or 'unknown'!r})"
        )

    sym_lib, sym_name = _split_lib_id(resolved.symbol)
    fp_lib, fp_name = _split_lib_id(resolved.footprint)
    cat = (category or "").strip() or _KIND_CATEGORY.get(spec.kind, "Other")

    specs = dict(spec.to_specs())
    specs.setdefault("Symbol", resolved.symbol)
    specs.setdefault("Footprint", resolved.footprint)
    specs.setdefault("3D Model", resolved.model_3d)

    datasheet_url = (datasheet_url or "").strip()
    datasheet = Datasheet(source_url=datasheet_url) if datasheet_url else None

    record = PartRecord(
        id="",
        display_name=_passive_display_name(spec) or mpn,
        category=cat,
        description=spec.summary(),
        mpn=mpn,
        manufacturer=mfr,
        passive=True,
        symbol=LibRef(lib=sym_lib, name=sym_name),
        footprint=LibRef(lib=fp_lib, name=fp_name),
        model=None,
        datasheet=datasheet,
        purchase=[Purchase(
            vendor="Mouser",
            url=purchase_url,
            part_number=(purchase_part_number or "").strip(),
        )],
        provenance=Provenance(source="passive-decode", source_url=purchase_url),
        specs=specs,
    )
    # detect_passive is honored for the override case (a category the user forced);
    # the record is passive regardless since it decoded as one.
    _ = detect_passive(mpn=mpn, category=cat)
    return PassiveBuild(record=record, stock_present=resolved.present, gaps=record.missing_fields())
