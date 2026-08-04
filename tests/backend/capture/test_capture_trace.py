"""The capture trace: it is written, it names the signal, it leaks nothing, and it cannot fail a run.

These four properties are the whole reason this module exists, so each is asserted directly rather
than inferred from a passing capture.

Context, 2026-07-31: `%APPDATA%\\Stockroom\\capture.log` had not been written since 2026-07-26
because the only handler that fed it lived in the deleted CAD host, and the capture package that
replaced it shipped with no logging at all. An automatic run then failed with "Automatic lookup
finished without a complete CAD package" and the real cause - a signed-out Ultra Librarian - had to
be guessed. A trace that is not written, or that cannot distinguish a real gate from a false
positive, would leave exactly that hole open.
"""

from __future__ import annotations

import logging

import pytest

from stockroom.capture import guided
from stockroom.capture import trace as capture_trace
from stockroom.capture.vendors import UltraLibrarianAdapter


@pytest.fixture
def trace_file(tmp_path, monkeypatch):
    """Point the trace at a private file and give the test its lines back."""

    path = tmp_path / "capture.log"
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG", str(path))
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG_LEVEL", "DEBUG")
    capture_trace.reset_for_tests()
    try:
        yield path
    finally:
        capture_trace.reset_for_tests()


def _lines(path) -> list[str]:
    for handler in logging.getLogger(capture_trace.LOGGER_NAME).handlers:
        handler.flush()
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


def _find(path, event: str) -> str:
    matches = [line for line in _lines(path) if f" {event} " in line or line.endswith(f" {event}")]
    assert matches, f"no {event!r} line in:\n" + "\n".join(_lines(path))
    return matches[-1]


# -- it is actually written ----------------------------------------------------------------


def test_the_trace_path_is_the_config_directory_by_default(monkeypatch, tmp_path):
    """The owner already looks in the config dir; the log must keep landing there."""

    monkeypatch.delenv("STOCKROOM_CAPTURE_LOG", raising=False)
    monkeypatch.setenv("STOCKROOM_CONFIG_DIR", str(tmp_path))
    assert capture_trace.capture_log_path() == tmp_path / "capture.log"


def test_every_trace_call_appends_to_one_discoverable_file(trace_file):
    capture_trace.trace("capture.run.start", mode="automatic")
    capture_trace.trace("capture.run.finish", mode="automatic")

    lines = _lines(trace_file)
    assert len(lines) == 2
    assert "capture.run.start mode=automatic" in lines[0]
    # Timestamp and level, so a line can be placed in a run without reading code.
    assert " INFO " in lines[0]


def test_a_second_install_does_not_double_every_line(trace_file):
    capture_trace.install_capture_log()
    capture_trace.install_capture_log()
    capture_trace.trace("capture.run.start")

    assert len(_lines(trace_file)) == 1


def test_a_moved_destination_reinstalls_instead_of_logging_into_thin_air(tmp_path, monkeypatch):
    """A handler frozen at first use is how a log goes silently dead - which is what happened.

    `capture.log` stopped being written on 2026-07-26 and nothing said so. Re-deriving the
    destination means a process whose config directory moves keeps writing somewhere real.
    """

    first = tmp_path / "one" / "capture.log"
    second = tmp_path / "two" / "capture.log"
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG", str(first))
    capture_trace.reset_for_tests()
    try:
        capture_trace.trace("capture.run.start", where="first")
        monkeypatch.setenv("STOCKROOM_CAPTURE_LOG", str(second))
        capture_trace.trace("capture.run.start", where="second")

        assert "where=first" in "\n".join(_lines(first))
        assert "where=second" in "\n".join(_lines(second))
        assert "where=second" not in "\n".join(_lines(first))
    finally:
        capture_trace.reset_for_tests()


def test_debug_detail_is_available_without_drowning_the_default_level(tmp_path, monkeypatch):
    path = tmp_path / "capture.log"
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG", str(path))
    monkeypatch.delenv("STOCKROOM_CAPTURE_LOG_LEVEL", raising=False)
    capture_trace.reset_for_tests()
    try:
        capture_trace.trace("capture.decision")
        capture_trace.trace_debug("capture.step")
        lines = _lines(path)
    finally:
        capture_trace.reset_for_tests()

    assert any("capture.decision" in line for line in lines)
    assert not any("capture.step" in line for line in lines)


# -- a clearance decision names the signal that fired ---------------------------------------


# -- nothing credential-bearing is ever written ---------------------------------------------


@pytest.mark.parametrize(
    "field",
    [
        "password",
        "ul_password",
        "provider_token",
        "session_cookie",
        "credentials",
        "api_key",
        "authorization",
        "username",
        "session_id",
        "otp",
    ],
)
def test_a_credential_bearing_field_name_never_carries_its_value(trace_file, field):
    """Guarded on the NAME, so a future call site cannot leak by passing the wrong thing."""

    capture_trace.trace("capture.signin.attempted", **{field: "hunter2-do-not-log"})

    line = _find(trace_file, "capture.signin.attempted")
    assert f"{field}=[redacted]" in line
    assert "hunter2" not in line


def test_a_secret_that_arrives_inside_an_innocent_value_is_still_scrubbed(trace_file):
    capture_trace.trace(
        "capture.route.failed",
        why="provider rejected the request (password=hunter2, token: abc123)",
    )

    line = _find(trace_file, "capture.route.failed")
    assert "hunter2" not in line
    assert "abc123" not in line
    assert "password=[redacted]" in line


def test_a_url_value_loses_its_query_wherever_it_appears(trace_file):
    capture_trace.trace(
        "capture.part.url",
        url=capture_trace.url_note(
            "https://app.ultralibrarian.com/search?queryText=ABC-1&sessionId=zzz"
        ),
        why="resolver returned https://sso.example.test/login?ticket=SECRET",
    )

    line = _find(trace_file, "capture.part.url")
    assert "zzz" not in line
    assert "SECRET" not in line
    assert "app.ultralibrarian.com/search" in line
    assert "sso.example.test/login" in line


def test_a_long_provider_value_is_bounded_instead_of_dumping_the_page(trace_file):
    capture_trace.trace("capture.route.failed", why="x" * 5_000)

    line = _find(trace_file, "capture.route.failed")
    assert len(line) < 400


# -- a logging failure cannot break a capture -----------------------------------------------


def test_a_broken_logger_is_swallowed_by_every_entry_point(monkeypatch, trace_file):
    class Exploding:
        handlers: list = []

        def isEnabledFor(self, _level):  # noqa: N802 - logging's own spelling
            raise RuntimeError("logging backend is on fire")

        def log(self, *_args, **_kwargs):
            raise RuntimeError("logging backend is on fire")

    monkeypatch.setattr(capture_trace, "_log", Exploding())
    capture_trace.trace("capture.run.start", mode="automatic")
    capture_trace.trace_debug("capture.step")
    capture_trace.trace_warning("capture.route.failed", why="anything")


def test_an_unwritable_log_location_does_not_stop_installation_from_returning(
    monkeypatch,
    tmp_path,
):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("", encoding="utf-8")
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG", str(blocker / "nested" / "capture.log"))
    capture_trace.reset_for_tests()
    try:
        capture_trace.trace("capture.run.start")
    finally:
        capture_trace.reset_for_tests()


def test_a_capture_still_completes_when_the_logging_backend_fails(monkeypatch, tmp_path):
    """The property that matters: diagnostics are additive, never load-bearing.

    The failure is injected where a real one occurs - inside the logging backend, behind every
    `trace*` entry point - rather than at the call sites, so this proves the guard rather than
    the test's own patching.
    """

    class Exploding:
        handlers: list = []

        def isEnabledFor(self, _level):  # noqa: N802 - logging's own spelling
            raise OSError("no space left on device")

        def log(self, *_args, **_kwargs):
            raise OSError("no space left on device")

    monkeypatch.setattr(capture_trace, "_log", Exploding())
    monkeypatch.setattr(
        capture_trace,
        "install_capture_log",
        lambda: (_ for _ in ()).throw(OSError("no space left on device")),
    )

    class Adapter:
        capability = UltraLibrarianAdapter.capability

        def resolve_url(self, _mpn):
            return ""

    class Record:
        id = "abc-1"
        mpn = "ABC-1"
        manufacturer = "Acme"
        category = "ic"
        passive = False

        def assets_for(self, _tool):
            raise AssertionError("this part never reaches attachment")

    monkeypatch.setattr(guided, "get_adapter", lambda _key: Adapter())
    monkeypatch.setattr(guided, "capture_needs", lambda _record: [])

    source = guided.GuidedCaptureSource(
        (lambda: None),
        vendor="ultralibrarian",
        download_root=tmp_path / "dl",
    )
    outcome = source.supply(Record())

    assert outcome.provider_outcomes
    assert "needs no captured files" in outcome.skipped


# -- the specific reason reaches the outcome the UI renders ---------------------------------


def test_a_challenge_is_reported_as_needing_a_person_not_as_a_blocked_route():
    """The badge must match the fact. A CAPTCHA is one click for the owner, not a Stockroom fault."""

    from stockroom.capture.complete import SourceOutcome
    from stockroom.capture.guided import _with_route_outcome

    outcome = _with_route_outcome(
        SourceOutcome(
            error=(
                "Ultra Librarian is asking you to confirm you are human. Clear it once in this "
                "window; the provider-specific browser profile remembers the session."
            ),
            blocked=True,
        ),
        provider_key="ultralibrarian",
        author_key="ultralibrarian",
        label="Ultra Librarian",
    )

    assert outcome.provider_outcomes[0].status == "requires-human"
    assert "confirm you are human" in outcome.provider_outcomes[0].reason


def test_an_absent_provider_export_row_survives_into_the_rejection_reason():
    """"Missing native Altium symbol/footprint" alone blames Stockroom for a provider's gap."""

    from stockroom.capture.guided import _provider_note_suffix

    suffix = _provider_note_suffix(
        "Requested kicad and model, but could not select altium on this page. Ultra Librarian "
        "does not offer Altium Designer (Native) for this exact part."
    )

    assert suffix.startswith("; ")
    assert "does not offer Altium Designer (Native)" in suffix
    assert _provider_note_suffix("") == ""
    assert len(_provider_note_suffix("x" * 5_000)) < 240


# -- routing says why a provider is in or out -----------------------------------------------


