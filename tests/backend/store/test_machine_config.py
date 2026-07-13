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
    assert cfg.active_profile == "Main"
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
