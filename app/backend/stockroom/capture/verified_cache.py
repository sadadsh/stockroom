"""Zero-interaction completion from immutable, already validated CAD evidence.

The evidence store is not a browser cache.  Every selectable bundle has already passed exact
identity, role, semantic-readback, and digest checks, and Altium bundles retain the exact KiCad
manifest whose terminals, pads, and package they were proved against.  This source reverifies
those claims at use time and materializes the strongest coherent result before any catalogue or
browser is touched.
"""

from __future__ import annotations

from collections.abc import Callable

from stockroom.cad_variants import (
    CadVariantDescriptor,
    ResolvedCadVariant,
    list_cad_variants,
    resolve_cad_variant,
    same_cad_evidence_set,
)
from stockroom.capture.complete import (
    CompletionEvidence,
    SourceOutcome,
    provider_outcome_from_source,
)
from stockroom.capture.evidence import exact_identity
from stockroom.capture.requirements import (
    Requirement,
    capture_needs,
    capture_requirements,
    split_requirement,
)

_KICAD_REQUIREMENTS = (
    Requirement.KICAD_SYMBOL,
    Requirement.KICAD_FOOTPRINT,
    Requirement.KICAD_MODEL,
)
_PAIR_REQUIREMENTS = (
    *_KICAD_REQUIREMENTS,
    Requirement.ALTIUM_SYMBOL,
    Requirement.ALTIUM_FOOTPRINT,
)


def _required_tools(record: object) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            split_requirement(requirement)[0]
            for requirement in capture_requirements(record)
        )
    )


def _unverified(reason: str) -> CompletionEvidence:
    return CompletionEvidence.unverified(reason)


def record_completion_evidence(store, record: object) -> CompletionEvidence:
    """Reverify the exact active projection against immutable local evidence.

    The part-class/override requirement registry decides which tools are owned.
    Every owned tool must have all required projected references, an active whole-
    bundle pointer, and a freshly resolved exact-identity CAS manifest. When more
    than one tool is owned, every projection must share one evidence lineage.
    """

    requirements = capture_requirements(record)
    if not requirements:
        return CompletionEvidence.not_required(
            "this part class has no owned CAD requirements"
        )
    missing = capture_needs(record)
    if missing:
        return _unverified(
            "required projected references are absent: "
            + ", ".join(requirement.value for requirement in missing)
        )

    selections = getattr(record, "cad_variants", None)
    selection_for = getattr(selections, "selection_for", None)
    if not callable(selection_for):
        return _unverified("the record has no active CAD variant selections")

    try:
        identity = exact_identity(record)
    except (TypeError, ValueError) as exc:
        return _unverified(
            f"the record does not have exact CAD identity ({type(exc).__name__})"
        )

    resolved: dict[str, ResolvedCadVariant] = {}
    for tool in _required_tools(record):
        pointer = selection_for(tool)
        if pointer is None:
            return _unverified(f"the active {tool} evidence pointer is absent")
        try:
            variant = resolve_cad_variant(
                store,
                identity=identity,
                tool=tool,
                manifest_digest=pointer.manifest_digest,
            )
        except Exception as exc:  # noqa: BLE001 - stale/tampered evidence fails closed
            return _unverified(
                f"the active {tool} evidence could not be reverified "
                f"({type(exc).__name__})"
            )
        if variant.pointer != pointer:
            return _unverified(
                f"the active {tool} pointer does not match the reverified manifest"
            )
        resolved[tool] = variant

    if set(resolved) == {"kicad", "altium"}:
        if not same_cad_evidence_set(
            resolved["kicad"].descriptor,
            resolved["altium"].descriptor,
        ):
            return _unverified(
                "the active KiCad and Altium pointers do not share one evidence set"
            )
    elif len(resolved) > 1:
        descriptors = tuple(item.descriptor for item in resolved.values())
        first = descriptors[0]
        if any(
            descriptor.manifest_digest != first.manifest_digest
            or descriptor.provider != first.provider
            or descriptor.adapter_version != first.adapter_version
            or descriptor.operation != first.operation
            or descriptor.source_manifests != first.source_manifests
            for descriptor in descriptors[1:]
        ):
            return _unverified(
                "the active CAD pointers do not share one immutable evidence set"
            )

    manifest_digest = next(iter(resolved.values())).descriptor.manifest_digest
    return CompletionEvidence(
        state="verified",
        manifest_digest=manifest_digest,
        reason="the active CAD projection was reverified from immutable evidence",
    )


def active_pair_is_verified(store, record: object) -> bool:
    """Whether both owned EDA tools point at one reverified evidence set."""

    return (
        set(_required_tools(record)) == {"kicad", "altium"}
        and record_completion_evidence(store, record).state == "verified"
    )


class VerifiedEvidenceSource:
    """Install the best retained exact bundle without network or browser work."""

    key = "verified-cache"
    report_label = "Verified Local Evidence"
    provider_key = "verified-cache"
    author_key = "verified-cache"

    def provider_route_ids(self) -> tuple[str, ...]:
        return ("verified-cache:verified-cache",)

    def __init__(
        self,
        store,
        *,
        materialize_kicad: Callable[[object, ResolvedCadVariant], object],
        materialize_pair: Callable[
            [object, ResolvedCadVariant, ResolvedCadVariant],
            object,
        ],
        run_write: Callable[[Callable[[], object]], object] | None = None,
        preserve_active_pair: bool = False,
    ) -> None:
        self._store = store
        self._materialize_kicad = materialize_kicad
        self._materialize_pair = materialize_pair
        self._run_write = run_write or (lambda operation: operation())
        self._preserve_active_pair = preserve_active_pair

    def provides(self) -> frozenset[Requirement]:
        return frozenset(_PAIR_REQUIREMENTS)

    @staticmethod
    def _compatible_pairs(
        kicad: tuple[CadVariantDescriptor, ...],
        altium: tuple[CadVariantDescriptor, ...],
    ) -> tuple[tuple[CadVariantDescriptor, CadVariantDescriptor], ...]:
        """Pair only projections indexed from the exact same provider download set."""

        kicad_by_manifest = {item.manifest_digest: item for item in kicad}
        pairs: list[tuple[CadVariantDescriptor, CadVariantDescriptor]] = []
        for altium_item in altium:
            kicad_item = kicad_by_manifest.get(altium_item.manifest_digest)
            if kicad_item is not None and same_cad_evidence_set(kicad_item, altium_item):
                pairs.append((kicad_item, altium_item))
        return tuple(pairs)

    @staticmethod
    def _safe_error(exc: Exception) -> str:
        detail = " ".join(str(exc).split())
        return f"{type(exc).__name__}: {detail}" if detail else type(exc).__name__

    def supply(self, record) -> SourceOutcome:
        try:
            identity = exact_identity(record)
        except (TypeError, ValueError) as exc:
            return SourceOutcome(skipped=self._safe_error(exc))

        if self._preserve_active_pair and active_pair_is_verified(self._store, record):
            message = (
                "the current active KiCad and Altium pair was reverified from one evidence set; "
                "its pointers are unchanged"
            )
            base = SourceOutcome(skipped=message)
            return SourceOutcome(
                skipped=message,
                provider_outcomes=(
                    provider_outcome_from_source(
                        base,
                        provider_key=self.provider_key,
                        author_key=self.author_key,
                        label=self.report_label,
                        status="succeeded-retained",
                    ),
                ),
            )

        try:
            kicad = list_cad_variants(self._store, identity=identity, tool="kicad")
            altium = list_cad_variants(self._store, identity=identity, tool="altium")
        except Exception as exc:  # noqa: BLE001 - corrupt cache fails closed, network may continue
            return SourceOutcome(
                error=f"retained CAD evidence failed revalidation ({self._safe_error(exc)})"
            )

        failures: list[str] = []
        for kicad_item, altium_item in self._compatible_pairs(kicad, altium):
            try:
                kicad_resolved = resolve_cad_variant(
                    self._store,
                    identity=identity,
                    tool="kicad",
                    manifest_digest=kicad_item.manifest_digest,
                )
                altium_resolved = resolve_cad_variant(
                    self._store,
                    identity=identity,
                    tool="altium",
                    manifest_digest=altium_item.manifest_digest,
                )
                self._run_write(
                    lambda: self._materialize_pair(
                        record,
                        kicad_resolved,
                        altium_resolved,
                    )
                )
                return SourceOutcome(satisfied=_PAIR_REQUIREMENTS)
            except Exception as exc:  # noqa: BLE001 - try the next independently verified pair
                failures.append(
                    f"pair {kicad_item.manifest_digest}/{altium_item.manifest_digest} "
                    f"({self._safe_error(exc)})"
                )

        if failures:
            return SourceOutcome(
                error="retained CAD evidence could not be materialized: " + "; ".join(failures)
            )
        if kicad or altium:
            return SourceOutcome(
                skipped=(
                    "retained CAD evidence has no same-provider, same-download KiCad and Altium "
                    "set; partial candidates remain non-projectable"
                )
            )
        return SourceOutcome(skipped="no complete exact CAD evidence is retained")


__all__ = [
    "VerifiedEvidenceSource",
    "active_pair_is_verified",
    "record_completion_evidence",
]
