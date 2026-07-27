"""The capture BROWSER: one cross-platform way to open a vendor page and catch its download.

Owner, 2026-07-27: *"literally make the best environment for us ... something that works on both
windows and linux so its not hard for u to test it"*.

WHY THIS EXISTS (the problem it removes)
Guided capture used to live entirely inside the pywebview WebView2 window, and that had three
costs, all of them measured rather than supposed:

1. **It is Windows-only, so the whole flow was untestable from Linux.** The frontend's only route
   in is `window.pywebview.api.open_cad_download` (`lib/capture.tsx`), which does not exist off
   Windows, so on Linux the flow silently degrades to "pick the files yourself". That is exactly
   why an agent could verify the URL layer and the selector layer but never the layer the owner
   actually sees.
2. **pywebview exposes NO public download-intercept API** (verified and recorded at
   `host/window.py:201`), so tier 1 monkeypatched pywebview's private WinForms/WebView2 internals
   and tier 2 polled `~/Downloads`. That coupling is logged as risk R3 in the guided-capture spec.
3. **CDP cannot rescue it**: `Browser.setDownloadBehavior` returns invalid-argument (0x80070057)
   in WebView2, so the one API that would have made downloads observable there does not work.

Playwright, which this repo ALREADY bundles for the scrape engine (`pyproject.toml`), has a
public, documented download API (`expect_download` / `save_as`), runs identically on Windows and
Linux, and gives real waiting primitives instead of sleeps. So the capture browser is Playwright,
and the vendor logic moves OUT of injected JS in `host/` into ordinary Python that a test can drive
anywhere.

WHAT STAYS AS IT WAS
The APP SHELL is still pywebview/WebView2 on Windows: that decision (spec 2026-07-12 section 3) is
about hosting our own frontend, where Python-as-host and native drag/drop paths genuinely win, and
nothing here disturbs it. This module is only about the SECOND window - the vendor page.

A NOTE ON THE PERSISTENT PROFILE, which is not a free choice
Vendor logins must survive between parts, which means a persistent user-data dir. But Playwright
has open reports of `download.save_as()` raising "Download canceled" under
`launch_persistent_context` (microsoft/playwright#34989), while plain `launch()` is unaffected. So
persistence is OPT-IN here, the two paths are separate, and `test_a_download_survives_a_persistent
_profile` exists to catch that regression on the version we actually ship rather than trusting the
issue tracker.
"""

from __future__ import annotations

import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path


class CaptureBrowserError(RuntimeError):
    """Something the caller must fix, phrased so the message names the actual blocker."""


@dataclass(frozen=True)
class CapturedFile:
    """One file the vendor actually delivered, already on disk at `path`.

    `suggested_name` is the vendor's own filename, kept because it is evidence (and because the
    classifier's zip-by-content path exists precisely for downloads that arrive without one).
    """

    path: Path
    suggested_name: str
    url: str


class PlaywrightCaptureBrowser:
    """A real, visible browser the person can work in, whose downloads we observe.

    Not headless by default: this is a GUIDED capture, so the human signs in, clears a Cloudflare
    check, and watches what happens. Headless exists for the tests.
    """

    def __init__(
        self,
        *,
        download_dir: Path,
        profile_dir: Path | None = None,
        headless: bool = False,
        browser: str = "chromium",
    ) -> None:
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.headless = headless
        self.browser_name = browser
        self._captured: list[CapturedFile] = []

    @property
    def captured(self) -> list[CapturedFile]:
        return list(self._captured)

    @contextmanager
    def session(self):
        """Open a browser, yield a page, and always tear it down.

        Yields the Playwright `Page`. Downloads that land during the session are saved into
        `download_dir` and recorded on `self.captured` - saved EAGERLY, because Playwright deletes
        a context's downloads when the context closes, so a file only "arrived" once it is copied
        out of the temp area.
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise CaptureBrowserError(
                "playwright is not installed; it is a declared dependency, run `uv sync`"
            ) from exc

        with sync_playwright() as pw:
            engine = getattr(pw, self.browser_name, None)
            if engine is None:
                raise CaptureBrowserError(f"unknown browser engine {self.browser_name!r}")
            context = None
            browser = None
            try:
                try:
                    if self.profile_dir is not None:
                        self.profile_dir.mkdir(parents=True, exist_ok=True)
                        context = engine.launch_persistent_context(
                            str(self.profile_dir),
                            headless=self.headless,
                            accept_downloads=True,
                        )
                    else:
                        browser = engine.launch(headless=self.headless)
                        context = browser.new_context(accept_downloads=True)
                except Exception as exc:  # noqa: BLE001 - turn a launch failure into a real message
                    raise CaptureBrowserError(
                        f"could not launch {self.browser_name}: {exc}. If the browser is missing, "
                        "run `uv run python -m playwright install chromium`."
                    ) from exc

                context.on("page", self._wire_downloads)
                page = context.pages[0] if context.pages else context.new_page()
                self._wire_downloads(page)
                yield page
            finally:
                for closable in (context, browser):
                    if closable is not None:
                        try:
                            closable.close()
                        except Exception:  # noqa: BLE001 - teardown is best effort
                            pass

    def _wire_downloads(self, page) -> None:
        page.on("download", self._on_download)

    def _on_download(self, download) -> None:
        """Save every download the moment it lands, and record where it went.

        Saved eagerly and unconditionally: Playwright removes a context's downloads on close, and
        a capture that reported a file it can no longer read is the exact "said downloaded before
        the file landed" failure the owner called out.
        """
        name = download.suggested_filename or "cad-download"
        dest = _unique(self.download_dir, name)
        try:
            download.save_as(str(dest))
        except Exception as exc:  # noqa: BLE001 - a cancelled/failed download must not kill capture
            failure = getattr(download, "failure", None)
            reason = failure() if callable(failure) else exc
            raise CaptureBrowserError(
                f"the vendor download did not complete ({reason}); nothing was saved for "
                f"{name!r}"
            ) from exc
        self._captured.append(
            CapturedFile(path=dest, suggested_name=name, url=download.url or "")
        )


def _unique(directory: Path, name: str) -> Path:
    """A collision-free path inside `directory`.

    Vendors name every export the same (`<MPN>.zip`), so a second format's download would
    otherwise overwrite the first while it is still being read - a failure already observed live
    on 2026-07-23 with the WebView2 path, and worth carrying over rather than re-learning.
    """
    stem = Path(name).stem or "cad-download"
    suffix = Path(name).suffix
    dest = directory / f"{stem}{suffix}"
    counter = 2
    while dest.exists():
        dest = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return dest


def chromium_unavailable_reason() -> str | None:
    """None when a browser really can launch, else the REAL reason it cannot.

    Returns the reason rather than a bool because the first version of this returned False for
    every cause and its callers all printed "chromium is not installed". That was FALSE: the
    actual failure was `ENOENT ... mkdtemp '/dev/shm/srtest/...'` - a TMPDIR that did not exist -
    and the invented explanation sent the diagnosis in the wrong direction entirely. A check that
    reports a cause it did not establish is worse than one that reports nothing.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return f"playwright is not importable ({exc})"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
        return None
    except Exception as exc:  # noqa: BLE001 - report whatever actually went wrong
        detail = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else type(exc).__name__
        return f"chromium could not launch: {detail}"


def chromium_available() -> bool:
    """Convenience wrapper. Prefer `chromium_unavailable_reason()` where a message is shown."""
    return chromium_unavailable_reason() is None


def default_profile_dir(app_data: Path) -> Path:
    """Where vendor logins persist, per machine.

    PER-MACHINE ON PURPOSE, and it is the allowed kind: it holds credentials/session cookies only,
    never anything that changes what the library renders, so it cannot break device parity the way
    a per-machine enrich cache does.
    """
    return Path(app_data) / "capture-profile"


def clear_profile(profile_dir: Path) -> bool:
    """Delete the persisted vendor sessions. True when something was removed."""
    profile_dir = Path(profile_dir)
    if not profile_dir.exists():
        return False
    shutil.rmtree(profile_dir, ignore_errors=True)
    return not profile_dir.exists()
