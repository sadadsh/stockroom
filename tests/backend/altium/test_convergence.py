"""Automatic, persistent Altium DbLib setup and its fresh-session evidence boundary."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from stockroom.altium.convergence import (
    AltiumLibraryConvergenceService,
    PersistenceVerification,
    converge_altium_library,
    render_installed_libraries_probe_script,
    render_persistence_probe_script,
    verify_libraries_absent,
    verify_persistent_library,
)
from stockroom.altium.install import InstallResult


@dataclass
class _Outcome:
    status: str
    detail: str = ""
    marker_text: str = ""

    @property
    def ok(self) -> bool:
        return self.status == "ok"


class _Host:
    def __init__(self, root: Path):
        self.root = root

    def to_windows_path(self, path: str) -> str:
        return "C:\\fake\\" + Path(path).name

    def windows_temp(self) -> Path:
        return self.root


class _Driver:
    def __init__(self, root: Path, outcome: _Outcome | None = None):
        self.host = _Host(root)
        self.x2 = root / "AD99" / "X2.EXE"
        self.x2.parent.mkdir(parents=True, exist_ok=True)
        self.x2.write_bytes(b"MZ")
        self.outcome = outcome or _Outcome("ok")
        self.runs = 0

    def run_script(self, **_kwargs):
        self.runs += 1
        return self.outcome


def _dblib(tmp_path: Path, name: str = "Stockroom.DbLib") -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    path = tmp_path / name
    path.write_text("[OutputDatabaseLinkFile]\n", encoding="utf-8")
    db = tmp_path / "stockroom-parts.db"
    connection = sqlite3.connect(db)
    try:
        connection.execute(
            'CREATE TABLE IF NOT EXISTS "Parts" ('
            '"MPN" TEXT, "Library Ref" TEXT, "Library Path" TEXT, '
            '"Footprint Ref" TEXT, "Footprint Path" TEXT)'
        )
        if not connection.execute('SELECT 1 FROM "Parts" LIMIT 1').fetchone():
            connection.execute(
                'INSERT INTO "Parts" VALUES (?, ?, ?, ?, ?)',
                (
                    "TPD6E05U06RVZR",
                    "TPD6E05U06RVZR",
                    "Part.SchLib",
                    "PART-FOOTPRINT",
                    "Part.PcbLib",
                ),
            )
        connection.commit()
    finally:
        connection.close()
    (tmp_path / "Part.SchLib").write_bytes(b"symbol")
    (tmp_path / "Part.PcbLib").write_bytes(b"footprint")
    return path


def _placeable(
    key: str = "TPD6E05U06RVZR",
    *,
    installed_paths: tuple[str, ...] = ("C:\\fake\\Stockroom.DbLib",),
) -> PersistenceVerification:
    return PersistenceVerification(
        "ok",
        "fresh session resolved the part",
        installed_paths=installed_paths,
        component_key=key,
        symbol_library="C:\\lib\\Part.SchLib",
        footprint_library="C:\\lib\\Part.PcbLib",
        placement_parameters="PlacingFromDatabase=TRUE",
        altium_log="DONE",
    )


def test_fresh_session_probe_cannot_install_the_library_it_is_measuring():
    script = render_persistence_probe_script(
        dblib_win="C:\\lib\\Stockroom.DbLib",
        marker_win="C:\\temp\\probe.txt",
        design_item_id="TPD6E05U06RVZR",
    )

    assert "ILM.InstallLibrary" not in script
    assert "ILM.ActivateLibrary" in script
    assert "InstalledLibraryPath" in script
    assert "GetAllComponentKeys" in script
    assert "FindComponentSymbol" in script
    assert "FindModelLibraryPath" in script
    assert "GetComponentPlacementParameters" in script


def test_fresh_installed_list_probe_is_read_only():
    script = render_installed_libraries_probe_script(marker_win="C:\\temp\\probe.txt")

    assert "InstalledLibraryPath" in script
    assert "InstallLibrary" not in script
    assert "UninstallLibrary" not in script


def test_fresh_installed_list_probe_proves_receipted_paths_are_absent(tmp_path):
    target = tmp_path / "Old.DbLib"
    driver = _Driver(
        tmp_path,
        _Outcome("ok", marker_text="SR-Installed0=C:\\user\\User.IntLib\nDONE\n"),
    )

    result = verify_libraries_absent((target,), driver=driver, workdir=tmp_path / "work")

    assert result.ok
    assert result.installed_paths == ("C:\\user\\User.IntLib",)
    assert driver.runs == 1


def test_fresh_installed_list_probe_rejects_a_remaining_receipted_path(tmp_path):
    target = tmp_path / "Old.DbLib"
    driver = _Driver(
        tmp_path,
        _Outcome("ok", marker_text="SR-Installed0=C:\\fake\\Old.DbLib\nDONE\n"),
    )

    result = verify_libraries_absent((target,), driver=driver, workdir=tmp_path / "work")

    assert result.status == "still-installed"
    assert not result.ok
    assert str(target) in result.detail


def test_fresh_session_verification_requires_persistence_and_a_complete_real_part(tmp_path):
    log = (
        "SR-Installed0=C:\\fake\\Stockroom.DbLib\n"
        "SR-DbComponentKey=TPD6E05U06RVZR\n"
        "SR-DbSchLibPath=C:\\lib\\TPD6E05U06RVZR.SchLib\n"
        "SR-FootprintLibrary=C:\\lib\\TPD6E05U06RVZR.PcbLib\n"
        "SR-PlacementParameters=PlacingFromDatabase=TRUE\n"
        "DONE\n"
    )
    driver = _Driver(tmp_path, _Outcome("ok", marker_text=log))

    result = verify_persistent_library(
        _dblib(tmp_path),
        driver=driver,
        workdir=tmp_path / "probe",
    )

    assert result.ok
    assert result.component_key == "TPD6E05U06RVZR"
    assert result.symbol_library.endswith(".SchLib")
    assert result.footprint_library.endswith(".PcbLib")
    assert driver.runs == 1
    generated = (tmp_path / "probe" / "SRVerifyPersistentLibrary.pas").read_text(encoding="utf-8")
    assert "ILM.InstallLibrary" not in generated


def test_a_fresh_process_missing_the_dblib_cannot_create_a_receipt(tmp_path):
    driver = _Driver(
        tmp_path,
        _Outcome(
            "ok",
            marker_text=(
                "SR-Installed0=C:\\Altium\\Simulation.IntLib\n"
                "FAIL: the DbLib is absent from this fresh session\nDONE\n"
            ),
        ),
    )

    result = verify_persistent_library(
        _dblib(tmp_path),
        driver=driver,
        workdir=tmp_path / "probe",
    )

    assert result.status == "not-installed"
    assert not result.ok


def test_an_installed_row_with_a_missing_footprint_is_not_placeable(tmp_path):
    log = (
        "SR-Installed0=C:\\fake\\Stockroom.DbLib\n"
        "SR-DbComponentKey=REAL-MPN\n"
        "SR-DbSchLibPath=C:\\lib\\Part.SchLib\n"
        "SR-FootprintLibrary=\n"
        "SR-PlacementParameters=PlacingFromDatabase=TRUE\n"
        "FAIL: the first database part has no resolvable footprint\n"
        "DONE\n"
    )
    driver = _Driver(tmp_path, _Outcome("ok", marker_text=log))

    result = verify_persistent_library(
        _dblib(tmp_path),
        driver=driver,
        workdir=tmp_path / "probe",
    )

    assert result.status == "not-placeable"
    assert "footprint" in result.detail


def test_known_mpn_resolution_wins_over_ad26s_empty_component_enumerator(tmp_path):
    """Measured AD26 behavior: key enumeration says zero while this exact MPN resolves.

    The database is the deterministic authority for which MPN exists. The fresh Altium process
    must still return a successful symbol lookup and exact PCBLIB placement model for that MPN.
    """

    log = (
        "SR-Installed0=C:\\fake\\Stockroom.DbLib\n"
        "SR-DbComponentKey=TPD6E05U06RVZR\n"
        "SR-DbComponentKeyCount=0\n"
        "SR-SymbolResolved=True\n"
        "SR-SymbolLibrary=\n"
        "SR-FootprintLibrary=\n"
        "SR-PlacementParameters=ModelType0=PCBLIB|ModelName0=PART-FOOTPRINT|"
        "PlacingFromDatabase=TRUE|DesignItemId=TPD6E05U06RVZR\n"
        "DONE\n"
    )
    driver = _Driver(tmp_path, _Outcome("ok", marker_text=log))

    result = verify_persistent_library(
        _dblib(tmp_path),
        driver=driver,
        workdir=tmp_path / "probe",
    )

    assert result.ok
    assert result.symbol_library.endswith("Part.SchLib")
    assert result.footprint_library.endswith("Part.PcbLib")
    assert "ModelName0=PART-FOOTPRINT" in result.placement_parameters


def test_convergence_installs_then_verifies_in_a_second_session_before_receipting(tmp_path):
    calls: list[str] = []
    driver = _Driver(tmp_path)
    receipt = tmp_path / "machine" / "receipts.json"
    target = _dblib(tmp_path)

    def installer(*_args, **_kwargs):
        calls.append("install")
        return InstallResult("ok", "installed")

    def verifier(*_args, **_kwargs):
        calls.append("verify")
        return _placeable()

    first = converge_altium_library(
        target,
        receipt_path=receipt,
        driver=driver,
        workdir=tmp_path / "work",
        installer=installer,
        verifier=verifier,
    )
    second = converge_altium_library(
        target,
        receipt_path=receipt,
        driver=driver,
        workdir=tmp_path / "work",
        installer=installer,
        verifier=verifier,
    )

    assert calls == ["install", "verify"]
    assert first.status == "verified"
    assert first.component_key == "TPD6E05U06RVZR"
    assert second.status == "already-verified"
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert payload["schema"] == 1
    assert payload["libraries"][0]["evidence"]["component_key"] == "TPD6E05U06RVZR"


def test_failed_fresh_session_proof_never_writes_a_receipt(tmp_path):
    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"

    result = converge_altium_library(
        _dblib(tmp_path),
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult("ok", "installed"),
        verifier=lambda *_args, **_kwargs: PersistenceVerification("not-placeable", "no footprint"),
    )

    assert result.status == "not-placeable"
    assert not receipt.exists()


def test_profile_switch_removes_only_receipted_dblib_and_can_switch_back(tmp_path):
    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"
    old = _dblib(tmp_path / "Old")
    new = _dblib(tmp_path / "New")
    user_library = _dblib(tmp_path / "User")
    calls: list[tuple[str, Path]] = []

    def installer(path, *, uninstall=False, **_kwargs):
        target = Path(path)
        calls.append(("uninstall" if uninstall else "install", target))
        return InstallResult("ok", "removed" if uninstall else "installed")

    def verifier(path, **_kwargs):
        target = Path(path)
        calls.append(("verify", target))
        return _placeable(installed_paths=(str(target), str(user_library)))

    first = converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )
    assert first.ok

    calls.clear()
    switched = converge_altium_library(
        new,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )

    assert switched.status == "verified"
    assert calls == [
        ("install", new),
        ("verify", new),
        ("uninstall", old),
        ("verify", new),
    ]
    assert ("uninstall", user_library) not in calls
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert [Path(item["dblib"]) for item in payload["libraries"]] == [new]

    calls.clear()
    switched_back = converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )

    assert switched_back.status == "verified"
    assert calls == [
        ("install", old),
        ("verify", old),
        ("uninstall", new),
        ("verify", old),
    ]
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert [Path(item["dblib"]) for item in payload["libraries"]] == [old]


def test_empty_profile_removes_only_receipted_dblibs_and_clears_retry_authority(tmp_path):
    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"
    old = _dblib(tmp_path / "Old")
    user_library = _dblib(tmp_path / "User")
    converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult("ok", "installed"),
        verifier=lambda path, **_kwargs: _placeable(installed_paths=(str(path),)),
    )
    calls: list[tuple[str, Path]] = []

    def installer(path, *, uninstall=False, **_kwargs):
        target = Path(path)
        calls.append(("uninstall" if uninstall else "install", target))
        return InstallResult("ok", "removed")

    result = converge_altium_library(
        None,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        absence_verifier=lambda *_args, **_kwargs: PersistenceVerification(
            "ok",
            "receipted paths absent",
            installed_paths=(str(user_library),),
        ),
    )

    assert result.status == "no-library"
    assert result.ok
    assert calls == [("uninstall", old)]
    assert ("uninstall", user_library) not in calls
    assert json.loads(receipt.read_text(encoding="utf-8"))["libraries"] == []


def test_empty_profile_cleanup_failure_preserves_the_receipt_for_retry(tmp_path):
    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"
    old = _dblib(tmp_path / "Old")
    converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult("ok", "installed"),
        verifier=lambda path, **_kwargs: _placeable(installed_paths=(str(path),)),
    )
    previous_receipt = receipt.read_bytes()

    result = converge_altium_library(
        None,
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult(
            "not-installed",
            "Altium still lists the old profile",
        ),
        absence_verifier=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("absence verification must wait for successful cleanup")
        ),
    )

    assert result.status == "cleanup-failed"
    assert not result.ok
    assert receipt.read_bytes() == previous_receipt


def test_empty_profile_receipt_replace_failure_preserves_retry_authority(tmp_path, monkeypatch):
    from stockroom.altium import convergence as convergence_mod

    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"
    old = _dblib(tmp_path / "Old")
    converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult("ok", "installed"),
        verifier=lambda path, **_kwargs: _placeable(installed_paths=(str(path),)),
    )
    previous_receipt = receipt.read_bytes()
    monkeypatch.setattr(
        convergence_mod.os,
        "replace",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    result = converge_altium_library(
        None,
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult("ok", "removed"),
        absence_verifier=lambda *_args, **_kwargs: PersistenceVerification(
            "ok",
            "receipted paths absent",
        ),
    )

    assert result.status == "receipt-failed"
    assert not result.ok
    assert receipt.read_bytes() == previous_receipt
    assert not tuple(receipt.parent.glob(f".{receipt.name}.*.tmp"))


def test_matching_target_receipt_cannot_hide_an_obsolete_receipted_duplicate(tmp_path):
    driver = _Driver(tmp_path)
    old = _dblib(tmp_path / "Old")
    new = _dblib(tmp_path / "New")
    old_receipt = tmp_path / "old-receipt.json"
    new_receipt = tmp_path / "new-receipt.json"
    installer = lambda *_args, **_kwargs: InstallResult("ok", "completed")
    verifier = lambda path, **_kwargs: _placeable(installed_paths=(str(path),))

    converge_altium_library(
        old,
        receipt_path=old_receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )
    converge_altium_library(
        new,
        receipt_path=new_receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )
    old_item = json.loads(old_receipt.read_text(encoding="utf-8"))["libraries"][0]
    new_item = json.loads(new_receipt.read_text(encoding="utf-8"))["libraries"][0]
    combined = {"schema": 1, "libraries": [old_item, new_item]}
    receipt = tmp_path / "receipts.json"
    receipt.write_text(json.dumps(combined), encoding="utf-8")
    calls: list[tuple[str, Path]] = []

    def observed_installer(path, *, uninstall=False, **_kwargs):
        target = Path(path)
        calls.append(("uninstall" if uninstall else "install", target))
        return InstallResult("ok", "completed")

    result = converge_altium_library(
        new,
        receipt_path=receipt,
        driver=driver,
        installer=observed_installer,
        verifier=verifier,
    )

    assert result.status == "verified"
    assert calls == [("install", new), ("uninstall", old)]
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert [Path(item["dblib"]) for item in payload["libraries"]] == [new]


def test_cleanup_failure_restores_last_receipted_target_and_keeps_retry_authority(tmp_path):
    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"
    old = _dblib(tmp_path / "Old")
    new = _dblib(tmp_path / "New")

    converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult("ok", "installed"),
        verifier=lambda path, **_kwargs: _placeable(installed_paths=(str(path),)),
    )
    previous_receipt = receipt.read_bytes()
    calls: list[tuple[str, Path]] = []

    def failing_installer(path, *, uninstall=False, **_kwargs):
        target = Path(path)
        calls.append(("uninstall" if uninstall else "install", target))
        if uninstall and target == old:
            return InstallResult("not-installed", "Altium still lists the previous profile")
        return InstallResult("ok", "completed")

    def verifier(path, **_kwargs):
        target = Path(path)
        calls.append(("verify", target))
        return _placeable(installed_paths=(str(target),))

    failed = converge_altium_library(
        new,
        receipt_path=receipt,
        driver=driver,
        installer=failing_installer,
        verifier=verifier,
    )

    assert failed.status == "cleanup-failed"
    assert not failed.ok
    assert calls == [
        ("install", new),
        ("verify", new),
        ("uninstall", old),
        ("install", old),
        ("verify", old),
        ("uninstall", new),
        ("verify", old),
    ]
    assert receipt.read_bytes() == previous_receipt

    retry_calls: list[tuple[str, Path]] = []

    def healthy_installer(path, *, uninstall=False, **_kwargs):
        target = Path(path)
        retry_calls.append(("uninstall" if uninstall else "install", target))
        return InstallResult("ok", "completed")

    retried = converge_altium_library(
        new,
        receipt_path=receipt,
        driver=driver,
        installer=healthy_installer,
        verifier=lambda path, **_kwargs: _placeable(installed_paths=(str(path),)),
    )

    assert retried.status == "verified"
    assert retry_calls == [("install", new), ("uninstall", old)]
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert [Path(item["dblib"]) for item in payload["libraries"]] == [new]


def test_failed_candidate_proof_restores_receipted_target_before_any_cleanup(tmp_path):
    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"
    old = _dblib(tmp_path / "Old")
    new = _dblib(tmp_path / "New")
    converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult("ok", "completed"),
        verifier=lambda path, **_kwargs: _placeable(installed_paths=(str(path),)),
    )
    previous_receipt = receipt.read_bytes()
    calls: list[tuple[str, Path]] = []

    def installer(path, *, uninstall=False, **_kwargs):
        target = Path(path)
        calls.append(("uninstall" if uninstall else "install", target))
        return InstallResult("ok", "completed")

    def verifier(path, **_kwargs):
        target = Path(path)
        calls.append(("verify", target))
        if target == new:
            return PersistenceVerification("not-placeable", "candidate has no footprint")
        return _placeable(installed_paths=(str(target),))

    result = converge_altium_library(
        new,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )

    assert result.status == "not-placeable"
    assert calls == [
        ("install", new),
        ("verify", new),
        ("install", old),
        ("verify", old),
        ("uninstall", new),
        ("verify", old),
    ]
    assert receipt.read_bytes() == previous_receipt


def test_failed_post_cleanup_proof_rolls_back_before_receipt_commit(tmp_path):
    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"
    old = _dblib(tmp_path / "Old")
    new = _dblib(tmp_path / "New")

    converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=lambda *_args, **_kwargs: InstallResult("ok", "completed"),
        verifier=lambda path, **_kwargs: _placeable(installed_paths=(str(path),)),
    )
    previous_receipt = receipt.read_bytes()
    calls: list[tuple[str, Path]] = []
    candidate_verifications = 0

    def installer(path, *, uninstall=False, **_kwargs):
        target = Path(path)
        calls.append(("uninstall" if uninstall else "install", target))
        return InstallResult("ok", "completed")

    def verifier(path, **_kwargs):
        nonlocal candidate_verifications
        target = Path(path)
        calls.append(("verify", target))
        if target == new:
            candidate_verifications += 1
            if candidate_verifications == 2:
                return PersistenceVerification("not-installed", "candidate disappeared")
        return _placeable(installed_paths=(str(target),))

    result = converge_altium_library(
        new,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )

    assert result.status == "cleanup-failed"
    assert calls == [
        ("install", new),
        ("verify", new),
        ("uninstall", old),
        ("verify", new),
        ("install", old),
        ("verify", old),
        ("uninstall", new),
        ("verify", old),
    ]
    assert receipt.read_bytes() == previous_receipt


def test_atomic_receipt_replace_failure_restores_previous_target(
    tmp_path,
    monkeypatch,
):
    from stockroom.altium import convergence as convergence_mod

    driver = _Driver(tmp_path)
    receipt = tmp_path / "receipts.json"
    old = _dblib(tmp_path / "Old")
    new = _dblib(tmp_path / "New")
    installer = lambda *_args, **_kwargs: InstallResult("ok", "completed")
    verifier = lambda path, **_kwargs: _placeable(installed_paths=(str(path),))

    converge_altium_library(
        old,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )
    previous_receipt = receipt.read_bytes()
    calls: list[tuple[str, Path]] = []

    def observed_installer(path, *, uninstall=False, **_kwargs):
        target = Path(path)
        calls.append(("uninstall" if uninstall else "install", target))
        return InstallResult("ok", "completed")

    def fail_replace(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(convergence_mod.os, "replace", fail_replace)
    result = converge_altium_library(
        new,
        receipt_path=receipt,
        driver=driver,
        installer=observed_installer,
        verifier=verifier,
    )

    assert result.status == "cleanup-failed"
    assert calls == [
        ("install", new),
        ("uninstall", old),
        ("install", old),
        ("uninstall", new),
    ]
    assert receipt.read_bytes() == previous_receipt
    assert not tuple(receipt.parent.glob(f".{receipt.name}.*.tmp"))


def test_an_altium_binary_change_invalidates_the_old_receipt(tmp_path):
    calls: list[str] = []
    driver = _Driver(tmp_path)
    target = _dblib(tmp_path)
    receipt = tmp_path / "receipts.json"

    def installer(*_args, **_kwargs):
        calls.append("install")
        return InstallResult("already", "installed")

    def verifier(*_args, **_kwargs):
        calls.append("verify")
        return _placeable()

    converge_altium_library(
        target,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )
    driver.x2.write_bytes(b"MZ-new-build")
    result = converge_altium_library(
        target,
        receipt_path=receipt,
        driver=driver,
        installer=installer,
        verifier=verifier,
    )

    assert result.status == "verified"
    assert calls == ["install", "verify", "install", "verify"]
    payload = json.loads(receipt.read_text(encoding="utf-8"))
    assert len(payload["libraries"]) == 1


def test_background_owner_uses_the_current_profile_path_on_every_pass(tmp_path, monkeypatch):
    profile = SimpleNamespace(root=tmp_path / "First")
    seen: list[Path | None] = []

    def converge(target, **_kwargs):
        from stockroom.altium.convergence import AltiumConvergenceResult

        seen.append(target)
        return AltiumConvergenceResult("no-library", "nothing generated")

    monkeypatch.setattr("stockroom.altium.convergence.converge_altium_library", converge)
    service = AltiumLibraryConvergenceService(
        lambda: Path(profile.root) / "altium" / "Stockroom.DbLib",
        driver_factory=lambda: _Driver(tmp_path),
    )

    service.run_once()
    profile.root = tmp_path / "Second"
    service.run_once()

    assert seen == [
        tmp_path / "First" / "altium" / "Stockroom.DbLib",
        tmp_path / "Second" / "altium" / "Stockroom.DbLib",
    ]


def test_native_host_starts_a_dynamic_profile_convergence_owner(tmp_path, monkeypatch):
    from stockroom.altium import convergence as convergence_mod
    from stockroom.host import run as run_mod

    services = []

    class _Service:
        def __init__(self, target, *, result_sink):
            self.target = target
            self.result_sink = result_sink
            self.started = False
            services.append(self)

        def start(self):
            self.started = True

    monkeypatch.setattr(convergence_mod, "AltiumLibraryConvergenceService", _Service)
    ctx = SimpleNamespace(profile=SimpleNamespace(root=tmp_path / "A"))

    service = run_mod._start_altium_library_convergence(ctx)

    assert service is services[0]
    assert service.started
    assert service.target() == tmp_path / "A" / "altium" / "Stockroom.DbLib"
    ctx.profile = SimpleNamespace(root=tmp_path / "B")
    assert service.target() == tmp_path / "B" / "altium" / "Stockroom.DbLib"
    result = object()
    service.result_sink(result)
    assert ctx.last_altium_convergence is result
