from stockroom.kicad.config import detect_kicad_version, detect_running_kicad, kicad_config_dir


def test_override_wins(tmp_path):
    assert kicad_config_dir(override=str(tmp_path / "kc")) == tmp_path / "kc"


def test_detect_version_picks_newest_numeric_dir(tmp_path):
    base = tmp_path / "kicad"
    for name in ("9.0", "10.0", "junk"):
        (base / name).mkdir(parents=True)
    # numeric, not lexicographic: a string sort would rank 9.0 above 10.0
    assert detect_kicad_version(base) == "10.0"
    (base / "11.0").mkdir()
    assert detect_kicad_version(base) == "11.0"


def test_detect_version_none_when_base_missing_or_empty(tmp_path):
    assert detect_kicad_version(tmp_path / "absent") is None
    empty = tmp_path / "kicad"
    empty.mkdir()
    assert detect_kicad_version(empty) is None


def test_config_dir_autodetects_installed_version(monkeypatch, tmp_path):
    # a machine still on KiCad 9: wiring must land in the config dir KiCad reads
    monkeypatch.setattr("stockroom.kicad.config._os_name", lambda: "posix")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    (tmp_path / "xdg" / "kicad" / "9.0").mkdir(parents=True)
    assert kicad_config_dir() == tmp_path / "xdg" / "kicad" / "9.0"


def test_config_dir_defaults_to_10_when_never_run(monkeypatch, tmp_path):
    monkeypatch.setattr("stockroom.kicad.config._os_name", lambda: "posix")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert kicad_config_dir() == tmp_path / "xdg" / "kicad" / "10.0"


def test_windows_path(monkeypatch, tmp_path):
    monkeypatch.setattr("stockroom.kicad.config._os_name", lambda: "nt")
    monkeypatch.setenv("APPDATA", str(tmp_path / "Roaming"))
    assert kicad_config_dir("10.0") == tmp_path / "Roaming" / "kicad" / "10.0"


def test_posix_xdg_path(monkeypatch, tmp_path):
    monkeypatch.setattr("stockroom.kicad.config._os_name", lambda: "posix")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert kicad_config_dir("10.0") == tmp_path / "xdg" / "kicad" / "10.0"


def test_detect_running_true_when_process_present():
    assert detect_running_kicad(lister=lambda: "1234 kicad\n5678 bash\n") is True


def test_detect_running_matches_editors():
    assert detect_running_kicad(lister=lambda: "pcbnew.exe\n") is True
    assert detect_running_kicad(lister=lambda: "eeschema\n") is True


def test_detect_running_false_when_absent():
    assert detect_running_kicad(lister=lambda: "bash\nvim\n") is False


def test_detect_running_never_raises():
    def boom():
        raise OSError("no process tool")
    assert detect_running_kicad(lister=boom) is False


def test_windows_reads_the_process_snapshot_instead_of_shelling_out(monkeypatch):
    """`tasklist` enumerates AND formats every process; the snapshot API only enumerates.

    Measured on the owner's machine, which runs ~3,600 processes: 6.75 s versus 82 ms. This runs
    inside `GET /api/system/info`, so the command version held that endpoint open past the
    client's default read timeout and the request failed rather than answering slowly.
    """
    import os
    import subprocess

    from stockroom.kicad import config

    if os.name != "nt":
        return

    def refuse(*_args, **_kwargs):
        raise AssertionError("the Windows path must not spawn a process lister")

    monkeypatch.setattr(subprocess, "run", refuse)
    names = config._default_lister()
    assert names.strip(), "the snapshot returned no process names"
    # The reader itself must run, not merely be defined: this test process is in its own snapshot.
    assert "python" in names.lower() or "pytest" in names.lower()
