from stockroom.kicad.config import detect_running_kicad, kicad_config_dir


def test_override_wins(tmp_path):
    assert kicad_config_dir(override=str(tmp_path / "kc")) == tmp_path / "kc"


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
