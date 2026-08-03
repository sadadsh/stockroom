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

import hashlib
import inspect
import json
import re
import tempfile
from collections.abc import Callable, Iterable
from pathlib import Path
from types import SimpleNamespace
from typing import Protocol, cast

from stockroom.altium.extract import extract_intlib
from stockroom.capture.cad_composition import cross_eda_report_is_proved
from stockroom.capture.cross_eda import (
    CrossEdaVerificationError,
    read_kicad_symbol,
    verify_kicad_component,
)
from stockroom.capture.identity import (
    PageIdentity,
    exact_catalog_observation_error,
    exact_observation_error,
    page_identity,
    select_exact_candidate,
)
from stockroom.evidence import EvidenceArtifact, EvidenceStore
from stockroom.ingest.staging import StagingCandidate
from stockroom.kicad.symbol_lib import SymbolLib
from stockroom.planning import (
    ALTIUM_CAD_OPERATION,
    KICAD_CAD_OPERATION,
    ExactPartIdentity,
)

BROWSER_CAPTURE_ADAPTER_VERSION = "browser-guided-cad-v2"
INSTALLED_KICAD_READBACK_ADAPTER_VERSION = "installed-kicad-readback-v1"
_SOURCE_RECEIPT_SET_ROLE = "source_receipt_set"


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
        altium_identity_attestation: ExactPartIdentity | None = None,
        altium_footprint_entry: str = "",
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


def _source_receipt_set(digests: tuple[str, ...]) -> bytes:
    """Canonicalize the immutable provider downloads that produced one CAD set.

    Native conversion outputs legitimately contain tool-generated timestamps, so their byte
    digests can differ even when the downloaded provider ZIP is identical.  The task-bound
    broker receipt is the stable identity for that observation and prevents repeated collection
    from manufacturing duplicate selectable variants.
    """

    if not digests:
        return b""
    canonical = tuple(sorted(set(digests)))
    if any(
        len(digest) != 71
        or not digest.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in digest[7:])
        for digest in canonical
    ):
        raise ValueError("browser CAD source receipt digests are not canonical")
    return json.dumps(
        {
            "digests": list(canonical),
            "schema": "stockroom.cad-source-receipts/1",
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _matching_receipt_manifest(
    store: EvidenceStore,
    *,
    identity: ExactPartIdentity,
    provider_key: str,
    receipt_set: bytes,
) -> str | None:
    if not receipt_set:
        return None
    receipt_document = json.loads(receipt_set)
    receipt_digests = receipt_document.get("digests")
    if not isinstance(receipt_digests, list) or not receipt_digests:
        raise ValueError("browser CAD source receipt set is incomplete")
    receipt_roles = tuple(
        f"source_receipt_{index}" for index in range(1, len(receipt_digests) + 1)
    )
    for artifact in store.list_role_variants(
        identity=identity,
        role=_SOURCE_RECEIPT_SET_ROLE,
    ):
        if (
            artifact.provider_key != provider_key
            or artifact.adapter_version != BROWSER_CAPTURE_ADAPTER_VERSION
            or artifact.data != receipt_set
        ):
            continue
        # Re-read the complete selectable contract before reusing it.  A receipt index is only a
        # lookup accelerator; it is never authority for CAD completeness or cross-EDA proof.
        verified = store.verified_role_artifacts(
            artifact.manifest_digest,
            identity=identity,
            roles=(
                "symbol",
                "footprint",
                "model",
                "altium_symbol",
                "altium_footprint",
                "validation_report",
                _SOURCE_RECEIPT_SET_ROLE,
                *receipt_roles,
            ),
        )
        if {
            verified[role].artifact_digest for role in receipt_roles
        } != set(receipt_digests):
            continue
        validation = store.verified_cad_validation_report(
            artifact.manifest_digest,
            identity=identity,
        )
        cross_eda = validation.get("cross_eda")
        report = cross_eda.get("report") if isinstance(cross_eda, dict) else None
        if (
            isinstance(cross_eda, dict)
            and cross_eda.get("status") == "verified"
            and cross_eda_report_is_proved(report)
        ):
            return artifact.manifest_digest
    return None


def _altium_artifacts(paths: Iterable[Path]) -> tuple[EvidenceArtifact, ...]:
    counts: dict[str, int] = {}
    artifacts: list[EvidenceArtifact] = []
    role_by_suffix = {
        ".schlib": ("altium_symbol", "application/vnd.altium.schlib"),
        ".pcblib": ("altium_footprint", "application/vnd.altium.pcblib"),
        ".intlib": ("altium_integrated_library", "application/vnd.altium.intlib"),
    }

    def append(path: Path, base_role: str, media_type: str) -> None:
        counts[base_role] = counts.get(base_role, 0) + 1
        index = counts[base_role]
        role = base_role if index == 1 else f"{base_role}_{index}"
        artifact = _artifact(path, role, media_type)
        if not artifact.data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
            raise ValueError(f"captured {role} is not a native Altium compound file")
        artifacts.append(artifact)

    for path in sorted((Path(item) for item in paths), key=lambda item: str(item).casefold()):
        mapping = role_by_suffix.get(path.suffix.casefold())
        if mapping is None:
            continue
        base_role, media_type = mapping
        if path.suffix.casefold() == ".intlib":
            # Keep the exact provider download for audit/replay AND index its native children as
            # selectable Altium roles. An IntLib is a compiled container, not a substitute role:
            # the active library projection and variant registry operate on SchLib/PcbLib bytes.
            append(path, base_role, media_type)
            with tempfile.TemporaryDirectory(prefix="sr-evidence-intlib-") as temporary:
                try:
                    schlib, pcblib = extract_intlib(path, Path(temporary))
                except ValueError as exc:
                    raise ValueError(f"captured Altium IntLib cannot be extracted: {exc}") from exc
                append(schlib, "altium_symbol", "application/vnd.altium.schlib")
                append(pcblib, "altium_footprint", "application/vnd.altium.pcblib")
            continue
        append(path, base_role, media_type)
    return tuple(artifacts)


def _verify_cross_eda_with_provider_identity(
    verifier: CrossEdaVerifier,
    *,
    identity: ExactPartIdentity,
    provider_key: str,
    detail_url: str,
    kicad_symbol: Path,
    kicad_footprint: Path,
    step_model: Path,
    altium_sources: tuple[Path, ...],
    catalog_identity_authorized: bool = False,
    altium_footprint_entry: str = "",
) -> object:
    """Call a verifier with exact provider-page identity when it supports that contract."""

    parameters = inspect.signature(verifier).parameters.values()
    parameter_names = {parameter.name for parameter in parameters}
    supports_kwargs = any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD for parameter in parameters
    )
    call = {
        "identity": identity,
        "kicad_symbol": kicad_symbol,
        "kicad_footprint": kicad_footprint,
        "step_model": step_model,
        "altium_sources": altium_sources,
    }
    if altium_footprint_entry and (
        "altium_footprint_entry" in parameter_names or supports_kwargs
    ):
        call["altium_footprint_entry"] = altium_footprint_entry
    supports_attestation = "altium_identity_attestation" in parameter_names or supports_kwargs
    if supports_attestation:
        detail = page_identity(provider_key, detail_url)
        if detail is not None:
            expected_record = SimpleNamespace(
                manufacturer=identity.authoritative_manufacturer_key,
                mpn=identity.mpn_canonical,
            )
            identity_issue = (
                exact_catalog_observation_error(expected_record, detail)
                if catalog_identity_authorized
                else exact_observation_error(expected_record, detail)
            )
            if not identity_issue:
                # A catalog-authorized URL can use a lossy carrier slug.  The catalog
                # observation proves the canonical record identity; the lossy URL must
                # never become the identity written into native-library attestation.
                attestation = (
                    identity
                    if catalog_identity_authorized
                    else ExactPartIdentity(detail.manufacturer, detail.mpn)
                )
                call["altium_identity_attestation"] = attestation
    return cast(Callable[..., object], verifier)(**call)


def _bind_kicad_symbol_identity(
    *,
    candidate: StagingCandidate,
    identity: ExactPartIdentity,
    provider_key: str,
    detail_url: str,
    catalog_identity_authorized: bool = False,
) -> tuple[str, ...]:
    """Bind a metadata-light provider symbol to its independently verified detail page.

    Ultra Librarian's standard KiCad export names the exact symbol but does not include
    manufacturer/MPN properties. The raw archive remains immutable in the download store;
    this normalized staging copy gains hidden identity fields only after both the candidate
    and the provider detail URL have passed the exact-result gate. Existing conflicting
    metadata is evidence of a mismatch and is never overwritten.
    """

    symbol_path = Path(candidate.symbol_lib_path or "")
    observed = read_kicad_symbol(symbol_path, candidate.symbol_name)
    expected_record = SimpleNamespace(
        manufacturer=identity.authoritative_manufacturer_key,
        mpn=identity.mpn_canonical,
    )
    if observed.manufacturer:
        issue = exact_observation_error(
            expected_record,
            PageIdentity(
                manufacturer=observed.manufacturer,
                mpn=identity.mpn_canonical,
            ),
        )
        if issue:
            raise CrossEdaVerificationError(f"KiCad symbol {issue}")
    if observed.mpn:
        issue = exact_observation_error(
            expected_record,
            PageIdentity(
                manufacturer=identity.authoritative_manufacturer_key,
                mpn=observed.mpn,
            ),
        )
        if issue:
            raise CrossEdaVerificationError(f"KiCad symbol {issue}")

    missing: list[str] = []
    if not observed.manufacturer:
        missing.append("Manufacturer")
    if not observed.mpn:
        missing.append("Manufacturer Part Number")
    if not missing:
        return ()

    detail = page_identity(provider_key, detail_url)
    detail_issue = (
        None
        if detail is None
        else (
            exact_catalog_observation_error(expected_record, detail)
            if catalog_identity_authorized
            else exact_observation_error(expected_record, detail)
        )
    )
    if detail is None or detail_issue:
        raise CrossEdaVerificationError(
            "KiCad symbol lacks embedded identity and no exact provider detail page can bind it"
        )

    library = SymbolLib.load(symbol_path)
    symbol = library.get_symbol(observed.entry)
    if "Manufacturer" in missing:
        symbol.set_property(
            "Manufacturer",
            identity.authoritative_manufacturer_key,
            hide=True,
        )
    if "Manufacturer Part Number" in missing:
        symbol.set_property(
            "Manufacturer Part Number",
            identity.mpn_canonical,
            hide=True,
        )
    library.save(symbol_path)
    return tuple(missing)


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


def _canonical_role_report(
    *,
    identity: ExactPartIdentity,
    operation: str,
    provider_key: str,
    roles: tuple[str, ...],
    source_manifests: tuple[str, ...],
    verification: object,
    observations: object,
) -> bytes:
    document = {
        "identity": {
            "authoritative_manufacturer_key": identity.authoritative_manufacturer_key,
            "mpn_canonical": identity.mpn_canonical,
        },
        "observations": observations,
        "operation": operation,
        "provider": provider_key,
        "roles": sorted(roles),
        "schema": "stockroom.cad-role-validation/1",
        "source_manifests": sorted(source_manifests),
        "valid": True,
        "verification": verification,
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
        raise ValueError("CAD role validation report must be strict JSON") from exc


def _installed_kicad_paths(record: object, profile: object) -> tuple[Path, Path, Path]:
    assets_for = getattr(record, "assets_for", None)
    library = getattr(profile, "library", None)
    category = getattr(record, "category", "")
    if not callable(assets_for) or library is None or not isinstance(category, str) or not category:
        raise ValueError("existing KiCad assets cannot be resolved from the active library")
    kicad = assets_for("kicad")
    try:
        symbol_asset = kicad.symbol
        footprint_asset = kicad.footprint
        model_asset = kicad.model
    except AttributeError as exc:
        raise ValueError(
            "existing KiCad assets do not use the canonical EDA bundle"
        ) from exc
    symbol_name = getattr(symbol_asset, "name", "")
    footprint_name = getattr(footprint_asset, "name", "")
    model_file = getattr(model_asset, "file", "")
    if not all(
        isinstance(value, str) and value for value in (symbol_name, footprint_name, model_file)
    ):
        raise ValueError(
            "Altium composition requires an already-attached KiCad symbol, footprint, and STEP"
        )
    model_relative = Path(model_file)
    if model_relative.is_absolute() or ".." in model_relative.parts:
        raise ValueError("existing KiCad model reference is not a safe library-relative path")
    root = Path(getattr(library, "root", ""))
    if not root.is_absolute() or not root.is_dir() or root.is_symlink():
        raise ValueError("active library root is unavailable or linked")
    root = root.resolve(strict=True)
    symbol = Path(library.symbol_lib_path(category))
    footprint = Path(library.footprint_lib_path(category)) / f"{footprint_name}.kicad_mod"
    model = root / model_relative
    for path in (symbol, footprint, model):
        if (
            not path.is_file()
            or path.is_symlink()
            or not path.resolve(strict=True).is_relative_to(root)
        ):
            raise ValueError(
                f"existing KiCad artifact is missing, linked, or outside the library: {path}"
            )
    return symbol, footprint, model


def _installed_provider(record: object) -> tuple[str, dict[str, object]]:
    assets_for = getattr(record, "assets_for")
    kicad = assets_for("kicad")
    observations: dict[str, object] = {}
    providers: set[str] = set()
    for role in ("symbol", "footprint", "model"):
        asset = getattr(kicad, role, None)
        origin = getattr(asset, "origin", None)
        provider = getattr(origin, "vendor", "")
        evidence_digest = getattr(origin, "extra", {}).get("evidence_manifest_digest", "")
        role_observation: dict[str, object] = {}
        if isinstance(provider, str) and provider:
            role_observation["provider"] = provider
            providers.add(provider)
        if isinstance(evidence_digest, str) and evidence_digest:
            role_observation["prior_evidence_manifest"] = evidence_digest
        observations[role] = role_observation
    provider_key = next(iter(providers)) if len(providers) == 1 else "stockroom-library"
    if (
        not provider_key
        or provider_key != provider_key.lower()
        or not provider_key[0].isalnum()
        or any(
            character not in "abcdefghijklmnopqrstuvwxyz0123456789._-" for character in provider_key
        )
    ):
        provider_key = "stockroom-library"
    return provider_key, observations


def _active_kicad_pad_allowance(
    *,
    store: EvidenceStore,
    record: object,
    identity: ExactPartIdentity,
) -> frozenset[str]:
    """Recover the mechanical-pad allowance proved by the exact active evidence manifest.

    The installed projection is intentionally normalized: its symbol is merged into a category
    library and its footprint model path is rewritten. Byte equality with the provider artifact
    is therefore not an invariant. The current installed bytes are independently read back below,
    and the new Altium package must still pass terminal, pad, and package equivalence against them.
    """

    variants = getattr(record, "cad_variants", None)
    active = getattr(variants, "active", None)
    pointer = active.get("kicad") if isinstance(active, dict) else None
    manifest_digest = getattr(pointer, "manifest_digest", "")
    if not isinstance(manifest_digest, str) or not manifest_digest:
        return frozenset()
    try:
        validation = store.verified_cad_validation_report(
            manifest_digest,
            identity=identity,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("active KiCad validation report is unreadable") from exc
    return proved_kicad_pad_allowance(validation)


def proved_kicad_pad_allowance(validation: object) -> frozenset[str]:
    """Return only package pads retained by one immutable proved validation report."""

    if not isinstance(validation, dict) or validation.get("valid") is not True:
        raise ValueError("active KiCad validation report is not a proved result")
    cross_eda = validation.get("cross_eda")
    cross_eda_report = cross_eda.get("report") if isinstance(cross_eda, dict) else None
    cross_eda_kicad = cross_eda_report.get("kicad") if isinstance(cross_eda_report, dict) else None
    candidate_sections = [
        validation.get("kicad_readback"),
        validation.get("verification"),
        cross_eda_kicad,
    ]
    for section in candidate_sections:
        if not isinstance(section, dict):
            continue
        values = section.get("unrepresented_pad_numbers")
        if values is None:
            continue
        if not isinstance(values, list) or not all(
            isinstance(value, str) and value for value in values
        ):
            raise ValueError("active KiCad mechanical-pad allowance is invalid")
        if len(values) != len(set(values)):
            raise ValueError("active KiCad mechanical-pad allowance contains duplicates")
        return frozenset(value for value in values if isinstance(value, str))
    return frozenset()


def record_installed_kicad_role_evidence(
    *,
    store: EvidenceStore,
    record: object,
    profile: object,
) -> tuple[str, tuple[Path, Path, Path]]:
    """Read back and index the exact KiCad bytes currently active for a part."""
    identity = exact_identity(record)
    symbol, footprint, model = _installed_kicad_paths(record, profile)
    allowed_unrepresented_pads = _active_kicad_pad_allowance(
        store=store,
        record=record,
        identity=identity,
    )
    report = verify_kicad_component(
        identity=identity,
        kicad_symbol=symbol,
        kicad_footprint=footprint,
        step_model=model,
        allowed_unrepresented_pads=allowed_unrepresented_pads,
    )
    if not isinstance(report, dict) or report.get("valid") is not True:
        raise ValueError("existing KiCad artifact readback did not prove a complete component")
    provider_key, observations = _installed_provider(record)
    artifacts = (
        _artifact(symbol, "symbol", "application/vnd.kicad.symbol-library"),
        _artifact(footprint, "footprint", "application/vnd.kicad.footprint"),
        _artifact(model, "model", "model/step"),
    )
    roles = tuple(artifact.role for artifact in artifacts)
    validation = _canonical_role_report(
        identity=identity,
        operation=KICAD_CAD_OPERATION.label,
        provider_key=provider_key,
        roles=roles,
        source_manifests=(),
        verification=report,
        observations={"active_library_origins": observations},
    )
    digest = store.record_role_artifact_success(
        identity=identity,
        operation=KICAD_CAD_OPERATION,
        provider_key=provider_key,
        adapter_version=INSTALLED_KICAD_READBACK_ADAPTER_VERSION,
        artifacts=artifacts,
        validation_report=validation,
    )
    return digest, (symbol, footprint, model)


def record_browser_cad_evidence(
    *,
    store: EvidenceStore,
    record: object,
    candidate: StagingCandidate,
    provider_key: str,
    detail_url: str,
    altium_sources: tuple[Path, ...] = (),
    cross_eda_verifier: CrossEdaVerifier | None = None,
    source_receipt_digests: tuple[str, ...] = (),
    source_receipts: tuple[Path, ...] = (),
    catalog_identity_authorized: bool = False,
    altium_footprint_entry: str = "",
) -> tuple[str, bool]:
    """Install and immediately verify one exact browser CAD observation.

    Returns ``(manifest_digest, cross_eda_verified)``.  The digest is suitable
    for both provider-runtime receipts and ``AssetOrigin.extra``.
    """
    identity = exact_identity(record)
    receipt_set = _source_receipt_set(source_receipt_digests)
    raw_by_digest: dict[str, Path] = {}
    for path in (Path(item) for item in source_receipts):
        digest = "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()
        raw_by_digest.setdefault(digest, path)
    raw_receipts = tuple(raw_by_digest[digest] for digest in sorted(raw_by_digest))
    if receipt_set and not raw_receipts:
        raise ValueError("source receipt digests require the immutable downloaded files")
    if raw_receipts:
        observed_receipts = _source_receipt_set(
            tuple(sorted(raw_by_digest))
        )
        if receipt_set and observed_receipts != receipt_set:
            raise ValueError("source receipt paths do not match their task-bound digests")
        receipt_set = observed_receipts
    selection = select_exact_candidate(
        record,
        [candidate],
        vendor_key=provider_key,
        detail_url=detail_url,
        catalog_identity_authorized=catalog_identity_authorized,
    )
    if selection.error or selection.candidate is not candidate:
        raise ValueError(selection.error or "browser CAD candidate is not exact")
    existing_manifest = _matching_receipt_manifest(
        store,
        identity=identity,
        provider_key=provider_key,
        receipt_set=receipt_set,
    )
    if existing_manifest is not None:
        return existing_manifest, True

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

    bound_identity_fields = _bind_kicad_symbol_identity(
        candidate=candidate,
        identity=identity,
        provider_key=provider_key,
        detail_url=detail_url,
        catalog_identity_authorized=catalog_identity_authorized,
    )
    native_altium = tuple(Path(path) for path in altium_sources)
    cross_eda_report = None
    allowed_unrepresented_pads: frozenset[str] = frozenset()
    if native_altium and cross_eda_verifier is not None:
        cross_eda_report = _verify_cross_eda_with_provider_identity(
            cross_eda_verifier,
            identity=identity,
            provider_key=provider_key,
            detail_url=detail_url,
            kicad_symbol=Path(symbol),
            kicad_footprint=Path(footprint),
            step_model=model_path,
            altium_sources=native_altium,
            catalog_identity_authorized=catalog_identity_authorized,
            altium_footprint_entry=altium_footprint_entry,
        )
        if not isinstance(cross_eda_report, dict) or not cross_eda_report_is_proved(
            cross_eda_report
        ):
            raise ValueError(
                "cross-EDA verifier did not prove terminal, pad, and package equivalence"
            )
        kicad_section = cross_eda_report.get("kicad")
        if isinstance(kicad_section, dict):
            reported_unrepresented = kicad_section.get("unrepresented_pad_numbers", ())
            if isinstance(reported_unrepresented, list):
                valid_unrepresented = [
                    number
                    for number in reported_unrepresented
                    if isinstance(number, str) and number
                ]
                if len(valid_unrepresented) == len(reported_unrepresented):
                    allowed_unrepresented_pads = frozenset(valid_unrepresented)

    kicad_report = verify_kicad_component(
        identity=identity,
        kicad_symbol=Path(symbol),
        kicad_footprint=Path(footprint),
        step_model=model_path,
        allowed_unrepresented_pads=allowed_unrepresented_pads,
    )
    if not isinstance(kicad_report, dict) or kicad_report.get("valid") is not True:
        raise ValueError("KiCad artifact readback did not prove a complete component")
    if bound_identity_fields:
        kicad_report = {
            **kicad_report,
            "identity_binding": {
                "fields_added": list(bound_identity_fields),
                "source": "exact-provider-detail-page",
            },
        }

    validation = _canonical_report(
        identity=identity,
        provider_key=provider_key,
        detail_url=detail_url,
        candidate=candidate,
        altium_sources=native_altium,
        kicad_report=kicad_report,
        cross_eda_report=cross_eda_report,
    )
    altium_artifacts = _altium_artifacts(native_altium)
    raw_receipt_artifacts = tuple(
        EvidenceArtifact(
            f"source_receipt_{index}",
            path.read_bytes(),
            "application/octet-stream",
            path.name,
        )
        for index, path in enumerate(raw_receipts, start=1)
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
        *altium_artifacts,
        *raw_receipt_artifacts,
        *(
            (
                EvidenceArtifact(
                    _SOURCE_RECEIPT_SET_ROLE,
                    receipt_set,
                    "application/json",
                    "Source Receipt Set.json",
                ),
            )
            if receipt_set
            else ()
        ),
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
    index_roles = ["symbol", "footprint", "model"]
    if cross_eda_report is not None:
        index_roles.extend(artifact.role for artifact in altium_artifacts)
    if receipt_set:
        index_roles.append(_SOURCE_RECEIPT_SET_ROLE)
    index_roles.extend(artifact.role for artifact in raw_receipt_artifacts)
    store.index_artifact_manifest(
        digest,
        identity=identity,
        roles=tuple(index_roles),
    )
    return digest, cross_eda_report is not None


__all__ = [
    "BROWSER_CAPTURE_ADAPTER_VERSION",
    "CrossEdaVerifier",
    "INSTALLED_KICAD_READBACK_ADAPTER_VERSION",
    "exact_identity",
    "proved_kicad_pad_allowance",
    "record_browser_cad_evidence",
    "record_installed_kicad_role_evidence",
]
