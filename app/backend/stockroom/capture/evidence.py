"""Immutable evidence for CAD files delivered by browser capture.

The browser proves that bytes landed.  The ingest pipeline proves that those
bytes are readable CAD.  This module joins those observations only after the
existing exact-identity gate has selected one unambiguous candidate, then
installs the actual normalized files in the provider evidence CAS.

Native Altium libraries may ride beside the required KiCad symbol, footprint,
and STEP file, but their presence is not an Altium success claim.  A separate
cross-EDA verifier must prove terminal, pad, and package equivalence before the
guided source may attach them.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Protocol

from stockroom.capture.cross_eda import verify_kicad_component
from stockroom.capture.identity import page_identity, select_exact_candidate
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.ingest.staging import StagingCandidate
from stockroom.planning import KICAD_CAD_OPERATION, ExactPartIdentity

BROWSER_CAPTURE_ADAPTER_VERSION = "browser-guided-cad-v1"


class CrossEdaVerifier(Protocol):
    """Prove that one provider's KiCad and Altium files describe one component."""

    def __call__(
        self,
        *,
        identity: ExactPartIdentity,
        kicad_symbol: Path,
        kicad_footprint: Path,
        step_model: Path,
        altium_sources: tuple[Path, ...],
    ) -> object: ...


def exact_identity(record: object) -> ExactPartIdentity:
    manufacturer = getattr(record, "manufacturer", "")
    mpn = getattr(record, "mpn", "")
    if not isinstance(manufacturer, str) or not manufacturer.strip():
        raise ValueError("browser CAD evidence requires an authoritative manufacturer")
    if not isinstance(mpn, str) or not mpn.strip():
        raise ValueError("browser CAD evidence requires an exact MPN")
    if manufacturer != manufacturer.strip() or mpn != mpn.strip():
        raise ValueError("browser CAD evidence identity must already be canonical")
    return ExactPartIdentity(manufacturer, mpn)


def _artifact(path: Path, role: str, media_type: str) -> EvidenceArtifact:
    resolved = Path(path)
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(f"captured {role} is missing or linked")
    data = resolved.read_bytes()
    if not data:
        raise ValueError(f"captured {role} is empty")
    return EvidenceArtifact(role, data, media_type, resolved.name)


def _altium_artifacts(paths: Iterable[Path]) -> tuple[EvidenceArtifact, ...]:
    counts: dict[str, int] = {}
    artifacts: list[EvidenceArtifact] = []
    role_by_suffix = {
        ".schlib": ("altium_symbol", "application/vnd.altium.schlib"),
        ".pcblib": ("altium_footprint", "application/vnd.altium.pcblib"),
        ".intlib": ("altium_integrated_library", "application/vnd.altium.intlib"),
    }
    for path in sorted((Path(item) for item in paths), key=lambda item: str(item).casefold()):
        mapping = role_by_suffix.get(path.suffix.casefold())
        if mapping is None:
            continue
        base_role, media_type = mapping
        counts[base_role] = counts.get(base_role, 0) + 1
        index = counts[base_role]
        role = base_role if index == 1 else f"{base_role}_{index}"
        artifact = _artifact(path, role, media_type)
        if not artifact.data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ValueError(f"captured {role} is not a native Altium compound file")
        artifacts.append(artifact)
    return tuple(artifacts)


def _canonical_report(
    *,
    identity: ExactPartIdentity,
    provider_key: str,
    detail_url: str,
    candidate: StagingCandidate,
    altium_sources: tuple[Path, ...],
    kicad_report: object,
    cross_eda_report: object | None,
) -> bytes:
    detail = page_identity(provider_key, detail_url)
    document = {
        "cross_eda": (
            {"status": "not_applicable"}
            if not altium_sources
            else (
                {"status": "not_verified"}
                if cross_eda_report is None
                else {"report": cross_eda_report, "status": "verified"}
            )
        ),
        "identity": {
            "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
            "mpn_canonical": identity.mpn_canonical,
        },
        "identity_observations": {
            "archive_candidate": {
                "manufacturer": getattr(candidate, "manufacturer", "") or "",
                "mpn": getattr(candidate, "mpn", "") or "",
                "symbol_name": getattr(candidate, "symbol_name", "") or "",
            },
            "provider_detail_page": (
                None if detail is None else {"manufacturer": detail.manufacturer, "mpn": detail.mpn}
            ),
        },
        "kicad_readback": kicad_report,
        "operation": KICAD_CAD_OPERATION.label,
        "provider": provider_key,
        "schema": "stockroom.cad-validation/1",
        "valid": True,
    }
    try:
        return json.dumps(
            document,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("cross-EDA validation report must be strict JSON") from exc


def record_browser_cad_evidence(
    *,
    store: EvidenceStore,
    record: object,
    candidate: StagingCandidate,
    provider_key: str,
    detail_url: str,
    altium_sources: tuple[Path, ...] = (),
    cross_eda_verifier: CrossEdaVerifier | None = None,
) -> tuple[str, bool]:
    """Install and immediately verify one exact browser CAD observation.

    Returns ``(manifest_digest, cross_eda_verified)``.  The digest is suitable
    for both provider-runtime receipts and ``AssetOrigin.extra``.
    """
    identity = exact_identity(record)
    selection = select_exact_candidate(
        record,
        [candidate],
        vendor_key=provider_key,
        detail_url=detail_url,
    )
    if selection.error or selection.candidate is not candidate:
        raise ValueError(selection.error or "browser CAD candidate is not exact")

    symbol = getattr(candidate, "symbol_lib_path", None)
    footprint = getattr(candidate, "chosen_footprint", None)
    model = getattr(candidate, "model_path", None)
    missing: list[str] = []
    if symbol is None:
        missing.append("symbol")
    if footprint is None:
        missing.append("footprint")
    if model is None:
        missing.append("STEP model")
    if missing:
        raise ValueError("browser CAD evidence is incomplete: missing " + ", ".join(missing))
    assert symbol is not None
    assert footprint is not None
    assert model is not None
    model_path = Path(model)
    if model_path.suffix.casefold() not in {".step", ".stp"}:
        raise ValueError("browser CAD evidence requires an actual STEP model")
    if not model_path.read_bytes().lstrip().startswith(b"ISO-10303-21;"):
        raise ValueError("browser CAD evidence STEP model has no ISO-10303-21 header")

    kicad_report = verify_kicad_component(
        identity=identity,
        kicad_symbol=Path(symbol),
        kicad_footprint=Path(footprint),
        step_model=model_path,
    )
    if not isinstance(kicad_report, dict) or kicad_report.get("valid") is not True:
        raise ValueError("KiCad artifact readback did not prove a complete component")

    native_altium = tuple(Path(path) for path in altium_sources)
    cross_eda_report = None
    if native_altium and cross_eda_verifier is not None:
        cross_eda_report = cross_eda_verifier(
            identity=identity,
            kicad_symbol=Path(symbol),
            kicad_footprint=Path(footprint),
            step_model=model_path,
            altium_sources=native_altium,
        )
        if not isinstance(cross_eda_report, dict) or cross_eda_report.get("valid") is not True:
            raise ValueError(
                "cross-EDA verifier did not prove terminal, pad, and package equivalence"
            )

    validation = _canonical_report(
        identity=identity,
        provider_key=provider_key,
        detail_url=detail_url,
        candidate=candidate,
        altium_sources=native_altium,
        kicad_report=kicad_report,
        cross_eda_report=cross_eda_report,
    )
    artifacts = (
        _artifact(Path(symbol), "symbol", "application/vnd.kicad.symbol-library"),
        _artifact(Path(footprint), "footprint", "application/vnd.kicad.footprint"),
        _artifact(model_path, "model", "model/step"),
        EvidenceArtifact(
            "validation_report",
            validation,
            "application/json",
            "Validation Report.json",
        ),
        *_altium_artifacts(native_altium),
    )
    digest = store.record_provider_artifact_success(
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=provider_key,
        adapter_version=BROWSER_CAPTURE_ADAPTER_VERSION,
        artifacts=tuple(artifacts),
    )
    store.verify_provider_success(
        digest,
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=provider_key,
        adapter_version=BROWSER_CAPTURE_ADAPTER_VERSION,
    )
    return digest, cross_eda_report is not None


__all__ = [
    "BROWSER_CAPTURE_ADAPTER_VERSION",
    "CrossEdaVerifier",
    "exact_identity",
    "record_browser_cad_evidence",
]
