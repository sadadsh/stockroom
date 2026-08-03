"""Resolve one immutable dual-EDA bundle only after its proof is reverified."""

from __future__ import annotations

from dataclasses import dataclass

from stockroom.cad_variants import (
    ResolvedCadVariant,
    resolve_cad_variant,
    same_cad_evidence_set,
)
from stockroom.capture.cad_composition import cross_eda_report_is_proved
from stockroom.evidence.store import ExactIdentity


@dataclass(frozen=True, slots=True)
class VerifiedCadPair:
    """A same-manifest KiCad/Altium pair with proved native entry bindings."""

    kicad: ResolvedCadVariant
    altium: ResolvedCadVariant
    validation: dict[str, object]
    altium_symbol_entry: str
    altium_footprint_entry: str


def _required_entry(report: dict[str, object], key: str) -> str:
    altium = report.get("altium")
    value = altium.get(key) if isinstance(altium, dict) else None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"cross-EDA proof has no native Altium {key.replace('_', ' ')}")
    return value.strip()


def resolve_verified_pair(
    store,
    *,
    identity: ExactIdentity,
    manifest_digest: str,
) -> VerifiedCadPair:
    """Reverify bytes, provenance, cross-EDA proof, and native entry names together."""

    kicad = resolve_cad_variant(
        store,
        identity=identity,
        tool="kicad",
        manifest_digest=manifest_digest,
    )
    altium = resolve_cad_variant(
        store,
        identity=identity,
        tool="altium",
        manifest_digest=manifest_digest,
    )
    if not same_cad_evidence_set(kicad.descriptor, altium.descriptor):
        raise ValueError("KiCad and Altium do not share one immutable provider evidence set")

    validation = store.verified_cad_validation_report(
        manifest_digest,
        identity=identity,
    )
    if not isinstance(validation, dict):
        raise ValueError("CAD validation report is not an object")
    cross_eda = validation.get("cross_eda")
    report = cross_eda.get("report") if isinstance(cross_eda, dict) else None
    if (
        not isinstance(cross_eda, dict)
        or cross_eda.get("status") != "verified"
        or not isinstance(report, dict)
        or not cross_eda_report_is_proved(report)
    ):
        raise ValueError("CAD pair has no proved cross-EDA validation report")

    return VerifiedCadPair(
        kicad=kicad,
        altium=altium,
        validation=validation,
        altium_symbol_entry=_required_entry(report, "symbol_entry"),
        altium_footprint_entry=_required_entry(report, "footprint_entry"),
    )


__all__ = ["VerifiedCadPair", "resolve_verified_pair"]
