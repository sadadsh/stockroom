"""kicad-cli discovery + non-fatal construction: the app must START even when
kicad-cli is not on PATH (library browse/search/mutations/sync do not need it), find
it wherever KiCad is installed, and raise a CLEAR error only when a KiCad operation is
actually requested. None of these tests need a real kicad-cli — discovery is mocked."""

from pathlib import Path

import stockroom.kicad.cli as cli_mod
import pytest
from stockroom.kicad.cli import KiCadCli, find_kicad_cli
from stockroom.kicad.errors import KiCadCliError


def test_find_kicad_cli_prefers_path(monkeypatch):
    monkeypatch.setattr(
        cli_mod.shutil, "which",
        lambda name: "/usr/bin/kicad-cli" if name == "kicad-cli" else None,
    )
    assert find_kicad_cli() == "/usr/bin/kicad-cli"


def test_find_kicad_cli_honors_an_explicit_override_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod.shutil, "which", lambda name: None)
    fake = tmp_path / "kicad-cli"
    fake.write_text("#!/bin/sh\n")
    assert find_kicad_cli(str(fake)) == str(fake)


def test_find_kicad_cli_falls_back_to_a_standard_install_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(cli_mod.shutil, "which", lambda name: None)
    installed = tmp_path / "bin" / "kicad-cli.exe"
    installed.parent.mkdir(parents=True)
    installed.write_text("")
    monkeypatch.setattr(
        cli_mod, "_standard_kicad_cli_paths", lambda: [tmp_path / "nope", installed]
    )
    assert find_kicad_cli() == str(installed)


def test_find_kicad_cli_returns_none_when_truly_absent(monkeypatch):
    monkeypatch.setattr(cli_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli_mod, "_standard_kicad_cli_paths", lambda: [])
    assert find_kicad_cli() is None


def test_windows_versions_sort_newest_first():
    # a directory scan must rank 10.0 ABOVE 9.0 (numeric, not lexicographic)
    assert cli_mod._version_key("10.0") > cli_mod._version_key("9.0")
    assert cli_mod._version_key("10.0") > cli_mod._version_key("8.0.1")
    assert cli_mod._version_key("9.0") > cli_mod._version_key("8.99")


def test_discovery_survives_an_unreadable_standard_install_dir(tmp_path, monkeypatch):
    # An unreadable / broken KiCad install dir (locked ACL, broken junction) must be
    # SKIPPED, never crash startup — otherwise discovery re-introduces the very crash
    # the non-fatal change exists to prevent.
    monkeypatch.setattr(cli_mod.shutil, "which", lambda name: None)
    monkeypatch.setattr(cli_mod.sys, "platform", "win32")
    kroot = tmp_path / "KiCad"
    kroot.mkdir()
    monkeypatch.setenv("ProgramFiles", str(tmp_path))
    monkeypatch.delenv("ProgramW6432", raising=False)
    monkeypatch.delenv("ProgramFiles(x86)", raising=False)
    real_iterdir = Path.iterdir

    def boom(self):
        if self == kroot:
            raise PermissionError(13, "denied")
        return real_iterdir(self)

    monkeypatch.setattr(Path, "iterdir", boom)
    # neither discovery nor construction may raise; the bad root is skipped
    assert cli_mod._standard_kicad_cli_paths() == []
    assert find_kicad_cli() is None
    assert KiCadCli().available is False


def test_kicadcli_construction_is_non_fatal_when_absent(monkeypatch):
    monkeypatch.setattr(cli_mod, "find_kicad_cli", lambda binary=None: None)
    cli = KiCadCli()  # MUST NOT raise — this is the startup-crash fix
    assert cli.available is False
    assert cli.binary is None


def test_kicadcli_command_raises_a_clear_error_when_absent(monkeypatch):
    monkeypatch.setattr(cli_mod, "find_kicad_cli", lambda binary=None: None)
    cli = KiCadCli()
    with pytest.raises(KiCadCliError) as e:
        cli.version()
    msg = str(e.value).lower()
    assert "kicad-cli not found" in msg and "install kicad" in msg
