"""Permissive, user-selected CAD intake for an existing component.

The person has already chosen both the component and the files.  Stockroom therefore treats each
input as a bag of possible assets: unpack safely, attach every role that can be mapped, ignore the
rest, and report the component's remaining roles.  One irrelevant sibling never rejects a useful
symbol, footprint, model, SchLib, or PcbLib.
"""

from __future__ import annotations

import tempfile
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from stockroom.altium.extract import normalize_altium_source
from stockroom.altium.ul_import import (
    UltraLibrarianImportError,
    convert_ul_altium_package,
)
from stockroom.capture.identity import same_mpn
from stockroom.capture.requirements import Requirement, capture_needs
from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.sandbox import unpack_inputs
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.asset import AssetOrigin

_ALTIUM_SUFFIXES = frozenset({".schlib", ".pcblib", ".intlib"})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _candidate_values(candidate: StagingCandidate) -> tuple[str, ...]:
    return tuple(
        value.strip()
        for value in (
            candidate.mpn,
            candidate.symbol_name,
            candidate.entry_name,
            candidate.display_name,
        )
        if isinstance(value, str) and value.strip()
    )


def _candidate_score(candidate: StagingCandidate) -> int:
    return sum(
        (
            candidate.symbol_lib_path is not None,
            bool(candidate.footprint_variants),
            candidate.model_path is not None,
        )
    )


def _select_candidate(record, candidates: list[StagingCandidate]) -> tuple[StagingCandidate | None, str]:
    """Prefer exact internal MPN; otherwise accept one unambiguous user-selected candidate."""

    exact = [
        candidate
        for candidate in candidates
        if any(same_mpn(value, record.mpn) for value in _candidate_values(candidate))
    ]
    pool = exact or candidates
    if not pool:
        return None, ""
    best_score = max(_candidate_score(candidate) for candidate in pool)
    best = [candidate for candidate in pool if _candidate_score(candidate) == best_score]
    if len(best) != 1:
        return None, (
            f"ignored {len(best)} equally complete CAD candidates because none uniquely maps "
            f"to {record.mpn}"
        )
    return best[0], ""


def _missing_values(record) -> set[str]:
    return {need.value for need in capture_needs(record)}


def _only_missing_kicad(record, candidate: StagingCandidate) -> StagingCandidate:
    missing = _missing_values(record)
    return replace(
        candidate,
        symbol_lib_path=(
            candidate.symbol_lib_path
            if Requirement.KICAD_SYMBOL.value in missing
            else None
        ),
        symbol_name=(
            candidate.symbol_name
            if Requirement.KICAD_SYMBOL.value in missing
            else ""
        ),
        footprint_variants=(
            list(candidate.footprint_variants)
            if Requirement.KICAD_FOOTPRINT.value in missing
            else []
        ),
        model_path=(
            candidate.model_path
            if Requirement.KICAD_MODEL.value in missing
            else None
        ),
        entry_name=record.mpn or candidate.entry_name or candidate.symbol_name,
        category=record.category,
    )


def _has_kicad_payload(candidate: StagingCandidate) -> bool:
    return bool(
        candidate.symbol_lib_path is not None
        or candidate.footprint_variants
        or candidate.model_path is not None
    )


def _discover_native_altium(inputs: tuple[Path, ...], root: Path) -> list[Path]:
    found: list[Path] = []
    for unpacked in unpack_inputs(list(inputs), root):
        found.extend(
            path
            for path in sorted(unpacked.root.rglob("*"))
            if path.is_file() and path.suffix.casefold() in _ALTIUM_SUFFIXES
        )
    return found


def import_manual_cad_files(ctx, part_id: str, paths: tuple[Path, ...]) -> dict:
    """Attach every useful selected CAD role and return an honest readback report."""

    if not paths:
        raise ValueError("select at least one CAD file")
    record = ctx.ops.load_record(part_id)
    before = _missing_values(record)
    messages: list[str] = []
    origin = AssetOrigin(vendor="manual", extra={"selected_by_user": True})
    stamp = _now_iso()

    with IngestPipeline(
        ctx.profile,
        ctx.repo,
        ctx.cli,
        auto_embed_altium_models=True,
    ) as pipeline:
        # Inspect the whole selection together so a symbol ZIP, footprint file, and loose STEP
        # can merge into one candidate. IngestPipeline already isolates each input and discards
        # individual failures when at least one sibling is useful.
        try:
            candidates = pipeline.inspect(inputs=paths)
        except Exception as exc:  # noqa: BLE001 - Altium siblings may still be useful
            candidates = []
            messages.append(f"KiCad/STEP discovery found no usable content: {exc}")
        candidate, selection_note = _select_candidate(record, candidates)
        if selection_note:
            messages.append(selection_note)
        if candidate is not None:
            useful = _only_missing_kicad(record, candidate)
            if _has_kicad_payload(useful):
                try:
                    pipeline.attach_assets(
                        part_id,
                        useful,
                        origin=origin,
                        now_iso=stamp,
                    )
                except Exception as exc:  # noqa: BLE001 - Altium siblings may still be useful
                    messages.append(f"KiCad/STEP content was not attached: {exc}")

        with tempfile.TemporaryDirectory(prefix="sr-manual-altium-") as td:
            materialized = None
            native: list[Path] = []
            try:
                native = _discover_native_altium(paths, Path(td) / "Native")
            except Exception as exc:  # noqa: BLE001 - candidate intake already handled each file
                messages.append(f"native Altium discovery skipped: {exc}")
            if not native:
                try:
                    materialized = convert_ul_altium_package(
                        paths,
                        expected_manufacturer=record.manufacturer,
                        expected_mpn=record.mpn,
                        allow_altium=False,
                    )
                except (UltraLibrarianImportError, ValueError) as exc:
                    messages.append(str(exc))
                if materialized is not None:
                    native = list(materialized.libraries)
            try:
                if native:
                    sch, pcb = normalize_altium_source(*native, out_dir=Path(td) / "Extracted")
                    current = ctx.ops.load_record(part_id)
                    missing = _missing_values(current)
                    useful_native = [
                        path
                        for path, requirement in (
                            (sch, Requirement.ALTIUM_SYMBOL.value),
                            (pcb, Requirement.ALTIUM_FOOTPRINT.value),
                        )
                        if path is not None and requirement in missing
                    ]
                    if useful_native:
                        ctx.ops.attach_altium_assets(
                            part_id,
                            *useful_native,
                            origin=origin,
                            now_iso=stamp,
                        )
            except Exception as exc:  # noqa: BLE001 - return every other useful attachment
                messages.append(f"Altium content was not attached: {exc}")
            finally:
                cleanup = getattr(materialized, "cleanup", None)
                if callable(cleanup):
                    cleanup()

    current = ctx.ops.load_record(part_id)
    remaining = _missing_values(current)
    attached = sorted(before - remaining)
    ignored = [message for message in messages if message]
    return {
        "part_id": part_id,
        "selected_files": len(paths),
        "attached": attached,
        "ignored": ignored,
        "remaining": sorted(remaining),
        "complete": not remaining,
    }
