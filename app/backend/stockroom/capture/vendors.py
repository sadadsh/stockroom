"""Per-vendor capture adapters: capability as DATA, behaviour as CODE.

WHY NOT A PURE DATA SCHEMA, which is what the guided-capture spec originally aimed at
The spec's risk R1 says drivers should be "data-driven + easy to update". Measurement on
2026-07-27 killed that goal, and the evidence is three DIFFERENT mechanics across three surfaces
for two vendors:

  * Ultra Librarian's own site  - CHECKBOXES in one shared group; both formats in ONE download.
  * Ultra Librarian inside DigiKey's models page - RADIO groups; one download per format.
  * SnapEDA - one BUTTON per format (one download each), and KiCad is a TWO-STEP version chooser.

No declarative schema expresses those without becoming a programming language. The established
answer agrees: yt-dlp handles thousands of sites with per-site extractor CLASSES rather than
config, because sites need real logic (signatures, headers, protocol quirks).

So the split here is deliberate:
  * CAPABILITY is data on the adapter - what it emits, whether formats are exclusive, whether it
    needs a login, and (critically) WHICH VERSION of each tool's export to take.
  * BEHAVIOUR is a method - `drive()` - written per vendor against measured selectors and locked
    by a driver-execution test over a captured fixture of the real page.

THE VERSION PIN IS NOT AN OPTIONAL FIELD
Two vendors independently offer exports this repo cannot ingest: Ultra Librarian lists KiCAD v5
one row above v6+, and SnapEDA's KiCad chooser offers "V3 & Prior" / "V4 & Later" / "V6 & Later".
KiCad 5 emits `(module ...)` footprints that `Footprint.load` REFUSES. A wrong pick downloads a
file that fails much later, far from the cause, so the version is declared explicitly per vendor
and never defaulted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from stockroom.capture.requirements import Requirement

_KICAD_REQS = frozenset(
    {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT, Requirement.KICAD_MODEL}
)
_ALTIUM_REQS = frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})


def formats_for(needs) -> list[str]:
    """The vendor-side formats a set of Requirements implies, KiCad first."""
    wanted = set(needs or ())
    out: list[str] = []
    if wanted & _KICAD_REQS:
        out.append("kicad")
    if wanted & _ALTIUM_REQS:
        out.append("altium")
    return out


@dataclass(frozen=True)
class VendorCapability:
    """What a vendor can do, as data. Read by surfaces; never branched on by tool name."""

    key: str
    label: str
    tools: tuple[str, ...]
    # False when one export can carry several formats at once (Ultra Librarian's checkboxes), True
    # when each format is its own download and the engine must sequence them (SnapEDA's buttons).
    formats_exclusive: bool
    # True when the vendor merely hosts models other libraries authored.
    aggregator: bool
    # True when downloads are gated behind a sign-in the person does by hand once.
    needs_login: bool
    # What a human has to do on that page, shown in the guided window.
    instruction: str
    # The EXACT export to take per format. See the module docstring: never defaulted.
    version_pins: dict[str, str] = field(default_factory=dict)


class VendorAdapter(Protocol):
    """One vendor's capture behaviour."""

    capability: VendorCapability

    def resolve_url(self, mpn: str) -> str:
        """The page this part lives at."""

    def drive(self, page, formats: list[str]) -> "DriveReport":
        """Select `formats` and trigger the download(s). Returns what it actually achieved."""


@dataclass
class DriveReport:
    """What a drive actually accomplished, named honestly.

    `selected` are the formats whose controls were verified selected; `missed` are the ones the
    page could not offer. The engine reports from THIS, never from "we clicked something", because
    a success message must come from the code that observed the success.
    """

    selected: list[str] = field(default_factory=list)
    missed: list[str] = field(default_factory=list)
    submitted: bool = False
    message: str = ""

    @property
    def ok(self) -> bool:
        return self.submitted and bool(self.selected)


class UltraLibrarianAdapter:
    """Ultra Librarian, measured 2026-07-27 against the live signed-in page.

    Fixture: `tests/backend/host/fixtures/ul-export-panel.html`.
    The whole point of this vendor: both formats ride ONE download, so `formats_exclusive=False`
    and the engine must not sequence it.
    """

    capability = VendorCapability(
        key="ultralibrarian",
        label="Ultra Librarian",
        tools=("kicad", "altium"),
        formats_exclusive=False,
        aggregator=False,
        needs_login=True,
        instruction="Pick the part, then Download Now. Both formats come in one file.",
        # measured element ids on the export panel
        version_pins={"kicad": "KiCADv6", "altium": "AltiumDesigner"},
    )

    # The accordion each format hides behind, by its visible text.
    _ACCORDION = {"kicad": "KiCAD", "altium": "Altium"}

    def resolve_url(self, mpn: str) -> str:
        from stockroom.enrich.cad_sources import resolve_cad_sources

        for source in resolve_cad_sources(mpn):
            if source.key == "ultralibrarian":
                return source.url
        return ""

    def drive(self, page, formats: list[str]) -> DriveReport:
        report = DriveReport()
        for fmt in formats:
            box_id = self.capability.version_pins.get(fmt)
            if not box_id:
                report.missed.append(fmt)
                continue
            accordion = self._ACCORDION.get(fmt)
            if accordion:
                _click_accordion(page, accordion)
            if _check_box(page, f"#{box_id}"):
                report.selected.append(fmt)
            else:
                report.missed.append(fmt)

        _accept_consents(page)

        if not report.selected:
            report.message = (
                "Could not select "
                + " or ".join(report.missed)
                + " on this page; choose the format and click Download Now."
            )
            return report

        submit = page.locator("#submit-export").first
        if submit.count() == 0:
            report.message = (
                "Selected " + " and ".join(report.selected) + ", but the Download button is "
                "not on this page."
            )
            return report
        submit.click()
        report.submitted = True
        report.message = (
            "Downloading " + " and ".join(report.selected) + " together."
            if not report.missed
            else "Downloading "
            + " and ".join(report.selected)
            + ", but could not select "
            + " and ".join(report.missed)
            + "."
        )
        return report


def _click_accordion(page, label: str) -> bool:
    """Expand the tool's section. Matched on EXACT text so "Altium" never hits the footer's
    "Altium" marketing link, which is a real element on this page."""
    toggles = page.locator("a.accordion-toggle")
    for index in range(toggles.count()):
        node = toggles.nth(index)
        if (node.inner_text() or "").strip() == label:
            node.click()
            return True
    return False


def _check_box(page, selector: str) -> bool:
    """Tick a checkbox and READ ITS STATE BACK.

    Never trusts the click: a handler can refuse it, a collapsed panel can swallow it. The same
    verify-after-click lesson the DigiKey driver learned the expensive way.
    """
    box = page.locator(selector).first
    if box.count() == 0:
        return False
    if not box.is_checked():
        box.check(force=True)
    return box.is_checked()


def _accept_consents(page) -> int:
    """Tick every required consent. Owner's decision 2026-07-27, asked with options and answered:
    always auto-tick. Ultra Librarian will not export without it and it is per-manufacturer, so a
    90-part sitting would otherwise cost 90 manual ticks."""
    consents = page.locator("input[type=checkbox][id^=consent-]")
    accepted = 0
    for index in range(consents.count()):
        node = consents.nth(index)
        if not node.is_checked():
            node.check(force=True)
        if node.is_checked():
            accepted += 1
    return accepted


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
