"""Installing the generated .DbLib into Altium, and refusing to call a no-op an install."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from stockroom.altium.install import (
    install_library,
    is_installed,
    parse_installed,
    render_install_script,
)

_WIN = "C:\\lib\\Stockroom\\altium\\Stockroom.DbLib"


def _strip_comments(text: str) -> str:
    """DelphiScript `{ ... }` comments removed, so an assertion about the CODE never matches the
    prose explaining it."""
    return re.sub(r"\{.*?\}", "", text, flags=re.S)


# -- the generated script ------------------------------------------------------------------


def test_the_script_does_NOT_terminate_altium():
    """The load-bearing detail, and the reason every earlier scripted install silently did nothing.

    Altium writes its preferences on a clean shutdown. A script that calls
    `TerminateWithExitCode` discards the library list it just changed: measured 2026-07-26, every
    scripted install left the Installed list EMPTY while the identical action through the GUI
    survived a full restart. The driver's graceful stop is what makes it persist, so the script
    must end by writing its marker and returning.
    """
    text = render_install_script(dblib_win=_WIN, marker_win="C:\\w\\m.txt")
    # Strip DelphiScript `{...}` comments FIRST. The generated script explains this rule in a
    # comment, so a raw substring check convicts the very text that documents the fix - the same
    # own-comment trap the repo's gates have hit before.
    assert "TerminateWithExitCode" not in _strip_comments(text)
    assert "InstallLibrary" in text


def test_uninstall_uses_the_uninstall_api():
    text = render_install_script(dblib_win=_WIN, marker_win="C:\\w\\m.txt", uninstall=True)
    assert "UninstallLibrary" in text
    assert "ILM.InstallLibrary" not in text


def test_the_script_reports_the_list_before_AND_after():
    """A boolean is a claim; the two lists are the observation behind it."""
    text = render_install_script(dblib_win=_WIN, marker_win="C:\\w\\m.txt")
    assert "SR-Before" in text and "SR-After" in text


def test_a_path_with_an_apostrophe_cannot_end_the_delphi_literal_early():
    text = render_install_script(dblib_win="C:\\O'Brien\\S.DbLib", marker_win="C:\\w\\m.txt")
    assert "'C:\\O''Brien\\S.DbLib'" in text


# -- the log ------------------------------------------------------------------------------


def test_installed_lists_parse_in_index_order_not_line_order():
    log = "SR-After10=C:\\j.IntLib\nSR-After0=C:\\a.IntLib\nSR-After2=C:\\c.DbLib\nDONE\n"
    assert parse_installed(log, "After") == ("C:\\a.IntLib", "C:\\c.DbLib", "C:\\j.IntLib")


def test_a_library_matches_case_insensitively_and_ignores_a_trailing_separator():
    """Windows paths are case-insensitive, so a case difference is not a missing library. Getting
    this wrong would reinstall on every run and report `ok` forever without ever being idempotent."""
    assert is_installed(["c:\\LIB\\stockroom.dblib"], "C:\\lib\\Stockroom.DbLib")
    assert is_installed(["C:\\lib\\Stockroom.DbLib\\"], "C:\\lib\\Stockroom.DbLib")
    assert not is_installed(["C:\\lib\\Other.DbLib"], "C:\\lib\\Stockroom.DbLib")


# -- the result logic ----------------------------------------------------------------------


@dataclass
class _Outcome:
    status: str
    detail: str
    marker_text: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class _FakeHost:
    def to_windows_path(self, path: str) -> str:
        # Mimic wslpath: the tests pass a POSIX temp path and the script needs a Windows one.
        return "C:\\fake\\" + Path(path).name

    def windows_temp(self) -> Path:  # pragma: no cover - workdir is always passed
        raise AssertionError("the test always passes an explicit workdir")


class _FakeDriver:
    def __init__(self, outcome: _Outcome):
        self.host = _FakeHost()
        self._outcome = outcome
        self.runs = 0

    def run_script(self, **kwargs):
        self.runs += 1
        return self._outcome


def _dblib(tmp_path: Path) -> Path:
    p = tmp_path / "Stockroom.DbLib"
    p.write_text("[OutputDatabaseLinkFile]\n", encoding="utf-8")
    return p


def test_a_missing_library_is_reported_without_booting_altium(tmp_path):
    drv = _FakeDriver(_Outcome("ok", ""))
    res = install_library(tmp_path / "nope.DbLib", driver=drv, workdir=tmp_path)
    assert res.status == "not-found"
    assert drv.runs == 0, "a missing library must not cost an Altium boot or a license seat"


def test_altium_reporting_success_while_installing_NOTHING_is_not_ok(tmp_path):
    """The failure this whole module exists because of: the API returned, Altium exited, and the
    library list was unchanged. Trusting the absence of an error would have shipped that."""
    log = "SR-Before0=C:\\stock.IntLib\nSR-After0=C:\\stock.IntLib\nDONE\n"
    drv = _FakeDriver(_Outcome("ok", "", marker_text=log))
    res = install_library(_dblib(tmp_path), driver=drv, workdir=tmp_path)
    assert res.status == "not-installed"
    assert not res.ok
    assert "does not list" in res.detail


def test_a_successful_install_is_confirmed_from_the_resulting_list(tmp_path):
    log = (
        "SR-Before0=C:\\stock.IntLib\n"
        "SR-After0=C:\\stock.IntLib\n"
        "SR-After1=C:\\fake\\Stockroom.DbLib\n"
        "DONE\n"
    )
    drv = _FakeDriver(_Outcome("ok", "", marker_text=log))
    res = install_library(_dblib(tmp_path), driver=drv, workdir=tmp_path)
    assert res.status == "ok"
    assert res.ok
    assert res.before == ("C:\\stock.IntLib",)
    assert len(res.after) == 2


def test_installing_an_already_installed_library_reports_already(tmp_path):
    """Idempotent, and it says so. Re-running must not read as a fresh install, or a caller can
    never tell a working setup from one it just repaired."""
    log = "SR-Before0=C:\\fake\\Stockroom.DbLib\nSR-After0=C:\\fake\\Stockroom.DbLib\nDONE\n"
    drv = _FakeDriver(_Outcome("ok", "", marker_text=log))
    res = install_library(_dblib(tmp_path), driver=drv, workdir=tmp_path)
    assert res.status == "already"
    assert res.ok, "already installed is a success, not a failure"


def test_a_FAIL_line_wins_over_a_clean_exit(tmp_path):
    drv = _FakeDriver(_Outcome("ok", "", marker_text="FAIL: no IntegratedLibraryManager\nDONE\n"))
    res = install_library(_dblib(tmp_path), driver=drv, workdir=tmp_path)
    assert res.status == "not-installed"
    assert "IntegratedLibraryManager" in res.detail


def test_a_busy_altium_is_surfaced_not_swallowed(tmp_path):
    """A windowed Altium holds the license seat. Reporting that plainly is the difference between
    a user who closes Altium and a user who thinks the feature is broken."""
    drv = _FakeDriver(_Outcome("busy", "A windowed Altium is open and holds the license seat."))
    res = install_library(_dblib(tmp_path), driver=drv, workdir=tmp_path)
    assert res.status == "busy"
    assert not res.ok
    assert "license seat" in res.detail


def test_uninstall_that_leaves_the_library_listed_is_a_failure(tmp_path):
    log = "SR-Before0=C:\\fake\\Stockroom.DbLib\nSR-After0=C:\\fake\\Stockroom.DbLib\nDONE\n"
    drv = _FakeDriver(_Outcome("ok", "", marker_text=log))
    res = install_library(_dblib(tmp_path), uninstall=True, driver=drv, workdir=tmp_path)
    assert res.status == "not-installed"


def test_a_successful_uninstall_is_confirmed_by_absence(tmp_path):
    log = "SR-Before0=C:\\fake\\Stockroom.DbLib\nSR-After0=C:\\stock.IntLib\nDONE\n"
    drv = _FakeDriver(_Outcome("ok", "", marker_text=log))
    res = install_library(_dblib(tmp_path), uninstall=True, driver=drv, workdir=tmp_path)
    assert res.status == "ok"
    assert "Removed" in res.detail
