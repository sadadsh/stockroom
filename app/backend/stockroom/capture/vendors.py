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
    needs a login, and (critically) WHICH exact export choice to take.
  * BEHAVIOUR is a method - `drive()` - written per vendor against measured selectors and locked
    by a driver-execution test over a captured fixture of the real page.

THE EXPORT CHOICE IS NOT OPTIONAL
Two vendors independently offer exports this repo cannot ingest: Ultra Librarian lists KiCAD v5
one row above v6+, and SnapEDA's KiCad chooser offers "V3 & Prior" / "V4 & Later" / "V6 & Later".
KiCad 5 emits `(module ...)` footprints that `Footprint.load` REFUSES. A wrong pick downloads a
file that fails much later, far from the cause, so the machine selector or exact human-visible
choice is declared explicitly per vendor and never defaulted.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace
from typing import Literal, Protocol
from unicodedata import normalize
from urllib.parse import parse_qs, unquote, urlparse

from stockroom.capture.identity import (
    exact_observation_error,
    page_identity,
    provider_url_allowed,
)
from stockroom.capture.requirements import Requirement

_KICAD_REQS = frozenset(
    {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT, Requirement.KICAD_MODEL}
)
_ALTIUM_REQS = frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})
BrowserAccessPolicy = Literal["user_driven", "machine_allowed"]


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
    # Exact provider control id/value for formats a reviewed machine-access adapter may drive.
    version_pins: dict[str, str] = field(default_factory=dict)
    # Exact visible provider choice for a reviewed machine-access adapter when the control id is
    # not a stable contract. Matching is exact and unique; a nearby legacy choice is never used.
    machine_format_labels: dict[str, str] = field(default_factory=dict)
    # Exact visible choices a person selects in a provider-controlled page. These are deliberately
    # separate from DOM ids: a user-driven provider can be a supported acquisition route without
    # granting Stockroom permission to inspect or operate its controls.
    user_format_labels: dict[str, str] = field(default_factory=dict)
    # Provider-side DOM automation is opt-in, never inferred from having an adapter. Commercial
    # sites remain user-driven until a separately reviewed machine-access contract permits it.
    browser_access: BrowserAccessPolicy = "user_driven"

    @property
    def supported_formats(self) -> frozenset[str]:
        """Formats the end-to-end capture path can accept, independent of browser-control policy."""

        return (
            frozenset(self.version_pins)
            | frozenset(self.machine_format_labels)
            | frozenset(self.user_format_labels)
        )


class VendorAdapter(Protocol):
    """One vendor's capture behaviour."""

    capability: VendorCapability

    def resolve_url(self, mpn: str) -> str:
        """The page this part lives at."""

    def drive(
        self,
        page,
        formats: list[str],
        *,
        expected_manufacturer: str = "",
        expected_mpn: str = "",
    ) -> "DriveReport":
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
    # A provider-wide challenge/auth/account gate, not a fact about this MPN. The batch engine
    # treats this as deferred and trips its circuit breaker instead of burning every remaining row.
    blocked: bool = False
    # True only when automation stopped at authentication, CAPTCHA, 2FA, or another security
    # control that Stockroom must never operate. The browser shows a handoff HUD and resumes only
    # after the person clears it.
    requires_user_clearance: bool = False
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
        # Ultra Librarian introduced a native Altium export on 2025-10-16. Its current official
        # workflow yields .LibPkg, .SchLib, .PcbLib, and an integrated STEP model. The 2026-07-27
        # fixture predates that option and remains useful only for the legacy PCAD/script controls.
        # Sources: ultralibrarian.com/native_export_for_altium_designer and
        # app.ultralibrarian.com/content/help/altium_designer_2.htm.
        # A private-evaluation authorization from an Ultra Librarian manager permits this user's
        # installation to exercise the reviewed adapter. Runtime access remains default-off behind
        # `ul_private_evaluation_automation` and two emergency kill switches; this declaration only
        # says the adapter is eligible when that separate policy check succeeds.
        tools=("kicad", "altium"),
        formats_exclusive=False,
        aggregator=False,
        needs_login=True,
        instruction=(
            "Confirm the exact part, select KiCad, STEP, and Altium Designer (Native), then choose "
            "Download Now. Stockroom captures every delivered file."
        ),
        # Measured element ids on the export panel. `model` is separate from `kicad`: the STEP
        # sits behind its own "3D CAD Model" accordion and is missed entirely if not ticked.
        # `ThreeDModel` is the current live id (2026-07-28). Older captured panels used
        # `MfrThreeDModel`; `_export_selectors` retains that as a compatibility fallback without
        # making the stale id the declared production pin.
        version_pins={"kicad": "KiCADv6", "model": "ThreeDModel"},
        machine_format_labels={"altium": "Altium Designer (Native)"},
        user_format_labels={
            "kicad": "KiCad 6 or later",
            "model": "STEP",
            "altium": "Altium Designer (Native)",
        },
        browser_access="machine_allowed",
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
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or (parsed.hostname or "").casefold() not in {
                "app.ultralibrarian.com",
                "www.ultralibrarian.com",
            }:
                return False
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
        import time as _time

        if not username or not password:
            return "no Ultra Librarian credentials are saved in Settings"
        try:
            security = _security_verification_issue(page, self.capability.label)
            if security:
                return security
            if self.signed_in(page):
                return ""
            page.goto("https://app.ultralibrarian.com/Account/Login", wait_until="domcontentloaded")
            security = _security_verification_issue(page, self.capability.label)
            if security:
                return security
            if self.signed_in(page):
                return ""
            user_box = page.locator("#Username").first
            deadline = _time.monotonic() + 30.0
            while user_box.count() == 0:
                security = _security_verification_issue(page, self.capability.label)
                if security:
                    return security
                if self.signed_in(page):
                    return ""
                if _time.monotonic() >= deadline:
                    return (
                        "Ultra Librarian showed neither its login form nor an authenticated "
                        "session within 30s."
                    )
                page.wait_for_timeout(250)
                user_box = page.locator("#Username").first
            security = _security_verification_issue(page, self.capability.label)
            if security:
                return security
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
            security = _security_verification_issue(page, self.capability.label)
            if security:
                return security
            # Credential rejection remains ahead of the inferred signed-in state, but security
            # controls are checked first so a CAPTCHA/MFA page retaining the form is never
            # mislabeled as a bad password.
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

    def open_panel(
        self,
        page,
        *,
        expected_manufacturer: str = "",
        expected_mpn: str = "",
    ) -> str:
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
            return _detail_identity_issue(
                "ultralibrarian",
                page.url or "",
                expected_manufacturer,
                expected_mpn,
            )
        challenge = _challenge_issue(page, "Ultra Librarian")
        if challenge:
            return challenge
        missing = _ultralibrarian_missing_model_issue(page)
        if missing:
            return missing

        if "/search" in (page.url or ""):
            requested_mpn = expected_mpn or _requested_mpn(page.url, ("queryText",))
            results = page.locator('a[href*="/details/"]')
            try:
                results.first.wait_for(state="visible", timeout=20_000)
            except Exception:  # noqa: BLE001 - no result is an answer, not a crash
                return "Ultra Librarian has no model for this part."
            href, selection_error = _exact_result_href(
                results,
                requested_mpn,
                expected_manufacturer=expected_manufacturer,
                vendor_key="ultralibrarian",
            )
            if selection_error:
                return f"Ultra Librarian {selection_error}"
            if not href:
                return "the result row carried no link"
            page.goto(_absolute(page, href), wait_until="domcontentloaded")
            identity_issue = _detail_identity_issue(
                "ultralibrarian",
                page.url or "",
                expected_manufacturer,
                requested_mpn,
            )
            if identity_issue:
                return identity_issue
            challenge = _challenge_issue(page, "Ultra Librarian")
            if challenge:
                return challenge
            missing = _ultralibrarian_missing_model_issue(page)
            if missing:
                return missing

        # The export panel is a real deep link on the part page - fewer clicks than the button,
        # and it survives the button being renamed.
        if "/details/" in (page.url or "") and "open=exports" not in (page.url or ""):
            identity_issue = _detail_identity_issue(
                "ultralibrarian",
                page.url or "",
                expected_manufacturer,
                expected_mpn,
            )
            if identity_issue:
                return identity_issue
            joiner = "&" if "?" in page.url else "?"
            page.goto(f"{page.url}{joiner}open=exports", wait_until="domcontentloaded")
            identity_issue = _detail_identity_issue(
                "ultralibrarian",
                page.url or "",
                expected_manufacturer,
                expected_mpn,
            )
            if identity_issue:
                return identity_issue
            missing = _ultralibrarian_missing_model_issue(page)
            if missing:
                return missing

        try:
            page.locator("input[name=exports]").first.wait_for(state="attached", timeout=20_000)
        except Exception:  # noqa: BLE001
            challenge = _challenge_issue(page, "Ultra Librarian")
            if challenge:
                return challenge
            missing = _ultralibrarian_missing_model_issue(page)
            if missing:
                return missing
            if page.locator('a[href*="/Account/Login"]').count() > 0:
                return "Sign in to Ultra Librarian in the window; the sign-in is remembered."
            return "the CAD format list did not open on this page"
        return _detail_identity_issue(
            "ultralibrarian",
            page.url or "",
            expected_manufacturer,
            expected_mpn,
        )

    def drive(
        self,
        page,
        formats: list[str],
        *,
        expected_manufacturer: str = "",
        expected_mpn: str = "",
    ) -> DriveReport:
        if not expected_manufacturer.strip() or not expected_mpn.strip():
            return DriveReport(
                missed=list(formats),
                blocked=True,
                message=(
                    "Ultra Librarian automatic capture requires the exact expected manufacturer "
                    "and MPN before it may inspect or operate a provider page."
                ),
            )
        blocked = self.open_panel(
            page,
            expected_manufacturer=expected_manufacturer,
            expected_mpn=expected_mpn,
        )
        if blocked:
            clearance = self.user_clearance_issue(page)
            return DriveReport(
                missed=list(formats),
                blocked=bool(clearance) or _is_global_blockage(blocked),
                requires_user_clearance=bool(clearance),
                message=blocked,
            )
        identity_issue = _detail_identity_issue(
            "ultralibrarian",
            page.url or "",
            expected_manufacturer,
            expected_mpn,
        )
        if identity_issue:
            return DriveReport(missed=list(formats), message=identity_issue)
        report = DriveReport()
        missed_reasons: list[str] = []
        # Export choices persist in the page/session. A previous Altium v14 selection was measured
        # still checked on the next live part (2026-07-28). Starting from that ambient state can
        # silently request an obsolete or unsupported format beside the pinned one. Clear every
        # export choice first, verify the clear, then select only this run's declared pins.
        if not _clear_export_selections(page):
            return DriveReport(
                missed=list(formats),
                blocked=True,
                message=(
                    "Ultra Librarian kept a previous export selection checked; refusing to submit "
                    "an ambiguous format set."
                ),
            )
        for fmt in formats:
            box_id = self.capability.version_pins.get(fmt)
            exact_label = self.capability.machine_format_labels.get(fmt)
            if not box_id and not exact_label:
                report.missed.append(fmt)
                continue
            accordion = self._ACCORDION.get(fmt)
            if accordion:
                _click_accordion(page, accordion)
            if box_id and any(
                _check_box(page, selector) for selector in _export_selectors(fmt, box_id)
            ):
                report.selected.append(fmt)
            elif exact_label:
                selected, reason = _check_exact_export_label(page, exact_label)
                if selected:
                    report.selected.append(fmt)
                else:
                    report.missed.append(fmt)
                    missed_reasons.append(reason)
            else:
                report.missed.append(fmt)

        _accept_consents(page)

        identity_issue = _detail_identity_issue(
            "ultralibrarian",
            page.url or "",
            expected_manufacturer,
            expected_mpn,
        )
        if identity_issue:
            return DriveReport(missed=list(formats), message=identity_issue)
        if not report.selected:
            report.message = " ".join(missed_reasons) or (
                "Could not select "
                + " or ".join(report.missed)
                + " on this page; choose the format and click Download Now."
            )
            return report

        submit = page.locator("#submit-export").first
        if submit.count() == 0:
            report.blocked = True
            report.requires_user_clearance = bool(self.user_clearance_issue(page))
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
        if missed_reasons:
            report.message += " " + " ".join(missed_reasons)
        return report

    def download_gate(self, page) -> str:
        """Provider-wide state explaining why a submitted export produced no browser download."""
        return self.user_clearance_issue(page)

    def user_clearance_issue(self, page) -> str:
        """Security or authentication state that requires a person, never automation."""

        security = _security_verification_issue(page, self.capability.label)
        if security:
            return security
        try:
            url = page.url or ""
            login_form = page.locator("#Username").count() > 0
            login_link = page.locator('a[href*="/Account/Login"]').count() > 0
            if (
                "sso.ultralibrarian.com" in url.casefold()
                or "/account/login" in url.casefold()
                or login_form
                or login_link
            ):
                return (
                    "Ultra Librarian needs you to finish sign-in or its security verification in "
                    "this window. Stockroom never operates CAPTCHA, 2FA, or security controls and "
                    "will resume automatically after you clear them."
                )
        except Exception:  # noqa: BLE001 - unreadable state is not evidence of a security gate
            pass
        return ""


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


def _check_exact_export_label(page, exact_label: str) -> tuple[bool, str]:
    """Select one uniquely and exactly labelled Ultra Librarian export.

    The native Altium control's DOM id is not a published contract. Its exact visible label is:
    Ultra Librarian's current help and announcement distinguish ``Altium Designer (Native)`` from
    the legacy Altium script and P-CAD exports. Matching a substring such as ``Altium Designer``
    would therefore select the very fallback this path is forbidden to use.
    """

    wanted = " ".join(normalize("NFKC", exact_label or "").split())
    labels = page.locator("label[for]")
    matching_ids: list[str] = []
    for index in range(labels.count()):
        label = labels.nth(index)
        try:
            visible = " ".join(normalize("NFKC", label.inner_text() or "").split())
            control_id = (label.get_attribute("for") or "").strip()
        except Exception:  # noqa: BLE001 - an unreadable label cannot establish an exact choice
            continue
        if visible == wanted and control_id and control_id not in matching_ids:
            matching_ids.append(control_id)
    if not matching_ids:
        return (
            False,
            "Ultra Librarian does not offer Altium Designer (Native) for this exact part; legacy "
            "Altium script, .lia, and P-CAD exports were not selected.",
        )
    if len(matching_ids) != 1:
        return (
            False,
            "Ultra Librarian exposed multiple Altium Designer (Native) choices; refusing an "
            "ambiguous export.",
        )
    escaped = matching_ids[0].replace("\\", "\\\\").replace('"', '\\"')
    selector = f'input[name="exports"][id="{escaped}"]'
    if _check_box(page, selector):
        return True, ""
    return (
        False,
        "Ultra Librarian exposed Altium Designer (Native), but its exact checkbox did not remain "
        "selected; legacy exports were not used.",
    )


def _uncheck_box(page, selector: str) -> bool:
    """Clear one checkbox and verify its state, including styled-input fallback."""
    box = page.locator(selector).first
    if box.count() == 0:
        return True
    if box.is_checked():
        try:
            box.uncheck(force=True, timeout=5_000)
        except Exception:  # noqa: BLE001 - styled controls may reject Playwright's uncheck
            pass
    if box.is_checked():
        try:
            page.evaluate(
                "sel => { const el = document.querySelector(sel); if (el && el.checked) el.click(); }",
                selector,
            )
        except Exception:  # noqa: BLE001 - the verified return below remains authoritative
            pass
    return not box.is_checked()


def _clear_export_selections(page) -> bool:
    """Clear all persisted Ultra Librarian export choices and read every state back."""
    selected = page.locator("input[name=exports]:checked")
    # Snapshot selectors before mutating: `:checked` is live, so indexing while clearing would skip
    # every other node.
    selectors: list[str] = []
    for index in range(selected.count()):
        node = selected.nth(index)
        box_id = node.get_attribute("id") or ""
        if not box_id:
            return False
        # Some real export ids contain spaces and punctuation (`TARGET 3001!`), so a CSS
        # `#id` selector is not generally valid here. An escaped attribute selector is.
        escaped = box_id.replace("\\", "\\\\").replace('"', '\\"')
        selectors.append(f'input[name="exports"][id="{escaped}"]')
    return all(_uncheck_box(page, selector) for selector in selectors) and (
        page.locator("input[name=exports]:checked").count() == 0
    )


def _export_selectors(fmt: str, declared_id: str) -> tuple[str, ...]:
    """Current selector first, then only measured backwards-compatible aliases."""
    selectors = [f"#{declared_id}"]
    if fmt == "model" and declared_id == "ThreeDModel":
        selectors.append("#MfrThreeDModel")
    return tuple(selectors)


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


_SNAPMAGIC_READY_FORMATS = (
    '[data-format="kicad_options"]:visible, '
    '[data-format="altium_native"]:visible, '
    '[data-format="step_model"]:visible'
)
_SNAPMAGIC_PART_STATE = (
    f"{_SNAPMAGIC_READY_FORMATS}, "
    'a[name="download-modal"]:visible, '
    'p:has-text("The 2D model for this part is not available"):visible, '
    'a:has-text("Request 3D Model"):visible'
)


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
      * Altium is ONE step, `[data-format=altium_native]`, and NATIVE - `.SchLib`/`.PcbLib`, which
        `guided.py::_attach` can store directly.
      * the 3D model is a SEPARATE download (`#download_step_model`), not part of either.

    THE WALL, stated because it decides the workflow: SnapEDA can serve a Cloudflare Turnstile
    interstitial. Production uses an installed Windows Chrome/Edge channel with an isolated
    persistent provider profile, so a person can clear the challenge once and retain that session.
    Camoufox is an explicit fallback for a measured need, not the production default. Auto-clicking
    a Turnstile only trips detection harder (learned 2026-07-24).
    """

    capability = VendorCapability(
        key="snapmagic",
        label="SnapMagic",
        # Both tools are native, so both can pass through Stockroom's existing attach seams.
        tools=("kicad", "altium"),
        formats_exclusive=True,
        # It hosts community and automatically generated models as well as authored ones, so its bytes are
        # lower-trust than Ultra Librarian's. Verification, not provider prose, decides whether
        # those bytes can attach.
        aggregator=False,
        needs_login=True,
        instruction="Clear the human check once if it appears, then the downloads run themselves.",
        version_pins={"kicad": "kicad_modv6", "altium": "altium_native", "model": "step_model"},
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

    _LOGIN_URL = "https://www.snapeda.com/account/login/"

    def signed_in(self, page) -> bool:
        """A signed-in SnapMagic session shows a logout link and no login link.

        BOTH halves are required, and the reason is the same one Ultra Librarian's `signed_in`
        records: a check built on the ABSENCE of one element cannot tell a signed-in page from a
        page that simply has no header. The logout link is the positive signal.
        """
        try:
            if page.locator("a[href*='/account/login']").count() > 0:
                return False
            return page.locator("a[href*='/account/logout'], a[href*='logout']").count() > 0
        except Exception:  # noqa: BLE001 - an unreadable page is not a signed-in one
            return False

    def sign_in(self, page, username: str, password: str) -> str:
        """Sign in so a whole-library run is unattended. "" on success, else a readable reason.

        WHY THIS EXISTS, and it is not a nicety. Measured live 2026-07-27 with `scripts/webread.py
        --vendor snapmagic --panel --controls`: signed OUT, the download modal opens and renders
        every format button - but EVERY ONE of them is an anchor whose href is
        `/account/signup/?next=...`. So a signed-out drive clicks "Altium", navigates to a signup
        page, and waits out its full 120s backstop having downloaded nothing. The adapter declared
        `needs_login=True` and shipped no `sign_in` at all, so saved credentials were never used and
        the failure looked like a vendor limitation. It is not one.

        MEASURED FORM (enumerated on the live page, 2026-07-27): a Django login carrying
        `#id_username` ("Username or Email"), `#id_password` and `input[type=submit].btn-submit`,
        all HIDDEN until the header's `a.ls-btn.login-btn` opens the panel - which is why they were
        invisible to a control survey that only reported visible elements. Filling and submitting
        the REAL form is deliberate: Django posts a `csrfmiddlewaretoken` with it, so a hand-built
        POST would be rejected and would also be a second implementation of signing in.
        """
        if not username or not password:
            return "no SnapMagic credentials are saved in Settings"
        try:
            page.goto(self._LOGIN_URL, wait_until="domcontentloaded")
            if self.signed_in(page):
                return ""
            user_box = page.locator("#id_username").first
            if user_box.count() == 0:
                return "SnapMagic showed no sign-in form"
            if not user_box.is_visible():
                # the fields exist in the DOM but live behind the header's Log In control
                opener = page.locator("a.ls-btn.login-btn").first
                if opener.count():
                    opener.click()
            user_box.wait_for(state="visible", timeout=20_000)
            user_box.fill(username)
            page.locator("#id_password").first.fill(password)
            # The click's OWN navigation wait must not decide anything: navigating away IS the
            # expected outcome, and letting a click timeout stand for a verdict is how a successful
            # login gets reported as a failure. `_await_sign_in` polls signals that mean something.
            try:
                page.locator("input[type=submit].btn-submit").first.click(timeout=15_000)
            except Exception:  # noqa: BLE001 - navigating away IS the point of this click
                pass
            return self._await_sign_in(page)
        except Exception as exc:  # noqa: BLE001 - a failed sign-in is a row, not a crash
            return f"could not sign in to SnapMagic: {exc}"

    def _await_sign_in(self, page, timeout_s: float = 30.0) -> str:
        """Poll the two REAL signals after submitting. "" once signed in.

        NEVER a fixed sleep followed by one look, and never the absence of one element on its own.
        Both signals are what the live pages actually do:
          * SUCCESS - a logout link is present and no login link is (`signed_in`). Ends the wait the
            instant it is true, so a fast login costs nothing.
          * FAILURE - the password field is on screen AGAIN. Django re-renders the login form with
            an error on a rejected credential, so the field coming back IS the rejection, available
            immediately rather than at the end of a clock.
        The timeout is only a backstop for a site that never answers either way.
        """
        import time as _time

        # LET THE SUBMIT LAND FIRST. The failure signal is "the login form is on screen again", and
        # the form is ALSO on screen for the fraction of a second between clicking submit and the
        # response rendering - so polling immediately reads the PRE-navigation DOM and returns
        # "did not accept the saved credentials" for a login still in flight. Measured 2026-07-27:
        # the verdict came back while `page.title()` still read "Loading ...".
        try:
            page.wait_for_load_state("domcontentloaded", timeout=int(timeout_s * 1000))
        except Exception:  # noqa: BLE001 - a slow settle is not a verdict either
            pass

        deadline = _time.monotonic() + timeout_s
        while _time.monotonic() < deadline:
            if self.signed_in(page):
                return ""
            try:
                # Both halves, because a visible password box alone is just the form. Django
                # re-renders it WITH an error, and on success the URL leaves /account/login.
                on_login = "/account/login" in (page.url or "")
                box = page.locator("#id_password")
                if on_login and box.count() > 0 and box.first.is_visible():
                    body = (page.inner_text("body") or "").lower()
                    if "correct username" in body or "incorrect" in body or "invalid" in body:
                        return "SnapMagic did not accept the saved credentials"
            except Exception:  # noqa: BLE001 - a page mid-navigation is not a verdict
                pass
            page.wait_for_timeout(400)
        return "SnapMagic did not confirm the sign-in"

    def open_panel(
        self,
        page,
        *,
        expected_manufacturer: str = "",
        expected_mpn: str = "",
    ) -> str:
        """Search -> part page -> the "Choose Download Format" modal. "" when the formats are up."""
        if page.locator(_SNAPMAGIC_READY_FORMATS).count() > 0:
            return _detail_identity_issue(
                "snapmagic",
                page.url or "",
                expected_manufacturer,
                expected_mpn,
            )
        challenge = _challenge_issue(page, "SnapMagic")
        if challenge:
            return challenge
        if "/search" in (page.url or ""):
            requested_mpn = expected_mpn or _requested_mpn(page.url, ("q",))
            results = page.locator('a[href*="view-part"]')
            try:
                results.first.wait_for(state="visible", timeout=20_000)
            except Exception:  # noqa: BLE001 - no result IS an answer, and a normal one
                return "SnapMagic has no model for this part."
            href, selection_error = _exact_result_href(
                results,
                requested_mpn,
                expected_manufacturer=expected_manufacturer,
                vendor_key="snapmagic",
            )
            if selection_error:
                return f"SnapMagic {selection_error}"
            if not href:
                return "the SnapMagic result row carried no link"
            page.goto(_absolute(page, href), wait_until="domcontentloaded")
            identity_issue = _detail_identity_issue(
                "snapmagic",
                page.url or "",
                expected_manufacturer,
                requested_mpn,
            )
            if identity_issue:
                return identity_issue
            challenge = _challenge_issue(page, "SnapMagic")
            if challenge:
                return challenge
        # The part body is client-rendered after ``domcontentloaded``. Wait for one real terminal
        # signal instead of reading too early and turning an explicit catalogue miss into the
        # generic "no download control" fallback.
        try:
            page.locator(_SNAPMAGIC_PART_STATE).first.wait_for(
                state="visible", timeout=15_000
            )
        except Exception:  # noqa: BLE001 - the checks below report the fail-closed fallback
            pass
        missing = _snapmagic_missing_model_issue(page)
        if missing:
            return missing
        account_issue = _snapmagic_account_issue(page)
        if account_issue:
            return account_issue
        opener = page.locator('a[name="download-modal"]:visible').first
        if opener.count() == 0:
            return "SnapMagic showed no download control for this part."
        opener.click()
        try:
            page.locator(_SNAPMAGIC_READY_FORMATS).first.wait_for(
                state="visible", timeout=15_000
            )
        except Exception:  # noqa: BLE001
            return "the SnapMagic format list did not open"
        return ""

    def drive(
        self,
        page,
        formats: list[str],
        *,
        expected_manufacturer: str = "",
        expected_mpn: str = "",
    ) -> DriveReport:
        """Select ONE format and trigger its download.

        The engine calls this once per format because on SnapMagic each is a separate file; taking
        `formats[:1]` here means a caller that forgets cannot silently lose the rest - it gets one
        file and an honest report naming the one it took.
        """
        report = DriveReport()
        blocked = self.open_panel(
            page,
            expected_manufacturer=expected_manufacturer,
            expected_mpn=expected_mpn,
        )
        if blocked:
            report.missed = list(formats)
            report.blocked = _is_global_blockage(blocked)
            report.message = blocked
            return report
        for fmt in formats[:1]:
            target = self.capability.version_pins.get(fmt)
            if not target:
                report.missed.append(fmt)
                continue
            if fmt == "kicad":
                # The version chooser has to be OPENED before its members exist in the DOM.
                #
                # This used to `wait_for_timeout(300)` and then test `count() == 0` - a SLEEP USED
                # AS A DETECTOR, and the most expensive kind. A chooser that took 301ms was
                # reported as `SnapMagic does not offer kicad for this part`: a false NEGATIVE,
                # indistinguishable from a real vendor limitation, on a vendor that had the file.
                # Waiting for the pinned member itself ends the instant it exists and turns the
                # timeout back into a backstop.
                opener = page.locator('[data-format="kicad_options"]').first
                if opener.count():
                    opener.click()
                    try:
                        page.locator(f'[data-format="{target}"]:visible').first.wait_for(
                            state="visible", timeout=10_000
                        )
                    except Exception:  # noqa: BLE001 - absence is answered by the check below
                        pass
            button = page.locator(f'[data-format="{target}"]:visible').first
            if button.count() == 0:
                report.missed.append(fmt)
                continue
            href = (button.get_attribute("href") or "").lower()
            if "/account/login" in href or "/account/signup" in href:
                report.missed.append(fmt)
                report.blocked = True
                report.message = (
                    "SnapMagic requires a signed-in, verified account before it will deliver "
                    f"{fmt}."
                )
                continue
            button.click()
            report.selected.append(fmt)
            report.submitted = True
        if not report.message:
            report.message = (
                f"Requested {' and '.join(report.selected)} from SnapMagic."
                if report.selected
                else f"SnapMagic does not offer {' or '.join(report.missed)} for this part."
            )
        return report

    def download_gate(self, page) -> str:
        """Explain a submitted button that changed the page but emitted no file.

        Live 2026-07-28: an unverified account changed the page to "Done! You just downloaded S1M"
        while Chrome emitted no download and no file appeared. DOM success is intent-shaped UI,
        never delivery evidence. This is consulted only after the saved-file backstop expires.
        """
        issue = _challenge_issue(page, self.capability.label) or _snapmagic_account_issue(page)
        if issue:
            return issue
        try:
            body = (page.inner_text("body") or "").casefold()
        except Exception:  # noqa: BLE001 - no readable gate evidence
            return ""
        if "done!" in body and "you just downloaded" in body:
            return (
                "SnapMagic reported that the download was done, but the browser received no file. "
                "The browser's multiple-file permission or another provider download gate must be "
                "resolved before continuing."
            )
        return ""


_ADAPTERS[SnapMagicAdapter.capability.key] = SnapMagicAdapter()


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


def _canonical_detail_identity(href: str) -> tuple[str, str, tuple[str, ...]] | None:
    """The stable destination behind one result link.

    Provider search pages repeat one part through image/title/action links and add presentation
    state such as Ultra Librarian's ``open=Pricing``. Those are one destination, not ambiguity.
    A provider's stable ``uid`` remains identity-bearing so genuinely distinct catalogue entries
    still fail closed.
    """
    try:
        parsed = urlparse(href)
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
) -> str:
    """Return a fail-closed provider-detail identity error when an expectation was supplied."""

    if not expected_mpn:
        return ""
    if not _provider_url_allowed(vendor_key, url):
        return (
            f"{vendor_key} left its official provider host; refusing to operate a lookalike "
            "detail path."
        )
    observed = page_identity(vendor_key, url)
    if observed is None:
        return (
            f"{vendor_key} did not expose the exact manufacturer and MPN in its detail URL; "
            "refusing to operate this page."
        )
    error = exact_observation_error(
        SimpleNamespace(manufacturer=expected_manufacturer, mpn=expected_mpn),
        observed,
    )
    return f"{vendor_key} {error}." if error else ""


def _exact_result_href(
    results,
    requested_mpn: str,
    *,
    expected_manufacturer: str = "",
    vendor_key: str = "",
) -> tuple[str, str]:
    """Choose one unique exact manufacturer+MPN result, or fail closed."""
    if not requested_mpn:
        return "", "could not recover the requested MPN from the search URL."
    matches: dict[tuple[str, str, tuple[str, ...]], str] = {}
    wrong_manufacturer = False
    for index in range(results.count()):
        node = results.nth(index)
        href = node.get_attribute("href") or ""
        text = ""
        try:
            text = node.inner_text() or ""
        except Exception:  # noqa: BLE001 - href evidence is sufficient
            pass
        exact_text = any(
            _mpn_key(line) == _mpn_key(requested_mpn) for line in text.splitlines() if line.strip()
        )
        if _href_demonstrates_mpn(href, requested_mpn) or exact_text:
            absolute = href.strip()
            if not _provider_url_allowed(vendor_key, absolute, allow_relative=True):
                continue
            if expected_manufacturer:
                observed = page_identity(vendor_key, absolute, allow_relative=True)
                if observed is None:
                    continue
                mismatch = exact_observation_error(
                    SimpleNamespace(
                        manufacturer=expected_manufacturer,
                        mpn=requested_mpn,
                    ),
                    observed,
                )
                if mismatch:
                    wrong_manufacturer = True
                    continue
            identity = _canonical_detail_identity(absolute)
            if identity is not None:
                matches.setdefault(identity, absolute)
    if not matches:
        if expected_manufacturer and wrong_manufacturer:
            return (
                "",
                "showed the requested MPN only under a different manufacturer; no near-match was "
                "selected.",
            )
        if expected_manufacturer:
            return (
                "",
                f"showed no exact result for manufacturer {expected_manufacturer!r} and requested "
                f"MPN {requested_mpn!r}.",
            )
        return "", f"showed no exact result for requested MPN {requested_mpn!r}."
    if len(matches) > 1:
        return "", f"showed multiple exact links for requested MPN {requested_mpn!r}."
    return next(iter(matches.values())), ""


def _visible_body_text(page) -> str:
    """Rendered body copy only; hidden provider templates are not availability evidence."""
    try:
        return " ".join((page.inner_text("body") or "").split()).casefold()
    except Exception:  # noqa: BLE001 - unreadable copy establishes no terminal state
        return ""


def _ultralibrarian_missing_model_issue(page) -> str:
    """A terminal exact-part miss rendered by Ultra Librarian."""
    body = _visible_body_text(page)
    if "no exact match found" in body:
        return "Ultra Librarian has no model for this part."
    unavailable = (
        "no symbol available",
        "no footprint available",
        "no 3d model available",
    )
    if all(marker in body for marker in unavailable):
        return "Ultra Librarian has no symbol, footprint, or 3D model for this part."
    return ""


def _snapmagic_missing_model_issue(page) -> str:
    """A terminal exact-part miss rendered by SnapMagic."""
    body = _visible_body_text(page)
    no_2d = "the 2d model for this part is not available" in body
    no_3d = "request 3d model" in body or "get this 3d model in" in body
    if no_2d and no_3d:
        return "SnapMagic has no downloadable symbol, footprint, or 3D model for this part."
    return ""


_CHALLENGE_MARKERS = (
    "access denied",
    "attention required",
    "challenges.cloudflare.com",
    "cloudflare ray id",
    "just a moment",
    "verify you are human",
    "verifying you are human",
    "security verification",
    "checking your browser",
    "cf-chl-",
    "challenge-platform",
    "captcha-delivery",
    "google.com/recaptcha",
    "recaptcha.net",
    "g-recaptcha",
    "hcaptcha.com",
    "h-captcha",
    "i'm not a robot",
    "i am not a robot",
    "turnstile",
)
_SECURITY_VERIFICATION_MARKERS = (
    "two-factor authentication",
    "two factor authentication",
    "multi-factor authentication",
    "multi factor authentication",
    "verification code",
    "security code",
    "one-time code",
    "one time code",
    "authenticator app",
    "approve sign-in",
    "approve sign in",
    "verify your identity",
    "use your passkey",
    "security key",
    "enter otp",
    "enter mfa",
)


def _challenge_issue(page, label: str) -> str:
    """Return an actionable explanation for a measured anti-bot interstitial."""
    samples: list[str] = [getattr(page, "url", "") or ""]
    try:
        samples.append(page.title() or "")
    except Exception:  # noqa: BLE001 - another signal may still identify it
        pass
    try:
        samples.append(page.inner_text("body") or "")
    except Exception:  # noqa: BLE001 - textless challenge shells are common
        pass
    try:
        frames = page.locator("iframe")
        for index in range(min(frames.count(), 20)):
            samples.append(frames.nth(index).get_attribute("src") or "")
    except Exception:  # noqa: BLE001 - frames are an optional signal
        pass
    evidence = "\n".join(samples).casefold()
    if not any(marker in evidence for marker in _CHALLENGE_MARKERS):
        return ""
    return (
        f"{label} is asking you to confirm you are human. Clear it once in this window; "
        "the provider-specific browser profile remembers the session."
    )


def _security_verification_issue(page, label: str) -> str:
    """CAPTCHA, MFA, passkey, or account-verification step that automation must not operate."""

    challenge = _challenge_issue(page, label)
    if challenge:
        return challenge
    body = _visible_body_text(page)
    if not any(marker in body for marker in _SECURITY_VERIFICATION_MARKERS):
        return ""
    return (
        f"{label} needs you to finish its security verification in this window. Stockroom never "
        "operates CAPTCHA, 2FA, MFA, passkeys, or security controls and will resume automatically "
        "after you clear them."
    )


def _snapmagic_account_issue(page) -> str:
    """Detect account states that make format buttons redirect instead of download."""
    try:
        body = (page.inner_text("body") or "").casefold()
    except Exception:  # noqa: BLE001 - absence of readable evidence is not an account verdict
        return ""
    if (
        "verify your email to download" in body
        or "email verification is required to download" in body
    ):
        return (
            "SnapMagic requires this account's email to be verified before CAD downloads can run."
        )
    return ""


def _is_global_blockage(message: str) -> bool:
    """True for provider/account state that will affect the next MPN exactly the same way."""
    text = (message or "").casefold()
    return any(
        marker in text
        for marker in (
            "confirm you are human",
            "download button is not on this page",
            "email to be verified",
            "requires a signed-in, verified account",
            "sign in to ultra librarian",
        )
    )
