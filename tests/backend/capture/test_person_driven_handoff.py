"""A person-driven provider page opens in the PERSON'S OWN browser, with no automation attached.

WHY THIS EXISTS
DigiKey sits behind Cloudflare. Stockroom's person-driven capture used to open the provider page in
a Playwright-controlled Camoufox session, so `navigator.webdriver`, a CDP endpoint, and automation
launch flags were all present while a PERSON did the clicking - and Cloudflare put the owner in an
endless verification loop. The fix is not to disguise the automation; it is to REMOVE it. On a
person-driven route Stockroom now hands the validated URL to the operating system's default browser
and never constructs a Playwright session at all.

WHAT THAT COSTS, AND WHAT REPLACES IT
There is no task-bound `save_as` in a browser Stockroom does not own, so the person's Downloads
directory is snapshotted BEFORE the handoff and only entries that appear afterwards are eligible.
The retired pre-rewrite implementation was deleted precisely because a Downloads watcher "could not
bind a downloaded file reliably to the task that requested it" (capture/browser.py, top of file), so
every adoption here is EXPLICIT: the original is copied and never moved, and each adoption is
appended to a durable ledger that names the original path, the staged path, and the exact part.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockroom.capture import guided
from stockroom.capture.browser import ProviderHudSpec
from stockroom.capture.download_broker import DownloadBroker, DownloadTask
from stockroom.capture.handoff import (
    TRANSPORT_DEFAULT_BROWSER,
    TRANSPORT_PLAYWRIGHT,
    DefaultBrowserCapture,
    DownloadsHandoff,
    HandoffError,
    handoff_guidance,
    select_transport,
    validated_provider_url,
)
from stockroom.capture.trace import reset_for_tests
from stockroom.capture.vendors import get_adapter

_DIGIKEY_URL = "https://www.digikey.com/en/models/1234567"


class _Clock:
    """A monotonic clock the test advances explicitly, so no test ever really sleeps."""

    def __init__(self) -> None:
        self.now = 1000.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += float(seconds)


class _OpenRecorder:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def __call__(self, url: str) -> None:
        self.opened.append(url)


def _broker(tmp_path: Path) -> DownloadBroker:
    staging = tmp_path / "Staging"
    staging.mkdir(parents=True, exist_ok=True)
    return DownloadBroker(
        DownloadTask(
            task_id="part-1",
            manufacturer_key="Acme",
            mpn_canonical="ABC-1",
            staging_root=staging,
            surface_key="digikey",
            evidence_provider_key="digikey-ultralibrarian",
        )
    )


def _hud() -> ProviderHudSpec:
    return ProviderHudSpec(
        provider_label="DigiKey · Ultra Librarian",
        author_route="Ultra Librarian",
        manufacturer="Acme",
        mpn="ABC-1",
        required_file_labels=("KiCad symbol and footprint", "STEP model"),
    )


def _capture(tmp_path: Path, downloads: Path, clock: _Clock, opener, **kwargs):
    transport = DefaultBrowserCapture(
        provider_key="digikey",
        downloads_dir=downloads,
        open_url=opener,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        stable_seconds=1.0,
        **kwargs,
    )
    return transport


# --- 1. transport selection is capability data, never a string sniff --------------------------


def test_a_person_driven_route_selects_the_de_automated_transport():
    capability = get_adapter("digikey").capability

    choice = select_transport(capability, person_driven=True)

    assert choice.name == TRANSPORT_DEFAULT_BROWSER
    assert "user_driven" in choice.why


def test_an_authorized_automated_route_keeps_the_playwright_transport():
    capability = get_adapter("ultralibrarian").capability

    choice = select_transport(capability, person_driven=True)

    assert choice.name == TRANSPORT_PLAYWRIGHT
    assert "machine_allowed" in choice.why


def test_the_operator_authorized_lane_still_drives_the_page_with_playwright():
    """SnapMagic is `user_driven` but `operator_automation` is True: when Stockroom itself operates
    the export controls it still needs a page it owns."""

    capability = get_adapter("snapmagic").capability

    choice = select_transport(capability, person_driven=False)

    assert choice.name == TRANSPORT_PLAYWRIGHT


def test_the_guided_source_opens_no_playwright_session_for_a_person_driven_route(tmp_path):
    class _Exploded:
        def __init__(self, *args, **kwargs):
            raise AssertionError("a person-driven route must never construct Playwright")

    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "dl",
        user_driven=True,
    )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(guided, "PlaywrightCaptureBrowser", _Exploded)
        session = source._ensure_session()

    assert isinstance(session.browser, DefaultBrowserCapture)
    assert session.page is None
    assert session.browser.owns_window is False


def test_the_guided_source_still_builds_playwright_for_the_authorized_route(tmp_path):
    built: list[dict] = []

    class _Fake:
        def __init__(self, **kwargs):
            built.append(kwargs)

        def session(self):
            from contextlib import nullcontext

            return nullcontext(object())

    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="ultralibrarian",
        download_root=tmp_path / "dl",
        user_driven=False,
    )

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(guided, "PlaywrightCaptureBrowser", _Fake)
        session = source._ensure_session()

    assert len(built) == 1
    assert not isinstance(session.browser, DefaultBrowserCapture)


def test_the_transport_choice_is_traced(tmp_path, monkeypatch):
    log = tmp_path / "capture.log"
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG", str(log))
    reset_for_tests()

    class _Exploded:
        def __init__(self, *args, **kwargs):
            raise AssertionError("no Playwright here")

    source = guided.GuidedCaptureSource(
        lambda: None,
        vendor="digikey",
        download_root=tmp_path / "dl",
        user_driven=True,
    )
    monkeypatch.setattr(guided, "PlaywrightCaptureBrowser", _Exploded)
    source._ensure_session()
    reset_for_tests()

    written = log.read_text(encoding="utf-8")
    lines = [line for line in written.splitlines() if "capture.transport" in line]
    assert lines, written
    assert TRANSPORT_DEFAULT_BROWSER in lines[0]
    assert "why=" in lines[0]


# --- 2. the origin gate runs BEFORE the operating system handler -------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://www.digikey.com/en/models/1234567",
        "file:///C:/Windows/System32/calc.exe",
        "javascript:alert(1)",
        "https://www.digikey.com.evil.test/en/models/1",
        "https://example.test/en/models/1",
        "https://user:pass@www.digikey.com/en/models/1",
        "",
    ],
)
def test_a_non_https_or_foreign_origin_url_never_reaches_the_operating_system(url):
    with pytest.raises(HandoffError):
        validated_provider_url("digikey", url)


def test_the_validated_provider_url_is_returned_unchanged():
    assert validated_provider_url("digikey", _DIGIKEY_URL) == _DIGIKEY_URL


def test_the_capture_refuses_before_opening_anything(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    with pytest.raises(HandoffError):
        transport.capture_user_downloads(
            "https://example.test/en/models/1",
            _broker(tmp_path),
            hud=_hud(),
            timeout_s=5.0,
        )

    assert opener.opened == []


def test_a_valid_url_is_handed_to_the_operating_system_exactly_once(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        timeout_s=3.0,
        poll_interval_s=0.5,
    )

    assert opener.opened == [_DIGIKEY_URL]
    assert result.status == "timed_out"


# --- 3. the Downloads snapshot never sweeps what was already there -----------------------------


def test_the_snapshot_excludes_every_pre_existing_download(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "old-package.zip").write_bytes(b"already here")
    clock = _Clock()
    watch = DownloadsHandoff(downloads, stable_seconds=1.0, monotonic=clock.monotonic)
    watch.snapshot()

    clock.sleep(5.0)

    assert watch.collect() == ()


def test_only_a_file_that_appears_after_the_snapshot_is_a_candidate(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "old-package.zip").write_bytes(b"already here")
    clock = _Clock()
    watch = DownloadsHandoff(downloads, stable_seconds=1.0, monotonic=clock.monotonic)
    watch.snapshot()

    (downloads / "new-package.zip").write_bytes(b"fresh bytes")
    assert watch.collect() == ()
    clock.sleep(2.0)
    landed = watch.collect()

    assert [item.path.name for item in landed] == ["new-package.zip"]
    assert watch.collect() == (), "a landed file is reported exactly once"


def test_a_partially_written_file_is_not_collected_until_it_is_stable(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    watch = DownloadsHandoff(downloads, stable_seconds=1.0, monotonic=clock.monotonic)
    watch.snapshot()

    partial = downloads / "package.zip.crdownload"
    partial.write_bytes(b"half")
    clock.sleep(5.0)
    assert watch.collect() == (), "a .crdownload suffix is never a landed file"

    finished = downloads / "package.zip"
    finished.write_bytes(b"half")
    assert watch.collect() == (), "the first sighting only starts the stability clock"

    finished.write_bytes(b"half and then the rest")
    clock.sleep(2.0)
    assert watch.collect() == (), "a file that grew between polls restarts the stability clock"

    clock.sleep(2.0)
    assert [item.path.name for item in watch.collect()] == ["package.zip"]


def test_an_empty_or_partial_suffixed_file_is_never_a_candidate(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    watch = DownloadsHandoff(downloads, stable_seconds=1.0, monotonic=clock.monotonic)
    watch.snapshot()

    (downloads / "empty.zip").write_bytes(b"")
    for suffix in (".part", ".partial", ".tmp", ".download", ".opdownload"):
        (downloads / f"package{suffix}").write_bytes(b"bytes")
    (downloads / "a-directory").mkdir()
    clock.sleep(10.0)

    assert watch.collect() == ()


# --- 4. adoption is explicit and reversible ----------------------------------------------------


def test_an_adopted_file_is_copied_never_moved_and_written_to_a_reversible_ledger(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)
    broker = _broker(tmp_path)

    original = downloads / "acme-abc-1.zip"

    def open_and_download(url: str) -> None:
        opener(url)
        original.write_bytes(b"provider package bytes")

    transport._open_url = open_and_download
    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        broker,
        hud=_hud(),
        timeout_s=30.0,
        poll_interval_s=0.5,
    )

    assert [receipt.suggested_name for receipt in result.files] == ["acme-abc-1.zip"]
    assert original.exists(), "the person's own download is never moved out of Downloads"
    assert original.read_bytes() == b"provider package bytes"
    staged = result.files[0].path
    assert staged.exists() and staged != original
    assert result.files[0].transport == TRANSPORT_DEFAULT_BROWSER
    assert result.files[0].evidence_provider_key == "digikey-ultralibrarian"

    ledger = broker.task.staging_root / "handoff-adoptions.jsonl"
    entries = [json.loads(line) for line in ledger.read_text(encoding="utf-8").splitlines() if line]
    assert len(entries) == 1
    assert entries[0]["task_id"] == "part-1"
    assert entries[0]["manufacturer"] == "Acme"
    assert entries[0]["mpn"] == "ABC-1"
    assert entries[0]["route"] == "digikey-ultralibrarian"
    assert entries[0]["original_path"] == str(original)
    assert entries[0]["staged_path"] == str(staged)
    assert entries[0]["sha256"].startswith("sha256:")


def test_a_pre_existing_download_is_never_adopted(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    (downloads / "someone-elses-holiday-photos.zip").write_bytes(b"not for stockroom")
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        timeout_s=6.0,
        poll_interval_s=0.5,
    )

    assert result.files == ()
    assert result.status == "timed_out"


# --- 5. termination, in a window Stockroom does not own ----------------------------------------


def test_the_capture_times_out_cleanly_without_touching_the_window(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        timeout_s=4.0,
        poll_interval_s=0.5,
    )

    assert result.status == "timed_out"
    assert result.files == ()
    assert transport.owns_window is False
    assert transport.closed_windows == 0
    transport.close()
    assert transport.closed_windows == 0


def test_the_capture_cancels_before_it_hands_anything_to_the_operating_system(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        should_cancel=lambda: True,
        timeout_s=10.0,
    )

    assert result.status == "cancelled"
    assert opener.opened == []


def test_the_person_finishing_ends_the_capture_and_keeps_what_landed(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)
    finished: list[bool] = [False]

    def open_and_download(url: str) -> None:
        opener(url)
        (downloads / "acme-abc-1.zip").write_bytes(b"provider package bytes")
        finished[0] = True

    transport._open_url = open_and_download
    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        should_finish=lambda: finished[0],
        timeout_s=60.0,
        poll_interval_s=0.5,
    )

    assert result.status == "completed"
    assert len(result.files) == 1


def test_the_capture_ends_itself_once_every_required_file_has_landed(tmp_path):
    """The person who collected everything should not have to say so.

    Before this, a person-driven route ended only on their Finish Route, on ~25 s of quiet after a
    file landed, or on the 600 s timeout - so clearing one worklist row cost a second Stockroom
    click for something Stockroom could already see. The rule is the Playwright path's: the route
    declares how many files it needs, and once that many have settled and the directory has been
    still for a moment, capture completes on its own.
    """

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    def open_and_download(url: str) -> None:
        opener(url)
        # Two files for the two labels `_hud()` declares.
        (downloads / "acme-abc-1-kicad.zip").write_bytes(b"kicad package bytes")
        (downloads / "acme-abc-1-step.step").write_bytes(b"step model bytes")

    transport._open_url = open_and_download
    started = clock.now
    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        timeout_s=600.0,
        poll_interval_s=0.5,
    )

    assert result.status == "completed"
    assert len(result.files) == 2
    # Well inside the 25 s idle backstop: the count is what ended it, not the wait.
    assert clock.now - started < 25.0


def test_a_route_that_ships_one_archive_still_waits_out_the_idle_backstop(tmp_path):
    """Fewer files than labels is the NORMAL shape for a provider that packs formats into one zip.

    This transport adopts files out of Downloads and cannot tell which format any of them holds
    until ingest classifies it, so an incomplete count must never finish early - the person may
    still be fetching the format that is missing. The long idle gap remains the only automatic
    ending in that case.
    """

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    def open_and_download(url: str) -> None:
        opener(url)
        (downloads / "acme-abc-1-everything.zip").write_bytes(b"one archive, both formats")

    transport._open_url = open_and_download
    started = clock.now
    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        timeout_s=600.0,
        poll_interval_s=0.5,
    )

    assert result.status == "completed"
    assert len(result.files) == 1
    assert clock.now - started >= 25.0, "one file against two labels must not finish early"


def test_a_download_still_being_written_holds_the_completeness_rule_open(tmp_path):
    """Both required files have landed, but the browser is still writing a third.

    Finishing here is exactly the failure that matters: the person is mid-fetch and the run would
    walk away from the file they are collecting. A `.crdownload`-class name that is not in the
    baseline is a download in progress, so the count rule waits and the backstop takes over.
    """

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    def open_and_download(url: str) -> None:
        opener(url)
        (downloads / "acme-abc-1-kicad.zip").write_bytes(b"kicad package bytes")
        (downloads / "acme-abc-1-step.step").write_bytes(b"step model bytes")
        (downloads / "acme-abc-1-altium.zip.crdownload").write_bytes(b"still arriving")

    transport._open_url = open_and_download
    started = clock.now
    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        timeout_s=600.0,
        poll_interval_s=0.5,
    )

    assert result.status == "completed"
    assert len(result.files) == 2
    assert clock.now - started >= 25.0, "a part-written download must hold the count rule open"


def test_a_route_with_no_declared_files_never_finishes_on_a_count(tmp_path):
    """No HUD means nothing to be complete against, so the count rule is switched off entirely."""

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    def open_and_download(url: str) -> None:
        opener(url)
        (downloads / "acme-abc-1.zip").write_bytes(b"provider package bytes")

    transport._open_url = open_and_download
    started = clock.now
    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        timeout_s=600.0,
        poll_interval_s=0.5,
    )

    assert result.status == "completed"
    assert clock.now - started >= 25.0


def test_finish_route_still_ends_a_complete_capture_before_the_quiet_period(tmp_path):
    """The completeness rule removes the NEED to press Finish Route, never the ability.

    Every required file has landed here, so the count rule would end the capture on its own after
    its quiet period - but the person's own signal is still answered first and immediately.
    """

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)
    finished: list[bool] = [False]

    def open_and_download(url: str) -> None:
        opener(url)
        (downloads / "acme-abc-1-kicad.zip").write_bytes(b"kicad package bytes")
        (downloads / "acme-abc-1-step.step").write_bytes(b"step model bytes")
        finished[0] = True

    transport._open_url = open_and_download
    started = clock.now
    result = transport.capture_user_downloads(
        _DIGIKEY_URL,
        _broker(tmp_path),
        hud=_hud(),
        should_finish=lambda: finished[0],
        timeout_s=600.0,
        poll_interval_s=0.5,
    )

    assert result.status == "completed"
    assert len(result.files) == 2
    assert clock.now - started < 2.0, "the person's own Finish Route is answered immediately"


def test_the_hud_identity_must_match_the_bound_download_task(tmp_path):
    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)
    wrong = ProviderHudSpec(
        provider_label="DigiKey · Ultra Librarian",
        author_route="Ultra Librarian",
        manufacturer="Other",
        mpn="ZZZ-9",
        required_file_labels=("KiCad symbol and footprint",),
    )

    with pytest.raises(HandoffError):
        transport.capture_user_downloads(
            _DIGIKEY_URL,
            _broker(tmp_path),
            hud=wrong,
            timeout_s=5.0,
        )

    assert opener.opened == []


# --- 6. the guidance the person needs, in Stockroom's own UI -----------------------------------


def test_the_guidance_carries_the_ordered_checklist_and_the_provider_instruction():
    guidance = handoff_guidance(
        "digikey",
        needs=["kicad_symbol", "kicad_footprint", "kicad_model", "altium_symbol"],
        manufacturer="Acme",
        mpn="ABC-1",
    )

    assert guidance["transport"] == TRANSPORT_DEFAULT_BROWSER
    assert guidance["provider_label"] == get_adapter("digikey").capability.label
    assert guidance["manufacturer"] == "Acme"
    assert guidance["mpn"] == "ABC-1"
    assert guidance["opens_in"] == "your own default browser"
    assert guidance["downloads_dir"]
    routes = guidance["routes"]
    assert routes, guidance
    for route in routes:
        assert route["label"]
        assert route["author_route"]
        assert route["required_files"], route
        assert all(
            isinstance(label, str) and label.strip() for label in route["required_files"]
        ), route
    assert any(route["instruction"] for route in routes), guidance


def test_the_guidance_for_the_authorized_route_names_the_playwright_transport():
    guidance = handoff_guidance("ultralibrarian", needs=["kicad_symbol"])

    assert guidance["transport"] == TRANSPORT_PLAYWRIGHT
    assert guidance["opens_in"] == "a Stockroom-controlled window"


def test_the_guidance_refuses_an_unknown_provider():
    assert handoff_guidance("nope", needs=["kicad_symbol"]) is None


# --- 7. the constraints this transport exists under, made mechanical ---------------------------


def test_only_one_person_driven_capture_window_can_be_active(tmp_path):
    """The de-automated transport takes the SAME process-wide lock the Playwright one takes.

    Two concurrent watchers over one Downloads directory is exactly how the retired implementation
    attributed a file to the wrong task.
    """

    from stockroom.capture.browser import CaptureBrowserError, exclusive_user_capture_window

    downloads = tmp_path / "Downloads"
    downloads.mkdir()
    clock = _Clock()
    opener = _OpenRecorder()
    transport = _capture(tmp_path, downloads, clock, opener)

    with exclusive_user_capture_window():
        with pytest.raises(CaptureBrowserError):
            transport.capture_user_downloads(
                _DIGIKEY_URL,
                _broker(tmp_path),
                hud=_hud(),
                timeout_s=5.0,
            )

    assert opener.opened == []


def test_the_de_automated_transport_carries_no_fingerprint_or_challenge_handling():
    """This is de-automation, NOT evasion.

    The session must genuinely be a person's browser, so nothing here may exist whose value depends
    on a bot check being deceived. A stealth patch, a spoofed navigator field, or CAPTCHA handling
    appearing in this module would mean the de-automation had quietly become disguise again.
    """

    from stockroom.capture import handoff

    source = Path(handoff.__file__).read_text(encoding="utf-8").casefold()
    body = source.split('"""', 2)[2] if source.count('"""') >= 2 else source
    forbidden = (
        "navigator.",
        "webdriver",
        "user_agent",
        "useragent",
        "canvas",
        "webgl",
        "turnstile",
        "recaptcha",
        "hcaptcha",
        "add_init_script",
        "stealth",
        "camoufox",
        "impersonate",
    )
    found = [marker for marker in forbidden if marker in body]

    assert found == [], f"the de-automated transport grew an evasion surface: {found}"
