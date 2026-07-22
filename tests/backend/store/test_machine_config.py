import json

import pytest

from stockroom.store.machine_config import MachineConfig, config_dir


def test_config_dir_honors_explicit_override(monkeypatch, tmp_path):
    monkeypatch.setenv("STOCKROOM_CONFIG_DIR", str(tmp_path / "sr"))
    assert config_dir() == tmp_path / "sr"


def test_config_dir_uses_appdata_on_windows(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCKROOM_CONFIG_DIR", raising=False)
    monkeypatch.setattr("stockroom.store.machine_config._os_name", lambda: "nt")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert config_dir() == tmp_path / "AppData" / "Roaming" / "Stockroom"


def test_config_dir_uses_xdg_on_posix(monkeypatch, tmp_path):
    monkeypatch.delenv("STOCKROOM_CONFIG_DIR", raising=False)
    monkeypatch.setattr("stockroom.store.machine_config._os_name", lambda: "posix")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config_dir() == tmp_path / "xdg" / "stockroom"


def test_missing_file_returns_defaults(tmp_path):
    cfg = MachineConfig.load(tmp_path / "nope.json")
    assert cfg.active_profile == "Stockroom"
    assert cfg.mouser_api_key == ""
    assert cfg.sync_enabled is True


def test_save_then_load_round_trip(tmp_path):
    path = tmp_path / "deep" / "config.json"
    cfg = MachineConfig(active_profile="Bench", mouser_api_key="KEY123", sync_enabled=False)
    cfg.save(path)
    assert path.exists()
    again = MachineConfig.load(path)
    assert again == cfg


def test_saved_json_is_human_readable(tmp_path):
    path = tmp_path / "config.json"
    MachineConfig(active_profile="Bench").save(path)
    data = json.loads(path.read_text())
    assert data["active_profile"] == "Bench"
    assert path.read_text().endswith("\n")


def test_load_ignores_unknown_keys(tmp_path):
    path = tmp_path / "config.json"
    path.write_text(json.dumps({"active_profile": "X", "future_field": 9}))
    cfg = MachineConfig.load(path)
    assert cfg.active_profile == "X"


def test_rescan_config_defaults():
    # Library-scale rescan (Phase-1b-2): a fresh install must trickle within each API's
    # published quota out of the box, without the settings UI having to be touched first.
    cfg = MachineConfig()
    assert cfg.rescan_ttl_days == 7
    assert cfg.rescan_mouser_per_min == 20
    assert cfg.rescan_digikey_per_min == 60


def test_libraries_root_defaults_blank_and_round_trips(tmp_path):
    # M9a: the per-machine library location. Blank on a fresh install (first-run onboarding);
    # persisted once the user picks/creates/clones a library.
    assert MachineConfig().libraries_root == ""
    path = tmp_path / "config.json"
    cfg = MachineConfig(libraries_root=str(tmp_path / "lib"))
    cfg.save(path)
    assert MachineConfig.load(path).libraries_root == str(tmp_path / "lib")


def test_vendor_login_fields_round_trip(tmp_path):
    path = tmp_path / "config.json"
    cfg = MachineConfig(
        ul_username="me@x.com",
        ul_password="pw",
        snapeda_username="s",
        snapeda_password="q",
    )
    cfg.save(path)
    loaded = MachineConfig.load(path)
    assert loaded.ul_username == "me@x.com"
    assert loaded.ul_password == "pw"
    assert loaded.snapeda_username == "s"
    assert loaded.snapeda_password == "q"


def test_vendor_login_defaults_empty():
    cfg = MachineConfig()
    assert cfg.ul_username == "" and cfg.ul_password == ""
    assert cfg.snapeda_username == "" and cfg.snapeda_password == ""
