"""Per-machine configuration and lossless legacy-secret migration.

Non-secret settings live outside the repo in ``config.json``. API keys, tokens,
and passwords live in Windows Credential Manager and exist on ``MachineConfig``
only in process memory for compatibility with the provider adapters.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import TYPE_CHECKING

from stockroom.credentials import (
    CredentialStoreError,
    default_credential_store,
)

if TYPE_CHECKING:
    from stockroom.credentials import CredentialStore


SECRET_FIELDS = (
    "mouser_api_key",
    "digikey_client_secret",
    "digikey_password",
    "github_token",
    "ul_password",
    "snapeda_password",
    "samacsys_password",
)


def _os_name() -> str:
    return os.name


def config_dir() -> Path:
    """Resolve the per-machine config directory.

    STOCKROOM_CONFIG_DIR wins (used in tests and for portable installs); then
    %APPDATA%/Stockroom on Windows; then ${XDG_CONFIG_HOME:-~/.config}/stockroom.
    """
    override = os.environ.get("STOCKROOM_CONFIG_DIR")
    if override:
        return Path(override)
    if _os_name() == "nt":
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        return Path(base) / "Stockroom"
    xdg = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(xdg) / "stockroom"


@dataclass
class MachineConfig:
    active_profile: str = "Stockroom"
    # Where the library repo lives on this machine (M9a). Blank on a fresh install, so the
    # app runs first-run onboarding (open / clone / create a library); persisted thereafter.
    # A frozen exe ships no library, so this is the ONLY thing that tells it where to look.
    libraries_root: str = ""
    # Where the STM32CubeMX MCU XML tree lives on this machine (stm-viewer workstream,
    # Phase 3, API-02). Blank until the user points it there (the all-families source is
    # Windows-side per research and is not bundled); stm.source.default_cubemx_source()
    # prefers this setting ahead of its own STM32_CUBEMX env-var/candidate-path fallback.
    # Not a secret - a plain filesystem path, echoed raw (never masked) in the settings DTO.
    stm_cubemx_source: str = ""
    mouser_api_key: str = field(default="", repr=False)
    # DigiKey Product Information API v4 OAuth2 client-credentials (opt-in, OFF by default —
    # spec section 6). Both must be set for enrich/routers/enrich.py:_make_pipeline to build a
    # live DigiKeyAdapter; either blank keeps DigiKey out of the enrichment source registry.
    digikey_client_id: str = ""
    digikey_client_secret: str = field(default="", repr=False)
    # DigiKey ACCOUNT web login (distinct from the OAuth API creds above). The capture driver
    # autofills this to sign into DigiKey.com and prepare a logged-in session for everything,
    # so a saved account clears the sign-in wall before the in-DigiKey CAD providers are reached.
    digikey_username: str = ""
    digikey_password: str = field(default="", repr=False)
    # A GitHub personal access token (fine-grained, Contents: write on the library repo) used to
    # authenticate library push/pull for the in-repo library, so a part add can auto-push and a
    # collaborator's changes pull. Stored in Windows Credential Manager and held here only in
    # process memory. Blank = no auto-push, sign in later.
    github_token: str = field(default="", repr=False)
    # Saved logins for the in-DigiKey CAD providers the guided capture window drives:
    # Ultra Librarian, SnapEDA, and SamacSys. DigiKey's EDA/CAD Models section aggregates
    # downloads from all three, and the driver prefers Ultra Librarian (it often bundles the
    # complete KiCad + Altium + 3D set). The username is not a secret; the password is.
    # Passwords are stored in Windows Credential Manager; usernames remain ordinary machine
    # settings. Blank = log in by hand in the capture window (session persistence keeps you
    # signed in thereafter).
    ul_username: str = ""
    ul_password: str = field(default="", repr=False)
    # Default-off authorization for the reviewed Ultra Librarian private-evaluation exception.
    # This is deliberately a non-secret machine setting: it grants no account access by itself,
    # and passwords remain exclusively in Windows Credential Manager. Public/general installs
    # stay on assisted capture unless their own authorization is explicitly recorded.
    ul_private_evaluation_automation: bool = False
    snapeda_username: str = ""
    snapeda_password: str = field(default="", repr=False)
    samacsys_username: str = ""
    samacsys_password: str = field(default="", repr=False)
    kicad_config_override: str = ""
    # An explicit kicad-cli binary path, for a non-standard KiCad install that
    # discovery (PATH + standard locations) does not find. Empty = auto-discover.
    kicad_cli_override: str = ""
    sync_enabled: bool = True
    # Set once the user completes first-run onboarding (picked / cloned / created a library,
    # or chose to continue with the default). Drives the one-time welcome screen (M9b).
    onboarded: bool = False
    window: dict = field(default_factory=dict)
    # UI preferences (theme, rail_collapsed). MACHINE level, not profile level: they follow the
    # person, not the library. They live here rather than in the browser because the host binds an
    # EPHEMERAL PORT, so the page origin changes on every launch and origin-scoped localStorage
    # starts empty each time - measured on real Windows, the theme reverted to dark on every single
    # launch. A dict so a new preference needs no schema change. Kept separate from `window`, which
    # is geometry.
    ui: dict = field(default_factory=dict)
    # Library-scale rescan (Phase-1b-2): a part is re-checked only when its last check is older
    # than this many days (incremental), and each provider's calls are paced to <= N/min so a
    # full-library rescan trickles within quota instead of tripping a 429. Sensible defaults; the
    # settings UI can tune them later.
    rescan_ttl_days: int = 7
    rescan_mouser_per_min: int = 20
    rescan_digikey_per_min: int = 60
    _credential_store: "CredentialStore | None" = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )
    _credential_path: Path | None = field(
        default=None,
        init=False,
        repr=False,
        compare=False,
    )

    @classmethod
    def _path(cls, path: Path | None) -> Path:
        return Path(path) if path is not None else config_dir() / "config.json"

    @classmethod
    def load(
        cls,
        path: Path | None = None,
        *,
        credential_store: "CredentialStore | None" = None,
    ) -> "MachineConfig":
        p = cls._path(path)
        data = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
        if not isinstance(data, dict):
            raise ValueError("machine config must be a JSON object")
        store = credential_store or default_credential_store(p)

        secret_values: dict[str, str] = {}
        legacy_fields_present = False
        for name in SECRET_FIELDS:
            if name in data:
                legacy_fields_present = True
                secret_values[name] = str(data.get(name) or "")
            else:
                secret_values[name] = store.get(name) or ""

        known = {item.name for item in fields(cls) if item.init}
        public = {
            key: value for key, value in data.items() if key in known and key not in SECRET_FIELDS
        }
        config = cls(**public, **secret_values)
        config._credential_store = store
        config._credential_path = p.resolve(strict=False)

        if legacy_fields_present:
            # The plaintext file remains untouched until every credential has
            # been stored and read back. A failure therefore loses no data.
            _sync_credentials(store, secret_values)
            _write_public_config(p, config)
        return config

    def save(
        self,
        path: Path | None = None,
        *,
        credential_store: "CredentialStore | None" = None,
    ) -> None:
        p = self._path(path)
        resolved = p.resolve(strict=False)
        store = credential_store
        if (
            store is None
            and self._credential_store is not None
            and self._credential_path == resolved
        ):
            store = self._credential_store
        store = store or default_credential_store(p)

        values = {name: str(getattr(self, name, "") or "") for name in SECRET_FIELDS}
        _sync_credentials(store, values)
        _write_public_config(p, self)
        self._credential_store = store
        self._credential_path = resolved


def _public_payload(config: MachineConfig) -> dict[str, object]:
    return {
        item.name: getattr(config, item.name)
        for item in fields(config)
        if item.init and item.name not in SECRET_FIELDS
    }


def _write_public_config(path: Path, config: MachineConfig) -> None:
    """Atomically replace the non-secret JSON after durable credential writes."""

    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        json.dumps(
            _public_payload(config),
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            newline="\n",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _sync_credentials(store: "CredentialStore", values: dict[str, str]) -> None:
    """Apply a credential batch and restore its prior state on any failure."""

    before = {name: store.get(name) for name in SECRET_FIELDS}
    try:
        for name in SECRET_FIELDS:
            value = values[name]
            if value:
                store.set(name, value)
                if store.get(name) != value:
                    raise CredentialStoreError("credential write verification failed")
            else:
                store.delete(name)
                if store.get(name) is not None:
                    raise CredentialStoreError("credential deletion verification failed")
    except Exception as exc:
        rollback_failed = False
        for name, old_value in before.items():
            try:
                if old_value:
                    store.set(name, old_value)
                else:
                    store.delete(name)
            except Exception:
                rollback_failed = True
        if rollback_failed:
            raise CredentialStoreError(
                "credential update failed and rollback was incomplete"
            ) from exc
        raise
