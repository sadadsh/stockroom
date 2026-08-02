"""kicad-cli discovery + non-fatal construction: the app must START even when
kicad-cli is not on PATH (library browse/search/mutations/sync do not need it), find
it wherever KiCad is installed, and raise a CLEAR error only when a KiCad operation is
actually requested. None of these tests need a real kicad-cli — discovery is mocked."""

from pathlib import Path

import pytest

import stockroom.kicad.cli as cli_mod
from stockroom.kicad.cli import KiCadCli, find_kicad_cli
from stockroom.kicad.errors import KiCadCliError


def test_find_kicad_cli_prefers_path(monkeypatch):
    monkeypatch.setattr(cli_mod.sys, "platform", "linux")
    monkeypatch.setattr(
        cli_mod.shutil, "which",
        lambda name: "/usr/bin/kicad-cli" if name == "kicad-cli" else None,
    )
    assert find_kicad_cli() == "/usr/bin/kicad-cli"


def test_windows_discovery_prefers_the_real_executable_over_a_cmd_shim(
    tmp_path, monkeypatch
):
    shim = tmp_path / "capabilities" / "kicad-cli.CMD"
    installed = tmp_path / "KiCad" / "10.0" / "bin" / "kicad-cli.exe"
    shim.parent.mkdir(parents=True)
    installed.parent.mkdir(parents=True)
    shim.write_text("@echo off\r\n")
    installed.write_bytes(b"MZ")
    monkeypatch.setattr(cli_mod.sys, "platform", "win32")
    monkeypatch.setattr(cli_mod.shutil, "which", lambda name: str(shim))
    monkeypatch.setattr(cli_mod, "_standard_kicad_cli_paths", lambda: [installed])

    assert find_kicad_cli() == str(installed)


@pytest.mark.parametrize("suffix", [".CMD", ".bat"])
def test_windows_discovery_rejects_a_batch_shim_even_when_it_is_the_only_result(
    suffix, tmp_path, monkeypatch
):
    shim = tmp_path / f"kicad-cli{suffix}"
    shim.write_text("@echo off\r\n")
    monkeypatch.setattr(cli_mod.sys, "platform", "win32")
    monkeypatch.setattr(cli_mod.shutil, "which", lambda _name: str(shim))
    monkeypatch.setattr(cli_mod, "_standard_kicad_cli_paths", lambda: [])

    assert find_kicad_cli() is None
    assert find_kicad_cli(str(shim)) is None


def test_kicad_commands_never_create_a_console_window(tmp_path, monkeypatch):
    binary = tmp_path / "kicad-cli.exe"
    binary.write_bytes(b"MZ")
    seen = {}

    def run(argv, **kwargs):
        seen["argv"] = argv
        seen.update(kwargs)
        return type("Completed", (), {"returncode": 0, "stdout": "10.0\n", "stderr": ""})()

    monkeypatch.setattr(cli_mod.subprocess, "run", run)
    cli = KiCadCli(str(binary))

    assert cli.version() == "10.0"
    assert seen["creationflags"] == getattr(cli_mod.subprocess, "CREATE_NO_WINDOW", 0)


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
