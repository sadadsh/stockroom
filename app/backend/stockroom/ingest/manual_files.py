"""Permissive, user-selected CAD intake for an existing component.

The person has already chosen both the component and the files.  Stockroom therefore treats each
input as a bag of possible assets: unpack safely, attach every role that can be mapped, ignore the
rest, and report the component's remaining roles.  One irrelevant sibling never rejects a useful
symbol, footprint, model, SchLib, or PcbLib.
"""

from __future__ import annotations

import hashlib
import secrets
import shutil
import tempfile
import threading
import time
import unicodedata
from collections import Counter, OrderedDict
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict

from stockroom.altium.extract import normalize_altium_source
from stockroom.altium.oleread import read_footprint_names, read_symbol_names
from stockroom.altium.ul_import import (
    UltraLibrarianImportError,
    convert_ul_altium_package,
)
from stockroom.capture.requirements import Requirement, capture_needs
from stockroom.ingest.errors import IngestError
from stockroom.ingest.naming import propose_entry_name
from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.sandbox import unpack_inputs
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.asset import AssetOrigin

_ALTIUM_SUFFIXES = frozenset({".schlib", ".pcblib", ".intlib"})
_PROPOSAL_TTL_SECONDS = 30 * 60
_PROPOSAL_LIMIT = 32
_proposal_lock = threading.RLock()


class _ManualCadProposalEntry(TypedDict):
    part_id: str
    root: Path
    paths: tuple[Path, ...]
    landed_names: tuple[str, ...]
    edas: tuple[str, ...]
    digests: tuple[str, ...]
    created: float


_proposals: OrderedDict[str, _ManualCadProposalEntry] = OrderedDict()


def _expire_manual_cad_proposals(now: float) -> list[_ManualCadProposalEntry]:
    expired = [
        token
        for token, entry in _proposals.items()
        if now - float(entry["created"]) >= _PROPOSAL_TTL_SECONDS
    ]
    return [_proposals.pop(token) for token in expired]


def _cleanup_proposal_entry(entry: _ManualCadProposalEntry) -> None:
    shutil.rmtree(entry["root"], ignore_errors=True)


def _snapshot_selected_files(
    paths: tuple[Path, ...],
) -> tuple[Path, tuple[Path, ...], tuple[str, ...]]:
    """Copy selected bytes once into one proposal-owned root without reopening them later."""

    root = Path(tempfile.mkdtemp(prefix="sr-manual-cad-proposal-"))
    snapshots: list[Path] = []
    landed_names: list[str] = []
    try:
        for index, raw_path in enumerate(paths):
            source = Path(raw_path)
            if source.is_symlink() or not source.is_file():
                raise ValueError("every selected CAD path must be a real file")
            destination_dir = root / f"{index:04d}"
            destination_dir.mkdir()
            destination = destination_dir / source.name
            with source.open("rb") as incoming, destination.open("xb") as outgoing:
                shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            snapshots.append(destination)
            landed_names.append(source.name)
        return root, tuple(snapshots), tuple(landed_names)
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise


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


def _exact_mpn_key(value: str) -> str:
    """Normalize presentation case and Unicode while preserving every MPN punctuation mark."""

    return unicodedata.normalize("NFKC", value or "").strip().casefold()


def _select_candidate(
    record,
    candidates: list[StagingCandidate],
) -> tuple[StagingCandidate | None, str, bool]:
    """Select review content while separately proving automatic-Apply identity."""

    requested = _exact_mpn_key(record.mpn)
    exact = [
        candidate
        for candidate in candidates
        if requested
        and any(_exact_mpn_key(value) == requested for value in _candidate_values(candidate))
    ]
    pool = exact or candidates
    if not pool:
        return (
            None,
            (
                f"Review required: downloaded CAD does not contain a parsed MPN bound exactly "
                f"to {record.mpn!r}."
            ),
            False,
        )
    best_score = max(_candidate_score(candidate) for candidate in pool)
    best = [candidate for candidate in pool if _candidate_score(candidate) == best_score]
    if len(best) != 1:
        return (
            None,
            (
                f"Review required: {len(best)} equally complete CAD candidates do not uniquely "
                f"map to {record.mpn!r}."
            ),
            False,
        )
    candidate = best[0]
    if candidate in exact:
        return candidate, "", True
    observed = _candidate_values(candidate)
    identity = ", ".join(repr(value) for value in observed) if observed else "no parsed MPN"
    return (
        candidate,
        (
            f"Review required: downloaded CAD identifies {identity}, not the exact "
            f"punctuation-preserving MPN {record.mpn!r}."
        ),
        False,
    )


def _missing_values(record) -> set[str]:
    return {need.value for need in capture_needs(record)}


def _only_missing_kicad(
    record,
    candidate: StagingCandidate,
    selected: set[Requirement],
) -> StagingCandidate:
    missing = _missing_values(record)
    return replace(
        candidate,
        symbol_lib_path=(
            candidate.symbol_lib_path
            if Requirement.KICAD_SYMBOL in selected
            and Requirement.KICAD_SYMBOL.value in missing
            else None
        ),
        symbol_name=(
            candidate.symbol_name
            if Requirement.KICAD_SYMBOL in selected
            and Requirement.KICAD_SYMBOL.value in missing
            else ""
        ),
        footprint_variants=(
            list(candidate.footprint_variants)
            if Requirement.KICAD_FOOTPRINT in selected
            and Requirement.KICAD_FOOTPRINT.value in missing
            else []
        ),
        model_path=(
            candidate.model_path
            if Requirement.KICAD_MODEL in selected
            and Requirement.KICAD_MODEL.value in missing
            else None
        ),
        entry_name=propose_entry_name(
            candidate.entry_name or candidate.symbol_name,
            record.mpn,
        ),
        category=record.category,
    )


def _has_kicad_payload(candidate: StagingCandidate) -> bool:
    return bool(
        candidate.symbol_lib_path is not None
        or candidate.footprint_variants
        or candidate.model_path is not None
    )


def _discover_native_altium(inputs: tuple[Path, ...], root: Path) -> list[Path]:
    """Native Altium libraries among the selected files.

    Each selection is unpacked on its own. The sandbox refuses an archive that carries
    provider script content, and one refused sibling must not discard a perfectly good
    ``.SchLib`` the person selected beside it -- the reviewed Ultra Librarian route below
    is what handles a script package, and it reports its own outcome.
    """

    found: list[Path] = []
    for index, selected in enumerate(inputs):
        try:
            unpacked = unpack_inputs([selected], root / str(index))
        except IngestError:
            continue
        for item in unpacked:
            found.extend(
                path
                for path in sorted(item.root.rglob("*"))
                if path.is_file() and path.suffix.casefold() in _ALTIUM_SUFFIXES
            )
    return found


def _file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _native_altium_exact_mpn(path: Path, expected_mpn: str) -> bool:
    """Prove one native library's authoritative entry name preserves the exact target MPN."""

    requested = _exact_mpn_key(expected_mpn)
    if not requested:
        return False
    try:
        suffix = path.suffix.casefold()
        if suffix == ".schlib":
            names = read_symbol_names(path)
        elif suffix == ".pcblib":
            names = read_footprint_names(path)
        else:
            return False
    except Exception:  # noqa: BLE001 - unreadable identity remains review-only
        return False
    return any(
        _exact_mpn_key(name.replace("&plus_", "+")) == requested
        for name in names
    )


def _proposal_target(requirement: Requirement) -> tuple[str, str]:
    return {
        Requirement.KICAD_SYMBOL: ("KiCad Symbol", "Active KiCad Symbol"),
        Requirement.KICAD_FOOTPRINT: ("KiCad Footprint", "Active KiCad Footprint"),
        Requirement.KICAD_MODEL: ("3D Model", "Shared 3D Model"),
        Requirement.ALTIUM_SYMBOL: ("Altium Symbol", "Active Altium Symbol"),
        Requirement.ALTIUM_FOOTPRINT: ("Altium Footprint", "Active Altium Footprint"),
    }[requirement]


def _selected_requirements(edas: tuple[str, ...]) -> set[Requirement]:
    selected = set(edas)
    if not selected or not selected <= {"kicad", "altium"}:
        raise ValueError("edas must select KiCad, Altium, or both")
    requirements = {Requirement.KICAD_MODEL}
    if "kicad" in selected:
        requirements.update({Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT})
    if "altium" in selected:
        requirements.update({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})
    return requirements


def _proposal_readiness(
    ctx,
    part_id: str,
    edas: tuple[str, ...],
    attachments: list[dict[str, str]],
) -> tuple[list[str], bool]:
    """Name selected roles that still lack one exact mapping.

    Zero mappings is partial and two mappings is ambiguous.  Only one mapping for every selected,
    currently-missing role is safe for provider-browser automatic Apply.
    """

    selected = _selected_requirements(edas)
    missing = _missing_values(ctx.ops.load_record(part_id))
    required = [
        requirement
        for requirement in Requirement
        if requirement in selected and requirement.value in missing
    ]
    mapped = Counter(
        item.get("role", "")
        for item in attachments
        if isinstance(item, dict) and type(item.get("role")) is str
    )
    remaining = [
        _proposal_target(requirement)[0]
        for requirement in required
        if mapped[_proposal_target(requirement)[0]] != 1
    ]
    return remaining, bool(required) and not remaining


def _manual_attachment_preview(
    ctx,
    part_id: str,
    paths: tuple[Path, ...],
    *,
    edas: tuple[str, ...],
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[str], list[str], str]:
    """Inspect selected bytes without calling an attachment or repository mutation seam."""

    selected = _selected_requirements(edas)
    record = ctx.ops.load_record(part_id)
    missing = {Requirement(value) for value in _missing_values(record)}
    attachments: list[dict[str, str]] = []
    inactive: list[dict[str, str]] = []
    ignored: list[str] = []
    identity_gaps: list[str] = []
    identity_reasons: list[str] = []

    def add(requirement: Requirement, path: Path) -> bool:
        role, target = _proposal_target(requirement)
        item = {"role": role, "file_name": path.name, "target": target}
        if requirement in selected and requirement in missing:
            # Distinct files remain distinct mappings even when providers reuse a basename.
            # Collapsing them would hide ambiguity and could auto-apply the wrong payload.
            attachments.append(item)
            return True
        elif requirement not in selected:
            evidence = {
                "tool": "altium" if requirement.value.startswith("altium_") else "kicad",
                "file_name": path.name,
            }
            if evidence not in inactive:
                inactive.append(evidence)
        return False

    def require_identity(label: str, reason: str) -> None:
        if label not in identity_gaps:
            identity_gaps.append(label)
        if reason and reason not in identity_reasons:
            identity_reasons.append(reason)

    with IngestPipeline(
        ctx.profile,
        ctx.repo,
        ctx.cli,
        auto_embed_altium_models=True,
    ) as pipeline:
        try:
            candidates = pipeline.inspect(inputs=paths)
        except Exception as exc:  # noqa: BLE001 - preview reports unreadable selections
            candidates = []
            ignored.append(f"KiCad/STEP discovery found no usable content: {exc}")
        candidate, note, identity_bound = _select_candidate(record, candidates)
        if note:
            ignored.append(note)
        if candidate is not None:
            candidate_contributed = False
            if candidate.symbol_lib_path is not None:
                candidate_contributed |= add(Requirement.KICAD_SYMBOL, candidate.symbol_lib_path)
            if candidate.chosen_footprint is not None:
                candidate_contributed |= add(
                    Requirement.KICAD_FOOTPRINT,
                    candidate.chosen_footprint,
                )
            if candidate.model_path is not None:
                candidate_contributed |= add(Requirement.KICAD_MODEL, candidate.model_path)
            if candidate_contributed and not identity_bound:
                require_identity("Exact MPN Identity", note)

    with tempfile.TemporaryDirectory(prefix="sr-manual-proposal-") as td:
        try:
            native = _discover_native_altium(paths, Path(td) / "Native")
        except Exception as exc:  # noqa: BLE001 - other proposal roles remain useful
            native = []
            ignored.append(f"native Altium discovery skipped: {exc}")
        unbound_native: list[str] = []
        for path in native:
            suffix = path.suffix.casefold()
            if suffix == ".schlib":
                contributed = add(Requirement.ALTIUM_SYMBOL, path)
            elif suffix in {".pcblib", ".intlib"}:
                contributed = add(Requirement.ALTIUM_FOOTPRINT, path)
            else:
                contributed = False
            if contributed and not _native_altium_exact_mpn(path, record.mpn):
                unbound_native.append(path.name)
        if unbound_native:
            names = ", ".join(sorted(set(unbound_native), key=str.casefold))
            require_identity(
                "Exact Altium Identity",
                (
                    f"Review required: native Altium files {names} do not expose the exact "
                    f"punctuation-preserving MPN {record.mpn!r}."
                ),
            )

    return attachments, inactive, ignored, identity_gaps, " ".join(identity_reasons)


def propose_manual_cad_files(
    ctx,
    part_id: str,
    paths: tuple[Path, ...],
    *,
    edas: tuple[str, ...],
) -> dict:
    """Return exact discovered mappings and retain immutable inputs until explicit Apply."""

    if not paths:
        raise ValueError("select at least one CAD file")
    _selected_requirements(edas)
    root, snapshots, landed_names = _snapshot_selected_files(paths)
    try:
        digests = tuple(_file_digest(path) for path in snapshots)
        attachments, inactive, ignored, identity_gaps, identity_reason = (
            _manual_attachment_preview(
                ctx,
                part_id,
                snapshots,
                edas=edas,
            )
        )
        if tuple(_file_digest(path) for path in snapshots) != digests:
            raise ValueError("a proposal-owned CAD snapshot changed during inspection")
        remaining_roles, _roles_ready = _proposal_readiness(
            ctx,
            part_id,
            edas,
            attachments,
        )
        attachment_roles = [str(item.get("role", "")) for item in attachments]
        automatic_apply_ready = (
            bool(attachments)
            and len(set(attachment_roles)) == len(attachment_roles)
            and not identity_gaps
        )
        remaining_status = list(dict.fromkeys([*remaining_roles, *identity_gaps]))
        now = time.monotonic()
        entry: _ManualCadProposalEntry = {
            "part_id": part_id,
            "root": root,
            "paths": snapshots,
            "landed_names": landed_names,
            "edas": edas,
            "digests": digests,
            "created": now,
        }
    except Exception:
        shutil.rmtree(root, ignore_errors=True)
        raise

    removed: list[_ManualCadProposalEntry] = []
    with _proposal_lock:
        removed.extend(_expire_manual_cad_proposals(now))
        token = secrets.token_urlsafe(24)
        while token in _proposals:
            token = secrets.token_urlsafe(24)
        _proposals[token] = entry
        while len(_proposals) > _PROPOSAL_LIMIT:
            _expired_token, expired_entry = _proposals.popitem(last=False)
            removed.append(expired_entry)
    for removed_entry in removed:
        _cleanup_proposal_entry(removed_entry)
    tool = "both" if set(edas) == {"kicad", "altium"} else edas[0]
    return {
        "proposal_token": token,
        "part_id": part_id,
        "provider": "manual",
        "primary_tool": tool,
        "attachments": attachments,
        "inactive_evidence": inactive,
        "ignored": ignored,
        "selected_files": len(paths),
        # The proposal is also the review surface for provider-browser intake. Keep the exact
        # landed names visible even when a file is irrelevant or cannot map to an active role.
        "landed_files": list(landed_names),
        # The existing review surface renders this field directly. Identity is therefore a
        # first-class remaining requirement, not a hidden reason beside an apparently complete set.
        "remaining_roles": remaining_status,
        "remaining_status": remaining_status,
        "review_required_reason": identity_reason,
        "automatic_apply_ready": automatic_apply_ready,
    }


def discard_manual_cad_proposal(part_id: str, proposal_token: str) -> bool:
    """Discard only the named part's inactive proposal; selected source files stay untouched."""

    now = time.monotonic()
    discarded: _ManualCadProposalEntry | None = None
    with _proposal_lock:
        expired = _expire_manual_cad_proposals(now)
        entry = _proposals.get(proposal_token)
        if entry is not None and entry["part_id"] == part_id:
            discarded = _proposals.pop(proposal_token)
    for expired_entry in expired:
        _cleanup_proposal_entry(expired_entry)
    if discarded is None:
        return False
    _cleanup_proposal_entry(discarded)
    return True


def discard_all_manual_cad_proposals() -> int:
    """Release every process-owned proposal snapshot during application shutdown."""

    with _proposal_lock:
        entries = list(_proposals.values())
        _proposals.clear()
    for entry in entries:
        _cleanup_proposal_entry(entry)
    return len(entries)


def apply_manual_cad_proposal(ctx, part_id: str, proposal_token: str) -> dict:
    """Consume one exact proposal and mutate only after its selected bytes still match."""

    now = time.monotonic()
    claimed: _ManualCadProposalEntry | None = None
    expired_current = False
    with _proposal_lock:
        current = _proposals.get(proposal_token)
        expired_current = bool(
            current is not None
            and current["part_id"] == part_id
            and now - float(current["created"]) >= _PROPOSAL_TTL_SECONDS
        )
        expired = _expire_manual_cad_proposals(now)
        entry = _proposals.get(proposal_token)
        if entry is not None and entry["part_id"] == part_id:
            claimed = _proposals.pop(proposal_token)
    for expired_entry in expired:
        _cleanup_proposal_entry(expired_entry)
    if claimed is None:
        if expired_current:
            raise ValueError("the manual CAD proposal expired; inspect the files again")
        raise ValueError("the manual CAD proposal is missing, expired, or belongs to another part")

    paths = tuple(claimed["paths"])
    edas = tuple(claimed["edas"])
    expected = tuple(claimed["digests"])
    try:
        observed = tuple(_file_digest(path) for path in paths)
        if observed != expected:
            raise ValueError("a selected CAD file changed after review; inspect the files again")
        return import_manual_cad_files(ctx, part_id, paths, edas=edas)
    finally:
        _cleanup_proposal_entry(claimed)


def import_manual_cad_files(
    ctx,
    part_id: str,
    paths: tuple[Path, ...],
    *,
    edas: tuple[str, ...] = ("kicad", "altium"),
) -> dict:
    """Attach every useful selected CAD role and return an honest readback report."""

    if not paths:
        raise ValueError("select at least one CAD file")
    selected = _selected_requirements(edas)
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
        candidate, selection_note, _identity_bound = _select_candidate(record, candidates)
        if selection_note:
            messages.append(selection_note)
        if candidate is not None:
            useful = _only_missing_kicad(record, candidate, selected)
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
                            (sch, Requirement.ALTIUM_SYMBOL),
                            (pcb, Requirement.ALTIUM_FOOTPRINT),
                        )
                        if path is not None
                        and requirement in selected
                        and requirement.value in missing
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
