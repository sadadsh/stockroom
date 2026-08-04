"""Per-vendor capture surfaces: capability as DATA, and nothing that operates a provider page.

Stockroom builds a safe URL, hosts the provider surface, and stages what the person downloads.
The person performs every provider-page action - navigation after the page opens, clicking,
form filling, format selection, sign-in, licence acceptance, and any security check. There is
no second, machine-driven path here to fall back to.

WHAT A VENDOR ENTRY STILL HAS TO CARRY
  * WHICH exact export choice to take. Two vendors independently offer exports this repo cannot
    ingest: Ultra Librarian lists KiCAD v5 one row above v6+, and SnapEDA's KiCad chooser offers
    "V3 & Prior" / "V4 & Later" / "V6 & Later". KiCad 5 emits `(module ...)` footprints that
    `Footprint.load` REFUSES. A wrong pick downloads a file that fails much later, far from the
    cause, so the exact human-visible choice is declared per vendor in `user_format_labels` and
    shown to the person rather than guessed at.
Provider identity that is not capture-specific - labels, domains, and search URLs - comes from
`stockroom.providers`, the one authoritative registry. What stays here is the capture-specific
route knowledge that registry deliberately does not model: DigiKey's per-author rows inside its
shared model surface, and the exact export labels above.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol
from unicodedata import normalize
from urllib.parse import parse_qs, unquote, urlparse

from stockroom.capture.identity import (
    exact_catalog_observation_error,
    exact_observation_error,
    page_identity,
    provider_url_allowed,
)
from stockroom.capture.requirements import Requirement
from stockroom.providers import provider_label as registry_label
from stockroom.providers import search_url

_ALTIUM_REQS = frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})


def formats_for(needs) -> list[str]:
    """The vendor-side export categories a set of Requirements implies.

    `model` is its OWN category, not part of `kicad`. Measured on Ultra Librarian 2026-07-27: the
    STEP model lives behind a separate "3D CAD Model" accordion, so a capture that only took the
    KiCad export came back with a symbol and a footprint and NO 3D - which is exactly what
    happened, and the run still reported success.
    """
    wanted = set(needs or ())
    out: list[str] = []
    if wanted & {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT}:
        out.append("kicad")
    if Requirement.KICAD_MODEL in wanted:
        out.append("model")
    if wanted & _ALTIUM_REQS:
        out.append("altium")
    return out


@dataclass(frozen=True)
class VendorCapability:
    """What a vendor surface offers, as data. Read by surfaces; never branched on by tool name."""

    key: str
    label: str
    tools: tuple[str, ...]
    # True when the vendor merely hosts models other libraries authored.
    aggregator: bool
    # True when downloads are gated behind a sign-in the person does by hand once.
    needs_login: bool
    # What a person has to do on that page, shown in the guided window.
    instruction: str
    # Exact visible choices a person selects in a provider-controlled page. Deliberately labels
    # and not DOM ids: Stockroom names the right export, the person takes it.
    user_format_labels: dict[str, str] = field(default_factory=dict)

    @property
    def supported_formats(self) -> frozenset[str]:
        """Formats the end-to-end capture path can accept."""

        return frozenset(self.user_format_labels)


class VendorAdapter(Protocol):
    """One vendor surface's capture DATA."""

    capability: VendorCapability

    def resolve_url(self, mpn: str) -> str:
        """The page this part lives at."""


class UltraLibrarianAdapter:
    """Ultra Librarian's own site, opened for the person to work in.

    Ultra Librarian introduced a native Altium export on 2025-10-16; its current official workflow
    yields .LibPkg, .SchLib, .PcbLib, and an integrated STEP model. PCAD v15 remains the fallback
    row when native libraries are unavailable for a part, and Stockroom converts that open ASCII
    library without launching Altium.
    """

    capability = VendorCapability(
        key="ultralibrarian",
        label=registry_label("ultralibrarian"),
        tools=("kicad", "altium"),
        aggregator=False,
        needs_login=True,
        instruction=(
            "Open the exact part, then select KiCad 6 or later, STEP, and Altium Designer "
            "(Native), using PCAD v15 only when native libraries are unavailable. Clear a "
            "provider security check if one appears."
        ),
        user_format_labels={
            "kicad": "KiCad 6 or later",
            "model": "STEP",
            "altium": "Altium Designer (Native)",
        },
    )

    def resolve_url(self, mpn: str) -> str:
        from stockroom.enrich.cad_sources import resolve_cad_sources

        for source in resolve_cad_sources(mpn):
            if source.key == "ultralibrarian":
                return source.url
        return ""


_ADAPTERS: dict[str, VendorAdapter] = {
    UltraLibrarianAdapter.capability.key: UltraLibrarianAdapter(),
}


def get_adapter(key: str) -> VendorAdapter | None:
    return _ADAPTERS.get((key or "").strip().lower())


def all_adapters() -> list[VendorAdapter]:
    return list(_ADAPTERS.values())


def capture_dir_for(root: Path, part_id: str) -> Path:
    """Where one part's downloads land. Per part, so two captures can never mingle files."""
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "-" for ch in part_id)[:80]
    return Path(root) / f"capture-{safe or 'part'}"


class SnapMagicAdapter:
    """SnapMagic (SnapEDA). Runs ALONGSIDE Ultra Librarian, never instead of it.

    Its mechanics are the opposite of Ultra Librarian's, which is why the person is told about
    them explicitly (measured 2026-07-27 against the live signed-in site):

      * ONE BUTTON PER FORMAT, so each format is its own download.
      * KiCad is a TWO-STEP chooser whose members are "V3 & prior", "V4 & later" and
        "V6 & later". Taking the wrong one downloads a library `Footprint.load` REFUSES.
      * Altium is ONE step and NATIVE - `.SchLib`/`.PcbLib`, which the attach path stores directly.
      * the 3D model is a SEPARATE download, not part of either.

    SnapEDA can serve a Cloudflare Turnstile interstitial. The person clears it once in the
    provider window and the isolated persistent profile retains that session.
    """

    capability = VendorCapability(
        key="snapmagic",
        label=registry_label("snapmagic"),
        # Both tools are native, so both can pass through Stockroom's existing attach seams.
        tools=("kicad", "altium"),
        # It hosts community and automatically generated models as well as authored ones, so its bytes are
        # lower-trust than Ultra Librarian's. Verification, not provider prose, decides whether
        # those bytes can attach.
        aggregator=False,
        needs_login=True,
        instruction=(
            "Clear the human check once if it appears, then take each format's download: "
            "KiCad V6 & Later, the STEP model, and the native Altium libraries."
        ),
        user_format_labels={
            "kicad": "KiCad V6 & Later",
            "model": "STEP model",
            "altium": "Altium native",
        },
    )

    def resolve_url(self, mpn: str) -> str:
        from stockroom.enrich.cad_sources import resolve_cad_sources

        for source in resolve_cad_sources(mpn):
            if source.key == "snapmagic":
                return source.url
        return ""


_ADAPTERS[SnapMagicAdapter.capability.key] = SnapMagicAdapter()


@dataclass(frozen=True, slots=True)
class DigiKeyProviderRoute:
    """One CAD author exposed inside DigiKey's shared model-download surface."""

    evidence_provider_key: str
    label: str
    row_ids: tuple[str, ...]
    modal_id: str
    altium_label: str
    model_label: str
    supported_formats: tuple[str, ...]
    model_only: bool = False
    # DigiKey's provider application can select a route successfully while leaving only its
    # loading skeleton visible. These are measured, route-owned element ids kept as data so the
    # person-facing surface can name what they are looking at.
    skeleton_ids: tuple[str, ...] = ()
    # The `?tab=` value that lands DIRECTLY on this author inside DigiKey's per-part models page
    # (`/en/models/<id>?tab=<models_tab>`), removing a search, a scroll and a tab click once the
    # part's opaque models id has been learned from the person's own navigation.
    #
    # DATA, deliberately, and empty unless someone has actually seen DigiKey serve it. Deriving it
    # from `evidence_provider_key` would spell `traceparts`, `manufacturer` and `cadenas` into
    # existence, and a wrong tab is worse than no tab: it promises a surface and delivers whatever
    # DigiKey does with an unknown one.
    models_tab: str = ""


_DIGIKEY_SNAPMAGIC_ROUTE = DigiKeyProviderRoute(
    evidence_provider_key="digikey-snapmagic",
    label=registry_label("snapmagic"),
    row_ids=("snap-media-active", "snapmagic-media-active"),
    modal_id="snapeda-export-options",
    altium_label="altium designer",
    model_label="step",
    supported_formats=("kicad", "model", "altium"),
    skeleton_ids=("snap-model-skeleton",),
    # Owner-confirmed 2026-07-31, and corroborated by DigiKey's own publicly indexed models URLs,
    # e.g. https://www.digikey.com/en/models/303553?tab=snapmagic.
    models_tab="snapmagic",
)
_DIGIKEY_ULTRALIBRARIAN_ROUTE = DigiKeyProviderRoute(
    evidence_provider_key="digikey-ultralibrarian",
    label=registry_label("ultralibrarian"),
    row_ids=("ultra-media-active",),
    modal_id="ultralib-export-options",
    # P-CAD v15 carries the symbol and footprint in an open ASCII library that Stockroom converts
    # to native SchLib/PcbLib without launching Altium. The script-based row needs Altium itself.
    altium_label="pcad v15",
    model_label="step",
    supported_formats=("kicad", "model", "altium"),
    skeleton_ids=("ultra-model-skeleton",),
    # DigiKey's own publicly indexed models URLs carry it verbatim, e.g.
    # https://www.digikey.com/en/models/3906419?tab=ultralibrarian (and the same shape on the
    # regional storefronts, digikey.ca/en/models/7313085?tab=ultralibrarian).
    models_tab="ultralibrarian",
)
_DIGIKEY_TRACEPARTS_ROUTE = DigiKeyProviderRoute(
    evidence_provider_key="digikey-traceparts",
    label=registry_label("traceparts"),
    row_ids=("traceparts-media-active",),
    modal_id="traceparts-export-options",
    altium_label="",
    model_label="step ap214",
    supported_formats=("model",),
    model_only=True,
)
_DIGIKEY_MANUFACTURER_ROUTE = DigiKeyProviderRoute(
    evidence_provider_key="digikey-manufacturer",
    label="Manufacturer Provided",
    row_ids=("mfr-media-active",),
    modal_id="mfr-export-options",
    altium_label="",
    model_label="",
    supported_formats=("model",),
    model_only=True,
)
_DIGIKEY_CADENAS_ROUTE = DigiKeyProviderRoute(
    evidence_provider_key="digikey-cadenas",
    label=registry_label("cadenas"),
    row_ids=("cadenas-media-active",),
    modal_id="cadenas-export-options",
    altium_label="",
    # No positive live format/download contract has been measured for this polymorphic row.
    model_label="",
    supported_formats=("model",),
    model_only=True,
)


class DigiKeyUltraLibrarianAdapter:
    """DigiKey's exact product/model pages with independently attributed CAD-author routes.

    DigiKey is the browser surface, not the CAD author. Its site controls are person-driven;
    Stockroom opens the exact route in its embedded provider window and intercepts, validates,
    retains, and activates the files the person downloads.
    """

    evidence_provider_key = "digikey-ultralibrarian"
    capability = VendorCapability(
        key="digikey",
        label="DigiKey CAD Models",
        tools=("kicad", "altium"),
        aggregator=True,
        needs_login=True,
        instruction=(
            "Stockroom opens the exact DigiKey models page and shows the required author routes. "
            "Start each offered download there; Stockroom captures every delivered variant, "
            "retains incomplete TraceParts, manufacturer-provided, and CADENAS model sets as "
            "supplementary evidence, converts the open P-CAD Altium library without launching an "
            "editor, and activates a strictly compatible cross-EDA set."
        ),
        user_format_labels={
            "kicad": "KiCad v6 or later",
            "model": "STEP",
            "altium": "Altium Designer",
        },
    )

    def capture_routes(self) -> tuple[object, ...]:
        """Collect the preferred coherent author first, then supplementary alternatives."""

        return (
            self,
            DigiKeySnapMagicRouteAdapter(self),
            DigiKeyTracePartsRouteAdapter(self),
            DigiKeyManufacturerProvidedRouteAdapter(self),
            DigiKeyCadenasRouteAdapter(self),
        )

    def resolve_url(self, mpn: str) -> str:
        return search_url("digikey", mpn)

    @property
    def models_tab(self) -> str:
        """This surface opens on its preferred coherent author, so it carries that route's tab."""

        return _DIGIKEY_ULTRALIBRARIAN_ROUTE.models_tab


class _DigiKeyProviderRouteAdapter:
    """One independently attributed author route inside DigiKey's shared session."""

    supplementary_only = False
    _route: DigiKeyProviderRoute

    def __init__(self, surface: DigiKeyUltraLibrarianAdapter) -> None:
        self._surface = surface
        self.evidence_provider_key = self._route.evidence_provider_key

    def resolve_url(self, mpn: str) -> str:
        return self._surface.resolve_url(mpn)

    @property
    def models_tab(self) -> str:
        """This route's measured DigiKey models tab, or "" when none is evidenced."""

        return self._route.models_tab


class DigiKeySnapMagicRouteAdapter(_DigiKeyProviderRouteAdapter):
    """SnapMagic's route, including DigiKey's current external-only presentation."""

    _route = _DIGIKEY_SNAPMAGIC_ROUTE
    capability = VendorCapability(
        key="digikey",
        label="DigiKey · SnapMagic",
        tools=("kicad", "altium"),
        aggregator=True,
        needs_login=True,
        instruction=(
            "Open the SnapMagic row and take the KiCad 6+, STEP, and native Altium downloads. "
            "DigiKey may present this author as an external SnapEDA link; the same task-bound "
            "window follows it and Stockroom still captures every delivered file."
        ),
        user_format_labels={
            "kicad": "KiCad v6 or later",
            "model": "STEP",
            "altium": "Altium Designer",
        },
    )


class DigiKeyTracePartsRouteAdapter(_DigiKeyProviderRouteAdapter):
    """TraceParts' measured STEP export retained as non-activatable evidence."""

    _route = _DIGIKEY_TRACEPARTS_ROUTE
    supplementary_only = True
    capability = VendorCapability(
        key="digikey",
        label="DigiKey · TraceParts",
        tools=("kicad",),
        aggregator=True,
        needs_login=True,
        instruction=(
            "Start the exact TraceParts STEP download. Stockroom retains it as supplementary "
            "evidence without treating it as a complete KiCad library variant."
        ),
        user_format_labels={"model": "STEP AP214"},
    )


class DigiKeyManufacturerProvidedRouteAdapter(_DigiKeyProviderRouteAdapter):
    """Direct-manufacturer STEP originals, retained without forming an active CAD set."""

    _route = _DIGIKEY_MANUFACTURER_ROUTE
    supplementary_only = True
    capability = VendorCapability(
        key="digikey",
        label="DigiKey · Manufacturer Provided",
        tools=("kicad",),
        aggregator=True,
        needs_login=True,
        instruction=(
            "Use the Manufacturer Provided row when it appears. Start every offered STEP "
            "original, including a visible external manufacturer link; Stockroom retains the "
            "delivered exact files as supplementary evidence without activating them."
        ),
        user_format_labels={"model": "3D Model"},
    )


class DigiKeyCadenasRouteAdapter(_DigiKeyProviderRouteAdapter):
    """CADENAS' exact 3D route, retained without forming an active CAD set."""

    _route = _DIGIKEY_CADENAS_ROUTE
    supplementary_only = True
    capability = VendorCapability(
        key="digikey",
        label="DigiKey · CADENAS",
        tools=("kicad",),
        aggregator=True,
        needs_login=True,
        instruction=(
            "When DigiKey offers CADENAS for the exact part, work its row directly. Stockroom "
            "retains whatever it delivers as supplementary evidence."
        ),
        user_format_labels={"model": "3D Model"},
    )


class SamacSysAssistedAdapter:
    """Person-driven SamacSys acquisition with automatic Stockroom capture and validation.

    The Supplyframe/Component Search Engine terms prohibit automated agents and scripts, and the
    rest of this module now works the same way for every provider: Stockroom navigates and
    overlays the exact task, the person operates the page, and the shared broker, ingest,
    evidence, native readback, and atomic attach path takes over once a download starts.
    """

    capability = VendorCapability(
        key="samacsys",
        label=registry_label("samacsys"),
        tools=("kicad", "altium"),
        aggregator=False,
        needs_login=True,
        instruction=(
            "Open the exact result and start its CAD download. Stockroom captures every delivered "
            "file, rejects pointer-only .epw files, validates native contents, and attaches only "
            "a complete exact component."
        ),
        user_format_labels={
            "kicad": "KiCad symbol and footprint",
            "model": "STEP model",
            "altium": "Altium Designer libraries",
        },
    )

    def resolve_url(self, mpn: str) -> str:
        return search_url("samacsys", mpn)


_ADAPTERS[DigiKeyUltraLibrarianAdapter.capability.key] = DigiKeyUltraLibrarianAdapter()
_ADAPTERS[SamacSysAssistedAdapter.capability.key] = SamacSysAssistedAdapter()


def _requested_mpn(url: str, names: tuple[str, ...]) -> str:
    """Read the exact requested MPN back from a vendor search URL."""
    try:
        query = parse_qs(urlparse(url or "").query, keep_blank_values=False)
    except Exception:  # noqa: BLE001 - malformed vendor navigation fails closed below
        return ""
    for name in names:
        values = query.get(name) or ()
        if values and values[0].strip():
            return values[0].strip()
    return ""


def _mpn_key(value: str) -> str:
    """Identity comparison for navigation: Unicode/case tolerant, punctuation preserving."""
    return normalize("NFC", (value or "").strip()).casefold()


def _href_demonstrates_mpn(href: str, requested_mpn: str) -> bool:
    """True only when one complete detail-path component equals the requested MPN.

    Deliberately no substring matching: `ABC` must not select `ABC-1`, and punctuation such as
    `+`, `/`, or `#` remains identity-bearing. Query values are not identity evidence: live
    SnapMagic sponsored results echo the requested MPN in a tracking ``t=`` parameter while their
    detail path names a completely different part.
    """
    expected = _mpn_key(requested_mpn)
    if not expected or not href:
        return False
    try:
        parsed = urlparse(href)
        path_segments = [unquote(segment) for segment in parsed.path.split("/") if segment]
    except Exception:  # noqa: BLE001 - malformed result URLs are not identity evidence
        return False
    return any(_mpn_key(value) == expected for value in path_segments)


def _canonical_detail_identity(
    href: str,
    vendor_key: str = "",
) -> tuple[str, str, tuple[str, ...]] | None:
    """The stable destination behind one result link.

    Provider search pages repeat one part through image/title/action links and add presentation
    state such as Ultra Librarian's ``open=Pricing``. Those are one destination, not ambiguity.
    A provider's stable ``uid`` remains identity-bearing so genuinely distinct catalogue entries
    still fail closed.
    """
    try:
        parsed = urlparse(href)
        observed = page_identity(vendor_key, href, allow_relative=True)
        if observed is not None:
            manufacturer = "".join(
                character
                for character in normalize("NFKC", observed.manufacturer).casefold()
                if character.isalnum()
            )
            mpn = _mpn_key(observed.mpn)
            if manufacturer and mpn:
                uid = tuple(
                    _mpn_key(value)
                    for value in parse_qs(parsed.query, keep_blank_values=False).get("uid", ())
                    if value.strip()
                )
                return (manufacturer, mpn, uid)
        path = _mpn_key(unquote(parsed.path)).rstrip("/")
        if not path:
            return None
        uid = tuple(
            _mpn_key(value)
            for value in parse_qs(parsed.query, keep_blank_values=False).get("uid", ())
            if value.strip()
        )
        return (parsed.netloc.casefold(), path, uid)
    except Exception:  # noqa: BLE001 - malformed destinations cannot establish one identity
        return None


def _provider_url_allowed(
    vendor_key: str,
    url: str,
    *,
    allow_relative: bool = False,
) -> bool:
    """Only official provider hosts may establish or receive part identity."""

    return provider_url_allowed(vendor_key, url, allow_relative=allow_relative)


def _detail_identity_issue(
    vendor_key: str,
    url: str,
    expected_manufacturer: str,
    expected_mpn: str,
    *,
    catalog_identity_authorized: bool = False,
) -> str:
    """Return a fail-closed provider-detail identity error when an expectation was supplied."""

    if not expected_mpn:
        return ""
    if not _provider_url_allowed(vendor_key, url):
        return (
            f"{vendor_key} left its official provider host; refusing to bind a lookalike "
            "detail path."
        )
    observed = page_identity(vendor_key, url)
    if observed is None:
        return (
            f"{vendor_key} did not expose the exact manufacturer and MPN in its detail URL; "
            "refusing to bind this page."
        )
    expected = SimpleNamespace(manufacturer=expected_manufacturer, mpn=expected_mpn)
    error = (
        exact_catalog_observation_error(expected, observed)
        if catalog_identity_authorized
        else exact_observation_error(expected, observed)
    )
    return f"{vendor_key} {error}." if error else ""
