"""The suite must never write the developer's REAL machine config.

MEASURED INCIDENT, 2026-07-27. The owner's live `~/.config/stockroom/config.json` was found holding
`libraries_root = /tmp/pytest-of-sadad/pytest-201/test_switch_library_rewires_sr0/B` with every
vendor credential blanked -- a test run had overwritten real user config. That is data loss on the
developer's own machine, and on a second machine it is also a device-parity break, because the two
installs then disagree about what is stored.

WHY IT HAPPENED: the `_isolate_machine_config` autouse fixture existed in `tests/backend/api/
conftest.py` ONLY. Twenty other test directories had no isolation at all, so any test outside
`api/` that reached `MachineConfig.save()` wrote straight to the real config dir. The protection had
been added where the bug was first seen rather than at the root -- a hand-listed coverage set, which
grows silent holes by construction.

These tests live in `store/` DELIBERATELY: a directory that was NOT covered before the fix, so they
fail if the isolation is ever narrowed back to `api/`.
"""

from __future__ import annotations

import os
from pathlib import Path

from stockroom.store.machine_config import MachineConfig, config_dir


def _real_config_dirs() -> list[Path]:
    """Where a real user's config lives on this platform, ignoring any test override."""
    out = [Path.home() / ".config" / "stockroom"]
    appdata = os.environ.get("APPDATA")
    if appdata:
        out.append(Path(appdata) / "Stockroom")
    return out


def test_config_dir_is_isolated_from_the_real_user_config():
    """The active config dir must never be the developer's real one."""
    active = config_dir().resolve()
    for real in _real_config_dirs():
        try:
            assert active != real.resolve(), (
                f"config_dir() resolves to the REAL user config {real} -- a save() in any test "
                f"would overwrite the developer's own credentials and library path"
            )
        except OSError:
            continue


def test_saving_config_does_not_touch_the_real_file(tmp_path):
    """Drive the actual write path, rather than trusting that the env var is merely set.

    An env check alone would pass if some code path ignored the override; this performs a real
    save and then asserts both halves: the bytes landed in the ISOLATED dir, and the real file on
    disk is untouched.

    IT REFUSES TO WRITE WHEN ISOLATION IS ALREADY BROKEN, and that ordering is the point. The
    obvious version of this test -- save first, compare the real file afterwards -- only reports
    the defect BY COMMITTING IT: on a broken fixture it writes straight into the developer's own
    config, which is the exact damage of 2026-07-27 that this file exists to prevent. A guard that
    has to cause the harm to detect it is not a guard. So the destination is checked BEFORE
    anything is written, and a broken state fails here having changed nothing.
    """
    active = config_dir().resolve()
    for real_dir in _real_config_dirs():
        try:
            resolved = real_dir.resolve()
        except OSError:
            continue
        assert active != resolved, (
            f"REFUSING to run the save: config_dir() is the real user config {real_dir}. "
            "Performing the write to prove the point would itself overwrite the developer's "
            "credentials -- the isolation fixture must be repaired first."
        )

    real = Path.home() / ".config" / "stockroom" / "config.json"
    before = real.read_bytes() if real.exists() else None

    cfg = MachineConfig.load()
    cfg.libraries_root = str(tmp_path / "some-library")
    cfg.save()

    after = real.read_bytes() if real.exists() else None
    assert after == before, (
        "a test-driven config.save() modified the developer's real config.json"
    )
    # POSITIVE half: prove the write actually happened somewhere, so this cannot pass by the save
    # having silently done nothing at all.
    assert (active / "config.json").is_file(), (
        f"config.save() wrote nothing to the isolated dir {active}; the negative assertion above "
        "would then pass for the wrong reason"
    )


def test_isolation_env_is_actually_set():
    """The mechanism itself, asserted directly so a silent removal is loud."""
    assert os.environ.get("STOCKROOM_CONFIG_DIR"), (
        "STOCKROOM_CONFIG_DIR is not set for this test, so config_dir() falls back to the real "
        "user directory. The autouse isolation fixture must cover the WHOLE suite."
    )
