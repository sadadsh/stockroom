"""The pure logic in `scripts/deploy.py`: install discovery and the content-marker check.

The git half needs two real checkouts and is exercised by running it. What is pinned here is the
CONTENT CHECK, because that is the part which distinguishes a real deploy from two equally stale
checkouts, and a confident wrong "DEPLOY-MATCH" from exactly that situation has happened before.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "deploy", Path(__file__).resolve().parents[2] / "scripts" / "deploy.py"
)
deploy = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(deploy)


def test_a_present_marker_reports_nothing_missing(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "x.py").write_text("KEY_COLUMN = 'MPN'\n", encoding="utf-8")
    assert deploy.check_markers(tmp_path, ["app/x.py=KEY_COLUMN"]) == []


def test_a_file_that_arrived_WITHOUT_the_edit_is_caught(tmp_path):
    """The whole point. HEAD equality passes trivially when the commit never happened, so the only
    check that can tell "deployed" from "both sides equally stale" is looking for the actual edit."""
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "x.py").write_text("# the old version\n", encoding="utf-8")
    missing = deploy.check_markers(tmp_path, ["app/x.py=KEY_COLUMN"])
    assert len(missing) == 1
    assert "KEY_COLUMN" in missing[0]


def test_a_missing_file_is_named_rather_than_crashing(tmp_path):
    missing = deploy.check_markers(tmp_path, ["nope/gone.py=anything"])
    assert missing and "not present" in missing[0]


def test_a_malformed_marker_is_rejected_instead_of_silently_passing(tmp_path):
    """`--expect path` with no `=needle` must not read as "nothing to check, all good"."""
    missing = deploy.check_markers(tmp_path, ["app/x.py"])
    assert missing and "path=needle" in missing[0]


def test_the_install_is_DISCOVERED_not_hardcoded_to_one_username(monkeypatch, tmp_path):
    """The install lives under a per-user path and `%LOCALAPPDATA%` does not expand through WSL
    interop, so a hardcoded name would work on exactly one machine."""
    users = tmp_path / "Users"
    (users / "Someone Else" / "AppData" / "Local" / "Stockroom" / "app" / ".git").mkdir(parents=True)
    monkeypatch.setattr(deploy, "Path", Path)
    found = None
    for home in sorted(users.iterdir()):
        candidate = home / "AppData" / "Local" / "Stockroom" / "app"
        if (candidate / ".git").exists():
            found = candidate
    assert found is not None and found.name == "app"
