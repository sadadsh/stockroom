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
    """The vendor-side export categories a set of Requirements implies.

    `model` is its OWN category, not part of `kicad`. Measured on Ultra Librarian 2026-07-27: the
    STEP model lives behind a separate "3D CAD Model" accordion (`#MfrThreeDModel`), so a capture
    that only ticked the KiCad box came back with a symbol and a footprint and NO 3D - which is
    exactly what happened, and the run still reported success.
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
        # Altium IS supplied - through the PCAD row, NOT the script row.
        #
        # The Altium accordion holds THREE rows and they are not interchangeable. From the real
        # export panel captured at tests/backend/host/fixtures/ul-export-panel.html:
        #     #AltiumDesigner  value=0  "Altium Designer (script based)"
        #     #AltiumPCADv14   value=1  "PCAD v14"
        #     #AltiumPCADV15   value=2  "PCAD v15"
        # The script row ships `AltiumDesigner/UL_Import.pas` + a `.PrjScr` - a Delphi script that
        # builds the libraries INSIDE Altium - and no library files at all. The PCAD rows ship
        # `AltiumV15/<stamp>.lia`, a P-CAD ASCII library Altium imports directly, carrying one
        # symbolDef AND one patternDef, so ONE file satisfies altium_symbol and altium_footprint
        # together (see capture/classify.py and its tests).
        #
        # THE VENDOR CAN SUPPLY IT; THIS APP CANNOT YET STORE IT. Both halves matter, so read on
        # before flipping this to ("kicad", "altium") - that flip was tried on 2026-07-27 and is
        # what this comment exists to stop being retried blind.
        #
        # What is TRUE about the vendor: measuring only the script row and concluding "Ultra
        # Librarian cannot supply Altium" was WRONG, an over-generalisation from one row of three.
        # Owner, 2026-07-27: *"in ul when u download the altium pcad files it gives u a lia"*.
        # Ticking #AltiumPCADV15 really does deliver `AltiumV15/<stamp>.lia`, and
        # `capture/classify.py` correctly reads a P-CAD ASCII library as BOTH Altium assets. That
        # much is verified end to end against the fixture.
        #
        # WHY THE CAPABILITY STILL SAYS ("kicad",): `version_pins` is what `GuidedCaptureSource.
        # provides()` derives from, so adding "altium" here makes the engine SCHEDULE parts for
        # altium_symbol/altium_footprint - and nothing downstream can satisfy them:
        #   * `capture/guided.py::_attach` only ever offers the three KiCad requirements;
        #   * `ingest/staging.py::StagingCandidate` carries no Altium field at all;
        #   * `library_ops.attach_altium_assets` -> `altium/extract.py::normalize_altium_source`
        #     accepts .SchLib/.PcbLib/.IntLib and raises ValueError on anything else, so a `.lia`
        #     is refused outright.
        # The result would be a part requested, downloaded and then never satisfied: a run that
        # reports progress forever, which is precisely the "success that attached nothing" this
        # file already got burned by once.
        #
        # DONE LOOKS LIKE: a `.lia` converted to `.SchLib`/`.PcbLib` and attached. THAT IS A BUILD
        # TASK WITH A DOCUMENTED PATH, not an open research question - a previous version of this
        # comment implied otherwise, which was a negative conclusion reached without researching it
        # (owner corrected it, 2026-07-27).
        #
        # THREE independent routes exist, and Altium is only one of them - an earlier version of
        # this comment implied Altium was required, which the owner pushed back on and was right:
        #   1. NO CONVERSION AT ALL. A vendor shipping native `.SchLib`/`.PcbLib` (SnapMagic's
        #      `altium_native`) needs none of this, and `guided.py::_attach` already stores those.
        #      This is the cheapest path and should be measured before either of the others.
        #   2. OPEN TOOLING, no Altium and no Windows. ACCEL_ASCII is an open format with existing
        #      parsers (`xtoolbox/pcad2kicad`; KiCad loads P-CAD ASCII natively), and `AltiumSharp`
        #      reads AND WRITES `.SchLib`/`.PcbLib` without Altium installed. Cost is a .NET
        #      dependency beside a Python backend, which is a real tradeoff, not a blocker.
        #   3. ALTIUM ITSELF. Its Import Wizard translates a P-CAD library carrying BOTH pattern and
        #      symbol info into a `.PcbLib` AND a `.SchLib` (the documented caveat about symbol-ONLY
        #      libraries does not apply here); `altium/driver.py` already drives it. Windows + a
        #      license only. The same reasoning rehabilitates the `#AltiumDesigner` script row:
        #      `UL_Import.pas` IS DelphiScript, which is exactly what Altium's scripting system runs.
        tools=("kicad",),
        formats_exclusive=False,
        aggregator=False,
        needs_login=True,
        instruction="Pick the part, then Download Now. Symbol, footprint and 3D come together.",
        # measured element ids on the export panel. `model` is separate from `kicad`: the STEP
        # sits behind its own "3D CAD Model" accordion and is missed entirely if not ticked.
        # When altium IS wired, its pin must be "AltiumPCADV15" (the PCAD row) and never
        # "AltiumDesigner" (the script row, which ships UL_Import.pas and no libraries).
        version_pins={"kicad": "KiCADv6", "model": "MfrThreeDModel"},
    )

    # The accordion each format hides behind, by its visible text.
    _ACCORDION = {"kicad": "KiCAD", "altium": "Altium", "model": "3D CAD Model"}

    def signed_in(self, page) -> bool:
        """Whether this page is a signed-in session.

        THE ABSENCE OF `#loginLink` IS NOT ENOUGH, and assuming it was made this function report
        SUCCESS FOR A WRONG PASSWORD. Measured 2026-07-27 across all three real states:

            correct password -> www.ultralibrarian.com   #loginLink 0   #Username 0
            WRONG password   -> sso.../Account/Login     #loginLink 0   #Username 1
            signed out       -> app.ultralibrarian.com   #loginLink 1   #Username 0

        `#loginLink` is absent in BOTH the success and the failure case, because the identity
        server's login page simply has no such header. So a check built on it alone cannot tell a
        hit from a miss - caught only by feeding it a deliberately wrong password, which returned
        the same `''` in the same 3.5s as the correct one.

        All three signals are therefore required: not on the identity host, no login form on screen,
        and no sign-in link in the header.
        """
        try:
            url = page.url or ""
            if "sso." in url or "/Account/Login" in url:
                return False
            if page.locator("#Username").count() > 0:
                return False
            return page.locator("#loginLink").count() == 0
        except Exception:  # noqa: BLE001 - an unreadable page is not a signed-in one
            return False

    def sign_in(self, page, username: str, password: str) -> str:
        """Sign in so a whole-library run is unattended. "" on success, else a readable reason.

        WHY THIS EXISTS. Measured against the live site 2026-07-27: signed OUT, everything works -
        search resolves, the details page opens, the export panel renders 39 controls, and KiCad and
        3D both tick. The ONLY thing missing is the Download button, which the site renders solely
        for a signed-in user. So one sign-in is the difference between a 90-part sitting completing
        by itself and failing on every single part.

        MEASURED FORM (the real one, enumerated 2026-07-27): login is OIDC on a DIFFERENT host,
        `sso.ultralibrarian.com/Account/Login`, carrying `#Username`, `#Password`, `#RememberLogin`
        and `button[name=button][value=login]`, plus an ASP.NET `__RequestVerificationToken`. The
        token is why this fills and submits the REAL form rather than posting credentials directly -
        a hand-built POST would be rejected, and would also be a second implementation of signing in.

        `#RememberLogin` is TICKED deliberately: it is what makes the persistent browser profile keep
        the session between runs, so the owner signs in once rather than once per run.
        """
        if not username or not password:
            return "no Ultra Librarian credentials are saved in Settings"
        try:
            page.goto("https://app.ultralibrarian.com/Account/Login", wait_until="domcontentloaded")
            user_box = page.locator("#Username").first
            user_box.wait_for(state="visible", timeout=30_000)
            user_box.fill(username)
            page.locator("#Password").first.fill(password)
            # Remembered session = the whole point of the persistent profile.
            _check_box(page, "#RememberLogin")
            # The click's OWN navigation wait must not decide anything. Playwright's `click()`
            # waits for the navigation it triggers to settle, and on this OIDC form_post bounce
            # that wait timed out after 30s on a login that was otherwise fine - reporting a hard
            # failure for a sign-in that had very likely succeeded. The outcome is decided
            # exclusively by `_await_sign_in`, which polls signals that mean something, so a click
            # that raises mid-navigation is swallowed on purpose rather than trusted.
            try:
                page.locator('button[name="button"][value="login"]').first.click(timeout=15_000)
            except Exception:  # noqa: BLE001 - navigating away IS the expected outcome of this click
                pass
            return self._await_sign_in(page)
        except Exception as exc:  # noqa: BLE001 - a failed sign-in is a reportable row, not a crash
            return f"could not sign in to Ultra Librarian: {exc}"

    def _await_sign_in(self, page, timeout_s: float = 30.0) -> str:
        """Poll the two REAL signals after submitting the login form. "" once signed in.

        NEVER a fixed sleep followed by one look. Sign-in completes through an OIDC `form_post`
        bounce from `sso.ultralibrarian.com` back to `app.ultralibrarian.com`, whose duration
        depends on the network - so "sleep 2s, then check" reports "did not accept the saved
        credentials" for a login that simply took 2.1 seconds, which is a false failure on CORRECT
        credentials and would look exactly like a wrong password.

        Both signals are MEASURED on the real pages rather than invented:
          * SUCCESS - the header's `#loginLink` is gone (`signed_in`). Ends the wait the instant it
            is true, so a fast login costs no wait at all.
          * FAILURE - `#Username` is present AGAIN. The identity server re-renders the login form on
            a rejected credential, so the field coming back IS the rejection, available immediately
            instead of at the end of a clock.
        The timeout is only a backstop for a vendor that never answers either way.
        """
        import time as _time

        deadline = _time.monotonic() + timeout_s
        while _time.monotonic() < deadline:
            # FAILURE IS CHECKED FIRST, on purpose. It is the unambiguous one - the identity server
            # re-renders the login form and says why - whereas "looks signed in" is inferred from
            # several absences. Checking success first is what let a wrong password return "".
            try:
                if page.locator("#Username").count() > 0 and "sso." in (page.url or ""):
                    body = ""
                    try:
                        body = page.inner_text("body") or ""
                    except Exception:  # noqa: BLE001 - the URL alone already settles it
                        pass
                    # measured wording on a rejected login: "Error Invalid username or password"
                    if "invalid username or password" in body.lower():
                        return (
                            "Ultra Librarian rejected the saved credentials: invalid username or "
                            "password. Update them in Settings."
                        )
                    return (
                        "Ultra Librarian did not accept the saved credentials. Check the username "
                        "and password in Settings."
                    )
            except Exception:  # noqa: BLE001 - mid-navigation reads are expected; keep polling
                pass
            if self.signed_in(page):
                return ""
            page.wait_for_timeout(250)
        return (
            f"Ultra Librarian did not finish signing in within {int(timeout_s)}s, and never showed "
            "either a signed-in header or a rejected login form."
        )

    def resolve_url(self, mpn: str) -> str:
        from stockroom.enrich.cad_sources import resolve_cad_sources

        for source in resolve_cad_sources(mpn):
            if source.key == "ultralibrarian":
                return source.url
        return ""

    def open_panel(self, page) -> str:
        """Navigate from wherever we landed to the export panel, and say what happened.

        THE WHOLE JOURNEY, not just the last screen. `resolve_url` returns a SEARCH url, so a
        drive that assumed the export panel was already on screen would find nothing on the real
        site - it only worked against a fixture captured at the end state. That gap is exactly the
        kind a fixture cannot catch, so the steps are explicit here:

            /search?queryText=<MPN>   -> the first result's a[href*="/details/"]
            /details/<guid>/<mfr>/<mpn>  -> the export panel, reached by `&open=exports`
                                            (a real deep link, measured) or #export-selection-btn

        Returns "" on success, else a human-readable reason.
        """
        if page.locator("input[name=exports]").count() > 0:
            return ""  # already there

        if "/search" in (page.url or ""):
            results = page.locator('a[href*="/details/"]')
            try:
                results.first.wait_for(state="visible", timeout=20_000)
            except Exception:  # noqa: BLE001 - no result is an answer, not a crash
                return "Ultra Librarian has no model for this part."
            href = results.first.get_attribute("href") or ""
            if not href:
                return "the result row carried no link"
            page.goto(_absolute(page, href), wait_until="domcontentloaded")

        # The export panel is a real deep link on the part page - fewer clicks than the button,
        # and it survives the button being renamed.
        if "/details/" in (page.url or "") and "open=exports" not in (page.url or ""):
            joiner = "&" if "?" in page.url else "?"
            page.goto(f"{page.url}{joiner}open=exports", wait_until="domcontentloaded")

        try:
            page.locator("input[name=exports]").first.wait_for(state="attached", timeout=20_000)
        except Exception:  # noqa: BLE001
            if page.locator('a[href*="/Account/Login"]').count() > 0:
                return "Sign in to Ultra Librarian in the window; the sign-in is remembered."
            return "the CAD format list did not open on this page"
        return ""

    def drive(self, page, formats: list[str]) -> DriveReport:
        blocked = self.open_panel(page)
        if blocked:
            return DriveReport(missed=list(formats), message=blocked)
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
        # STATES INTENT, NEVER ACHIEVEMENT. A drive can only observe what it SELECTED and that it
        # clicked submit; whether the files arrived is decided later, by `classify_asset` on the
        # actual download. The previous wording ("Downloading kicad and altium together") was a
        # claim this code had no way to check, and on the live site it was FALSE - the zip carried
        # no Altium libraries at all. The engine reports what landed, from the record.
        report.message = (
            "Requested " + " and ".join(report.selected) + " from " + self.capability.label + "."
            if not report.missed
            else "Requested "
            + " and ".join(report.selected)
            + ", but could not select "
            + " and ".join(report.missed)
            + " on this page."
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
    """Tick a checkbox and READ ITS STATE BACK, with a real fallback when the first way fails.

    Never trusts the click: a handler can refuse it, a collapsed panel can swallow it. The same
    verify-after-click lesson the DigiKey driver learned the expensive way.

    THE FALLBACK IS NOT DEFENSIVE PADDING - it is load-bearing. Ultra Librarian's export options are
    Bootstrap `custom-control-input`s: the real input is visually replaced by a styled label, and
    Playwright's `check()` raises "Clicking the checkbox did not change its state" on them even with
    force. A direct `.click()` in page context does toggle them. Measured 2026-07-27: the KiCad and
    3D rows happened to accept `check()` and `#AltiumPCADV15` did not - so relying on one mechanism
    silently lost Altium while appearing to work for everything else. That is the worst shape of
    failure here, because the run still reports success for the formats that did tick.

    Either way the RETURN is the state read back off the element, so a miss is reported honestly.
    """
    box = page.locator(selector).first
    if box.count() == 0:
        return False
    if not box.is_checked():
        try:
            box.check(force=True, timeout=5_000)
        except Exception:  # noqa: BLE001 - a styled control refuses the synthetic check; try JS
            pass
    if not box.is_checked():
        try:
            page.evaluate(
                "sel => { const el = document.querySelector(sel); if (el) el.click(); }", selector
            )
        except Exception:  # noqa: BLE001 - report the honest miss rather than raising
            pass
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


def _absolute(page, href: str) -> str:
    """Resolve a vendor's relative link against the page it came from."""
    if href.startswith("http://") or href.startswith("https://"):
        return href
    from urllib.parse import urljoin

    return urljoin(page.url, href)


class SnapMagicAdapter:
    """SnapMagic (SnapEDA). Runs ALONGSIDE Ultra Librarian, never instead of it.

    Owner, 2026-07-27: *"i wanted both"* and *"check both to see which one has it, and if one
    download fails use the other."* The completion engine already gives that for free - it walks its
    sources in order and skips any whose `provides()` no longer overlaps what a part still needs -
    so registering this second is the whole fallback chain.

    ITS MECHANICS ARE THE OPPOSITE OF ULTRA LIBRARIAN'S, which is why it is a separate adapter
    rather than a config difference (measured 2026-07-27 against the live signed-in site):

      * ONE BUTTON PER FORMAT, so each format is its own download -> `formats_exclusive=True`, and
        `GuidedCaptureSource` sequences them. Ultra Librarian ticks checkboxes and exports once.
      * KiCad is a TWO-STEP chooser: `[data-format=kicad_options]` opens a version list whose
        members are `kicad` (V3 & prior), `kicad_mod` (V4+) and `kicad_modv6` (V6+). Taking the
        wrong one downloads a library `Footprint.load` REFUSES - the same version trap Ultra
        Librarian has, at a second vendor, which is why the pin is mandatory data rather than a
        default.
      * Altium is ONE step, `[data-format=altium_native]`, and NATIVE - `.SchLib`/`.PcbLib` rather
        than Ultra Librarian's P-CAD `.lia`. That matters: `guided.py::_attach` can store those
        directly, with no conversion anywhere.
      * the 3D model is a SEPARATE download (`#download_step_model`), not part of either.

    THE WALL, stated because it decides the workflow: SnapEDA serves a Cloudflare Turnstile
    interstitial to a plain browser. That is why the capture engine defaults to camoufox, which was
    measured walking straight through it. Auto-clicking a Turnstile only trips detection harder
    (learned 2026-07-24), so a person clears it once into the persistent profile if it ever appears.
    """

    capability = VendorCapability(
        key="snapmagic",
        label="SnapMagic",
        # Altium is NATIVE here, unlike Ultra Librarian's PCAD `.lia`, so both tools are real.
        tools=("kicad", "altium"),
        formats_exclusive=True,
        # It hosts community and automatically generated models as well as authored ones, so it is ordered
        # AFTER Ultra Librarian in the source chain rather than being an equal first choice.
        aggregator=False,
        needs_login=True,
        instruction="Clear the human check once if it appears, then the downloads run themselves.",
        version_pins={"kicad": "kicad_modv6", "altium": "altium_native", "model": "step_model"},
    )

    def resolve_url(self, mpn: str) -> str:
        from stockroom.enrich.cad_sources import resolve_cad_sources

        for source in resolve_cad_sources(mpn):
            if source.key == "snapmagic":
                return source.url
        return ""

    def signed_in(self, page) -> bool:
        """A signed-in SnapEDA session shows an account menu instead of a Login link."""
        try:
            if page.locator("a[href*='/account/login']").count() > 0:
                return False
            return page.locator("a[href*='/account/logout'], a[href*='logout']").count() > 0
        except Exception:  # noqa: BLE001 - an unreadable page is not a signed-in one
            return False

    def open_panel(self, page) -> str:
        """Search -> part page -> the "Choose Download Format" modal. "" when the formats are up."""
        if page.locator("[data-format]").count() > 0:
            return ""
        body = ""
        try:
            body = (page.inner_text("body") or "").lower()
        except Exception:  # noqa: BLE001 - a page mid-navigation is not a verdict
            pass
        if "just a moment" in body or "security verification" in body:
            return (
                "SnapMagic is asking you to confirm you are human. Clear it once in this window; "
                "it is remembered afterwards."
            )
        if "/search" in (page.url or ""):
            results = page.locator('a[href*="view-part"]')
            try:
                results.first.wait_for(state="visible", timeout=20_000)
            except Exception:  # noqa: BLE001 - no result IS an answer, and a normal one
                return "SnapMagic has no model for this part."
            href = results.first.get_attribute("href") or ""
            if not href:
                return "the SnapMagic result row carried no link"
            page.goto(_absolute(page, href), wait_until="domcontentloaded")
        opener = page.locator('a[name="download-modal"]').first
        if opener.count() == 0:
            return "SnapMagic showed no download control for this part."
        opener.click()
        try:
            page.locator("[data-format]").first.wait_for(state="attached", timeout=15_000)
        except Exception:  # noqa: BLE001
            return "the SnapMagic format list did not open"
        return ""

    def drive(self, page, formats: list[str]) -> DriveReport:
        """Select ONE format and trigger its download.

        The engine calls this once per format because on SnapMagic each is a separate file; taking
        `formats[:1]` here means a caller that forgets cannot silently lose the rest - it gets one
        file and an honest report naming the one it took.
        """
        report = DriveReport()
        blocked = self.open_panel(page)
        if blocked:
            report.missed = list(formats)
            report.message = blocked
            return report
        for fmt in formats[:1]:
            target = self.capability.version_pins.get(fmt)
            if not target:
                report.missed.append(fmt)
                continue
            if fmt == "kicad":
                # the version chooser has to be opened before its members exist in the DOM
                opener = page.locator('[data-format="kicad_options"]').first
                if opener.count():
                    opener.click()
                    page.wait_for_timeout(300)
            button = page.locator(f'[data-format="{target}"]').first
            if button.count() == 0:
                report.missed.append(fmt)
                continue
            button.click()
            report.selected.append(fmt)
            report.submitted = True
        report.message = (
            f"Requested {' and '.join(report.selected)} from SnapMagic."
            if report.selected
            else f"SnapMagic does not offer {' or '.join(report.missed)} for this part."
        )
        return report


_ADAPTERS[SnapMagicAdapter.capability.key] = SnapMagicAdapter()
