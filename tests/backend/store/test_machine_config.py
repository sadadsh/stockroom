import json

import pytest

from stockroom.credentials import CredentialStoreError, MemoryCredentialStore
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
    assert "mouser_api_key" not in json.loads(path.read_text())
    again = MachineConfig.load(path)
    assert again == cfg


def test_reload_reads_the_exact_source_and_reuses_its_credential_store(tmp_path):
    path = tmp_path / "custom" / "machine.json"
    store = MemoryCredentialStore("reload-source")
    MachineConfig(
        active_profile="Before",
        github_token="SECRET",
    ).save(path, credential_store=store)
    loaded = MachineConfig.load(path, credential_store=store)
    MachineConfig(
        active_profile="After",
        github_token="SECRET",
        ui={"theme": "light"},
    ).save(path, credential_store=store)

    latest = loaded.reload(migrate_credentials=False)

    assert latest is not loaded
    assert latest.source_path == path.resolve(strict=False)
    assert latest.active_profile == "After"
    assert latest.github_token == "SECRET"
    assert latest.ui == {"theme": "light"}


def test_reload_preserves_an_explicit_detached_configuration():
    detached = MachineConfig(active_profile="Embedded")

    assert detached.source_path is None
    assert detached.reload() is detached


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
    saved = json.loads(path.read_text())
    assert "ul_password" not in saved
    assert "snapeda_password" not in saved
    assert saved["ul_username"] == "me@x.com"
    loaded = MachineConfig.load(path)
    assert loaded.ul_username == "me@x.com"
    assert loaded.ul_password == "pw"
    assert loaded.snapeda_username == "s"
    assert loaded.snapeda_password == "q"


def test_vendor_login_defaults_empty():
    cfg = MachineConfig()
    assert cfg.ul_username == "" and cfg.ul_password == ""
    assert cfg.snapeda_username == "" and cfg.snapeda_password == ""


def test_samacsys_and_digikey_account_fields_round_trip(tmp_path):
    # SamacSys is a kept in-DigiKey CAD provider; the DigiKey account login is the
    # web sign-in the capture driver autofills (distinct from the OAuth API creds).
    path = tmp_path / "config.json"
    cfg = MachineConfig(
        samacsys_username="sam@x.com",
        samacsys_password="sp",
        digikey_username="dk@x.com",
        digikey_password="dp",
    )
    cfg.save(path)
    saved = json.loads(path.read_text())
    assert "samacsys_password" not in saved
    assert "digikey_password" not in saved
    loaded = MachineConfig.load(path)
    assert loaded.samacsys_username == "sam@x.com"
    assert loaded.samacsys_password == "sp"
    assert loaded.digikey_username == "dk@x.com"
    assert loaded.digikey_password == "dp"


def test_samacsys_and_digikey_account_defaults_empty():
    cfg = MachineConfig()
    assert cfg.samacsys_username == "" and cfg.samacsys_password == ""
    assert cfg.digikey_username == "" and cfg.digikey_password == ""


def test_legacy_plaintext_secrets_migrate_before_json_is_scrubbed(tmp_path):
    path = tmp_path / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "active_profile": "Bench",
                "mouser_api_key": "LEGACY-MOUSER",
                "digikey_client_secret": "LEGACY-DIGIKEY",
                "github_token": "LEGACY-GITHUB",
            }
        ),
        encoding="utf-8",
    )
    store = MemoryCredentialStore("legacy-migration")

    loaded = MachineConfig.load(path, credential_store=store)

    assert loaded.mouser_api_key == "LEGACY-MOUSER"
    assert loaded.digikey_client_secret == "LEGACY-DIGIKEY"
    assert loaded.github_token == "LEGACY-GITHUB"
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert (
        not {
            "mouser_api_key",
            "digikey_client_secret",
            "github_token",
        }
        & saved.keys()
    )
    assert store.get("mouser_api_key") == "LEGACY-MOUSER"
    assert store.get("digikey_client_secret") == "LEGACY-DIGIKEY"
    assert store.get("github_token") == "LEGACY-GITHUB"


def test_clearing_a_secret_removes_it_from_the_store(tmp_path):
    path = tmp_path / "config.json"
    store = MemoryCredentialStore("clear-secret")
    config = MachineConfig(mouser_api_key="FIRST")
    config.save(path, credential_store=store)
    assert store.get("mouser_api_key") == "FIRST"

    config.mouser_api_key = ""
    config.save(path, credential_store=store)

    assert store.get("mouser_api_key") is None
    assert MachineConfig.load(path, credential_store=store).mouser_api_key == ""


class _FailingStore:
    def __init__(self):
        self.values: dict[str, str] = {}

    def get(self, name: str) -> str | None:
        return self.values.get(name)

    def set(self, name: str, value: str) -> None:
        if name == "digikey_client_secret":
            raise CredentialStoreError("injected credential failure")
        self.values[name] = value

    def delete(self, name: str) -> None:
        self.values.pop(name, None)


def test_failed_legacy_migration_preserves_the_plaintext_source(tmp_path):
    path = tmp_path / "legacy.json"
    original = json.dumps(
        {
            "mouser_api_key": "FIRST",
            "digikey_client_secret": "SECOND",
        }
    )
    path.write_text(original, encoding="utf-8")

    with pytest.raises(CredentialStoreError, match="injected credential failure"):
        MachineConfig.load(path, credential_store=_FailingStore())

    assert path.read_text(encoding="utf-8") == original


def test_failed_save_does_not_replace_existing_public_config(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"active_profile":"Original"}', encoding="utf-8")
    config = MachineConfig(
        active_profile="Replacement",
        mouser_api_key="FIRST",
        digikey_client_secret="SECOND",
    )

    with pytest.raises(CredentialStoreError, match="injected credential failure"):
        config.save(path, credential_store=_FailingStore())

    assert path.read_text(encoding="utf-8") == '{"active_profile":"Original"}'
