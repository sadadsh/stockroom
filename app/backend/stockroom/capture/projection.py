"""Read back the active library projection before calling a part CAD-ready.

Immutable evidence proves what Stockroom retained. This module proves that the active profile
still contains the corresponding usable files and entry bindings. It is deliberately read-only
and never launches KiCad or Altium.
"""

from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path, PurePosixPath
from typing import cast

import olefile

from stockroom.cad_variants import ResolvedCadVariant
from stockroom.capture.cross_eda import (
    read_altium_footprint,
    read_altium_symbol,
    read_kicad_footprint,
    read_kicad_symbol,
    verify_cross_eda_component,
    verify_kicad_component,
)
from stockroom.capture.evidence import exact_identity, proved_kicad_pad_allowance
from stockroom.model.part import PartRecord


class InstalledProjectionError(ValueError):
    """The record/evidence pointer does not resolve to one usable active projection."""


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}\Z")
_PUBLICATION_SCHEMA = "stockroom.production-publication/1"


def _publication_row(record: object) -> dict[str, object]:
    extra = getattr(record, "extra", None)
    publication = extra.get("production_publication") if isinstance(extra, dict) else None
    if not isinstance(publication, dict) or publication.get("schema") != _PUBLICATION_SCHEMA:
        return {}
    row = publication.get("catalog_row")
    return row if isinstance(row, dict) else {}


def _published_file(root: Path, record: object, column: str) -> Path | None:
    raw = _publication_row(record).get(column)
    if not isinstance(raw, str) or not raw.strip():
        return None
    relative = PurePosixPath(raw)
    if relative.is_absolute() or ".." in relative.parts or ":" in relative.parts[0]:
        raise InstalledProjectionError(f"published {column} is not profile-relative")
    return root / Path(*relative.parts)


def _altium_file(root: Path, container: str) -> Path:
    relative = PurePosixPath(container)
    if relative.is_absolute() or ".." in relative.parts or ":" in relative.parts[0]:
        raise InstalledProjectionError("installed Altium container path is unsafe")
    if len(relative.parts) > 1:
        return root / Path(*relative.parts)
    return root / "altium" / relative.name


def _published_digest(record: object, column: str) -> str:
    value = _publication_row(record).get(column)
    return value if isinstance(value, str) and _DIGEST.fullmatch(value) else ""


def _required_file(root: Path, path: Path, label: str) -> Path:
    root = Path(root).resolve(strict=True)
    candidate = Path(path)
    try:
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise InstalledProjectionError(f"installed {label} is missing") from exc
    if not resolved.is_relative_to(root):
        raise InstalledProjectionError(f"installed {label} escaped the active library")
    current = candidate
    while current != root and current.is_relative_to(root):
        if current.is_symlink():
            raise InstalledProjectionError(f"installed {label} is linked")
        current = current.parent
    if not resolved.is_file() or resolved.stat().st_size <= 0:
        raise InstalledProjectionError(f"installed {label} is not a non-empty file")
    return resolved


def _same_bytes(path: Path, data: bytes, label: str) -> None:
    observed = hashlib.sha256(path.read_bytes()).digest()
    expected = hashlib.sha256(data).digest()
    if observed != expected:
        raise InstalledProjectionError(
            f"installed {label} bytes do not match the active evidence artifact"
        )


def _ole_payload_digest(source: Path | bytes) -> bytes:
    handle = source if isinstance(source, Path) else io.BytesIO(source)
    digest = hashlib.sha256()
    with olefile.OleFileIO(handle) as container:
        streams = sorted(tuple(parts) for parts in container.listdir(streams=True, storages=False))
        for parts in streams:
            name = "/".join(parts).encode("utf-8")
            data = container.openstream(list(parts)).read()
            if parts == ("FileHeader",):
                # Altium assigns a fresh eight-character document UniqueID when the same SchLib
                # is saved under its canonical library filename. It is container bookkeeping,
                # not a symbol/component identity; every component stream remains byte-bound.
                data = re.sub(
                    rb"\|UniqueID=[^|\x00]*",
                    b"|UniqueID=<document>",
                    data,
                    count=1,
                )
            digest.update(len(name).to_bytes(4, "big"))
            digest.update(name)
            digest.update(len(data).to_bytes(8, "big"))
            digest.update(data)
    return digest.digest()


def _same_ole_payload(path: Path, data: bytes, label: str) -> None:
    try:
        equal = _ole_payload_digest(path) == _ole_payload_digest(data)
    except Exception as exc:
        raise InstalledProjectionError(f"installed {label} is not a readable native library") from exc
    if not equal:
        raise InstalledProjectionError(
            f"installed {label} native streams do not match the active evidence artifact"
        )


def _matches_digest(path: Path, digest: str, label: str) -> None:
    if digest and "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise InstalledProjectionError(
            f"installed {label} bytes do not match the published artifact digest"
        )


def _proved_unrepresented_pads(
    validation_reports: dict[str, dict[str, object]] | None,
) -> frozenset[str]:
    """Read only the pad allowance retained by immutable native verification."""

    validation = (validation_reports or {}).get("kicad")
    if validation is None:
        return frozenset()
    try:
        return proved_kicad_pad_allowance(validation)
    except ValueError as exc:
        raise InstalledProjectionError("immutable KiCad pad allowance is invalid") from exc


def verify_installed_projection(
    library,
    record: object,
    resolved: dict[str, ResolvedCadVariant],
    *,
    validation_reports: dict[str, dict[str, object]] | None = None,
) -> None:
    """Prove the five current record bindings against files in the active profile.

    KiCad symbol/footprint files are normalized while installing, so their usable entry, identity,
    pins, pads, model link, and cross-EDA geometry are read back semantically. The STEP and SchLib
    are stored verbatim and are additionally digest-compared. A PcbLib can legitimately gain the
    exact STEP body during atomic materialization; its native entries/pads/model are therefore
    proved by the same independent cross-EDA reader instead of whole-container byte equality.
    """

    if not resolved:
        raise InstalledProjectionError("no active CAD evidence was resolved")
    record = cast(PartRecord, record)
    root = Path(library.root)
    if not root.is_dir() or root.is_symlink():
        raise InstalledProjectionError("the active library root is missing or linked")

    identity = exact_identity(record)
    kicad = record.assets_for("kicad")
    altium = record.assets_for("altium")

    kicad_paths: tuple[Path, Path, Path] | None = None
    kicad_symbol_name = ""
    kicad_footprint_name = ""
    if "kicad" in resolved:
        if kicad.symbol is None or kicad.footprint is None or kicad.model is None:
            raise InstalledProjectionError("the active KiCad projection is incomplete")
        kicad_symbol_name = kicad.symbol.name
        kicad_footprint_name = kicad.footprint.name
        symbol_path = _required_file(
            root,
            _published_file(root, record, "KiCad Symbol Artifact Path")
            or library.symbol_lib_path(record.category),
            "KiCad symbol library",
        )
        footprint_path = _required_file(
            root,
            _published_file(root, record, "KiCad Footprint Artifact Path")
            or (
                library.footprint_lib_path(record.category)
                / f"{kicad.footprint.name}.kicad_mod"
            ),
            "KiCad footprint",
        )
        model_path = _required_file(root, root / kicad.model.file, "STEP model")
        _same_bytes(model_path, resolved["kicad"].data["model"], "STEP model")
        _matches_digest(
            symbol_path,
            _published_digest(record, "KiCad Symbol Artifact Digest"),
            "KiCad symbol library",
        )
        _matches_digest(
            footprint_path,
            _published_digest(record, "KiCad Footprint Artifact Digest"),
            "KiCad footprint",
        )
        symbol_readback = read_kicad_symbol(symbol_path, kicad.symbol.name)
        footprint_readback = read_kicad_footprint(footprint_path, model_path)
        if symbol_readback.entry != kicad.symbol.name:
            raise InstalledProjectionError("installed KiCad symbol entry does not match the record")
        if footprint_readback.entry != kicad.footprint.name:
            raise InstalledProjectionError(
                "installed KiCad footprint entry does not match the record"
            )
        allowed_unrepresented = _proved_unrepresented_pads(validation_reports)
        verify_kicad_component(
            identity=identity,
            kicad_symbol=symbol_path,
            kicad_footprint=footprint_path,
            step_model=model_path,
            allowed_unrepresented_pads=allowed_unrepresented,
        )
        kicad_paths = (symbol_path, footprint_path, model_path)

    if "altium" in resolved:
        if altium.symbol is None or altium.footprint is None:
            raise InstalledProjectionError("the active Altium projection is incomplete")
        symbol_path = _required_file(
            root,
            _altium_file(root, altium.symbol.lib),
            "Altium symbol library",
        )
        footprint_path = _required_file(
            root,
            _altium_file(root, altium.footprint.lib),
            "Altium footprint library",
        )
        symbol_digest = _published_digest(record, "Altium Symbol Artifact Digest")
        footprint_digest = _published_digest(record, "Altium Footprint Artifact Digest")
        _matches_digest(symbol_path, symbol_digest, "Altium symbol library")
        _matches_digest(footprint_path, footprint_digest, "Altium footprint library")
        if not symbol_digest:
            # OLE directory timestamps legitimately change when the same native streams are
            # copied/saved. Compare every named stream and its bytes, not container bookkeeping.
            _same_ole_payload(
                symbol_path,
                resolved["altium"].data["symbol"],
                "Altium symbol library",
            )
        try:
            symbol_readback = read_altium_symbol(symbol_path, altium.symbol.name)
            footprint_readback = read_altium_footprint(footprint_path, altium.footprint.name)
        except Exception as exc:
            raise InstalledProjectionError(
                "installed Altium entries are unreadable or unbound"
            ) from exc
        if symbol_readback.entry != altium.symbol.name:
            raise InstalledProjectionError(
                "installed Altium symbol entry does not match the active record binding"
            )
        if footprint_readback.entry != altium.footprint.name:
            raise InstalledProjectionError(
                "installed Altium footprint entry does not match the active record binding"
            )
        if kicad_paths is None:
            if not footprint_digest:
                _same_ole_payload(
                    footprint_path,
                    resolved["altium"].data["footprint"],
                    "Altium footprint library",
                )
            return

        report = verify_cross_eda_component(
            identity=identity,
            kicad_symbol=kicad_paths[0],
            kicad_footprint=kicad_paths[1],
            step_model=kicad_paths[2],
            altium_sources=(symbol_path, footprint_path),
            altium_identity_attestation=identity,
            altium_footprint_entry=altium.footprint.name,
        )
        kicad_report = report.get("kicad")
        altium_report = report.get("altium")
        if not isinstance(kicad_report, dict) or not isinstance(altium_report, dict):
            raise InstalledProjectionError("installed cross-EDA readback returned no bindings")
        expected = (
            (kicad_report.get("symbol_entry"), kicad_symbol_name, "KiCad symbol"),
            (kicad_report.get("footprint_entry"), kicad_footprint_name, "KiCad footprint"),
            (altium_report.get("symbol_entry"), altium.symbol.name, "Altium symbol"),
            (altium_report.get("footprint_entry"), altium.footprint.name, "Altium footprint"),
        )
        for observed, wanted, label in expected:
            if observed != wanted:
                raise InstalledProjectionError(
                    f"installed {label} entry does not match the active record binding"
                )


__all__ = ["InstalledProjectionError", "verify_installed_projection"]
