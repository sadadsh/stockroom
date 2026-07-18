"""Per-machine configuration, stored OUTSIDE the repo.

Active profile, API keys, KiCad path override, sync preference, window state.
Nothing here is machine-independent or secret-free enough to live in the repo
(spec sections 2 and 11).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path


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
    active_profile: str = "Main"
    # Where the library repo lives on this machine (M9a). Blank on a fresh install, so the
    # app runs first-run onboarding (open / clone / create a library); persisted thereafter.
    # A frozen exe ships no library, so this is the ONLY thing that tells it where to look.
    libraries_root: str = ""
    mouser_api_key: str = ""
    # DigiKey Product Information API v4 OAuth2 client-credentials (opt-in, OFF by default —
    # spec section 6). Both must be set for enrich/routers/enrich.py:_make_pipeline to build a
    # live DigiKeyAdapter; either blank keeps DigiKey out of the enrichment source registry.
    digikey_client_id: str = ""
    digikey_client_secret: str = ""
    # A GitHub personal access token (fine-grained, Contents: write on the library repo) used to
    # authenticate library push/pull for the in-repo library, so a part add can auto-push and a
    # collaborator's changes pull. Per-machine, stored in config.json (in the OS config dir, never
    # the repo), so it is a local secret and never committed. Blank = no auto-push, sign in later.
    github_token: str = ""
    kicad_config_override: str = ""
    # An explicit kicad-cli binary path, for a non-standard KiCad install that
    # discovery (PATH + standard locations) does not find. Empty = auto-discover.
    kicad_cli_override: str = ""
    sync_enabled: bool = True
    # Set once the user completes first-run onboarding (picked / cloned / created a library,
    # or chose to continue with the default). Drives the one-time welcome screen (M9b).
    onboarded: bool = False
    window: dict = field(default_factory=dict)
    # Library-scale rescan (Phase-1b-2): a part is re-checked only when its last check is older
    # than this many days (incremental), and each provider's calls are paced to <= N/min so a
    # full-library rescan trickles within quota instead of tripping a 429. Sensible defaults; the
    # settings UI can tune them later.
    rescan_ttl_days: int = 7
    rescan_mouser_per_min: int = 20
    rescan_digikey_per_min: int = 60

    @classmethod
    def _path(cls, path: Path | None) -> Path:
        return Path(path) if path is not None else config_dir() / "config.json"

    @classmethod
    def load(cls, path: Path | None = None) -> "MachineConfig":
        p = cls._path(path)
        if not p.exists():
            return cls()
        data = json.loads(p.read_text(encoding="utf-8"))
        known = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in known})

    def save(self, path: Path | None = None) -> None:
        p = self._path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(
            json.dumps(asdict(self), indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
