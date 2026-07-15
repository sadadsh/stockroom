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

from stockroom.enrich.passive import (
    PassiveSpec,
    clean_mpn,
    detect_passive,
    parse_passive_mpn,
    passive_package_options,
    resolve_passive_assets,
)
from stockroom.ingest.errors import IngestError
from stockroom.model.part import Datasheet, LibRef, PartRecord, Provenance, Purchase

_KIND_CATEGORY: dict[str, str] = {
    "resistor": "Resistors",
    "capacitor": "Capacitors",
    "inductor": "Inductors",
    "ferrite": "Ferrite Beads",
}

# Manual kind aliases the UI may send for the pick-your-kind fallback.
_KIND_ALIASES: dict[str, str] = {
    "r": "resistor", "c": "capacitor", "l": "inductor",
    "resistor": "resistor", "capacitor": "capacitor", "inductor": "inductor",
}


class PassiveAddError(IngestError):
    """The input is not an addable passive (bad URL host, empty input, or a manual
    package that has no KiCad stock footprint)."""


class PassiveNeedsInputError(IngestError):
    """The MPN could not be decoded, so it cannot be auto-added: the user must pick
    a kind and a package (and may add value/tolerance). This is NOT a failure - it is
    the signal to reveal the manual pickers - so it carries what IS known (the cleaned
    MPN, the manufacturer read from a URL, a best-effort kind guess) plus the package
    options, so the UI pre-fills the pickers instead of asking for everything twice."""

    def __init__(
        self,
        message: str,
        *,
        mpn: str = "",
        manufacturer: str = "",
        suggested_kind: str | None = None,
        packages: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.mpn = mpn
        self.manufacturer = manufacturer
        self.suggested_kind = suggested_kind
        self.packages = list(packages) if packages is not None else passive_package_options()


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


def _effective_spec(
    decoded: PassiveSpec | None,
    *,
    mpn: str,
    kind: str,
    package: str,
    value: str,
    tolerance: str,
    manufacturer: str,
) -> PassiveSpec:
    """The spec the record is built from: a clean decode as-is, or the decode with
    manual overrides layered on. Manual value/tolerance win when supplied; a kind or
    package correction drops decoded facts that no longer apply (a corrected package
    invalidates the power rating; a corrected kind invalidates the numeric value)."""
    if decoded is None:
        return PassiveSpec(
            kind=kind, mpn=mpn, manufacturer=manufacturer,
            value=value, tolerance=tolerance, package=package,
        )
    # A kind correction repudiates every kind-specific decoded fact (value, tolerance,
    # family, manufacturer inferred from the family match): carry them only when the
    # kind is unchanged, else a resistance would surface under a capacitor's label.
    same_kind = kind == decoded.kind
    same_package = package == decoded.package
    spec = PassiveSpec(
        kind=kind,
        mpn=mpn,
        manufacturer=manufacturer or (decoded.manufacturer if same_kind else ""),
        family=decoded.family if same_kind else "",
        value=value or (decoded.value if same_kind else ""),
        tolerance=tolerance or (decoded.tolerance if same_kind else ""),
        package=package,
    )
    if same_kind:
        if not value:  # the decoded numeric is only valid while the display value stands
            spec.value_ohms = decoded.value_ohms
            spec.value_farads = decoded.value_farads
            spec.value_henries = decoded.value_henries
        spec.voltage = decoded.voltage        # voltage/dielectric are value-independent
        spec.dielectric = decoded.dielectric
        if same_package:                       # power is per-package, not per-value
            spec.power = decoded.power
    return spec


def build_passive_record(
    source: str,
    *,
    kind: str | None = None,
    package: str | None = None,
    value: str | None = None,
    tolerance: str | None = None,
    category: str | None = None,
    manufacturer: str | None = None,
    datasheet_url: str | None = None,
    purchase_part_number: str | None = None,
    footprints_root=None,
) -> PassiveBuild:
    """Build (but do not commit) a passive PartRecord from `source` (a bare MPN or a
    Mouser product URL).

    Two paths, both file-less (symbol/footprint/3D are KiCad stock references):
      * decode - the MPN is a known R/C/L family, so value/tolerance/package come
        from the MPN with no manual input;
      * manual - the MPN cannot be decoded (or the user overrides a decode), so the
        caller supplies `kind` + `package` (+ optional `value`/`tolerance`) and the
        footprint is resolved from the picked package.

    Raises PassiveNeedsInputError when neither path can resolve a footprint (an
    undecoded MPN with no manual kind/package): that is the signal to reveal the
    manual pickers, not a hard error. Raises PassiveAddError for a genuinely bad
    input (empty, a non-Mouser URL, or a manual package with no stock footprint).
    `gaps` lists the passport fields still missing (typically just the datasheet)."""
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

    decoded = parse_passive_mpn(mpn)
    mpn = decoded.mpn if decoded is not None else clean_mpn(mpn)

    # Manual overrides (the fallback / correction path). A supplied kind or package
    # forces the manual path; value/tolerance refine whichever path builds.
    man_kind = _KIND_ALIASES.get((kind or "").strip().lower(), "")
    man_package = (package or "").strip()
    man_value = (value or "").strip()
    man_tolerance = (tolerance or "").strip()

    eff_kind = man_kind or (decoded.kind if decoded is not None else "")
    eff_package = man_package or (decoded.package if decoded is not None else "")

    resolved = (
        resolve_passive_assets(eff_kind, eff_package, footprints_root)
        if eff_kind and eff_package
        else None
    )
    if resolved is None:
        if eff_kind and eff_package:
            # Both were chosen but resolve to no stock footprint (a package/kind with
            # no KiCad stock library). The UI dropdowns only offer resolvable options,
            # so this is a genuinely bad manual input: report it plainly.
            raise PassiveAddError(
                f"no KiCad stock footprint for a {eff_kind} in the {eff_package} package"
            )
        # Not enough to resolve a footprint: ask the caller to pick. The message is
        # honest about what IS known - a Murata LQ decodes its kind but not its
        # package, so it must not claim a total decode failure.
        raise PassiveNeedsInputError(
            (f"decoded the kind ({decoded.kind}) but not the package; "
             "pick a package to add it")
            if decoded is not None
            else f"could not decode {mpn!r}; choose a kind and package to add it",
            mpn=mpn,
            manufacturer=mfr,
            suggested_kind=(eff_kind or (decoded.kind if decoded is not None else None)
                            or detect_passive(mpn=mpn, category=(category or ""))),
            packages=passive_package_options(),
        )

    # The effective spec: the decode as-is, or the decode with the manual overrides
    # layered on (a corrected package drops the now-stale decoded power/value).
    spec = _effective_spec(
        decoded, mpn=mpn, kind=eff_kind, package=eff_package,
        value=man_value, tolerance=man_tolerance, manufacturer=mfr,
    )

    if not mfr:
        mfr = spec.manufacturer
    if not purchase_url:
        purchase_url = mouser_search_url(mpn)

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
        provenance=Provenance(
            source="passive-decode" if decoded is not None else "passive-manual",
            source_url=purchase_url,
        ),
        specs=specs,
    )
    return PassiveBuild(record=record, stock_present=resolved.present, gaps=record.missing_fields())
