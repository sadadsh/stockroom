"""Resolve a retained KiCad bundle for native Altium composition.

Composition is deliberately a search over immutable evidence, not an assumption that the
currently projected KiCad files are the only possible match.  Provider-family affinity is a
ranking hint only: every candidate is re-resolved from the evidence CAS and must independently
pass the strict cross-EDA verifier before it can be selected.

Temporary KiCad files exist only while a candidate is being verified.  Files which must outlive
this function use :class:`OwnedMaterialization`, whose caller has an explicit, idempotent cleanup
obligation.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from stockroom.cad_variants import (
    CadVariantDescriptor,
    CadVariantEvidence,
    ResolvedCadVariant,
    list_cad_variants,
    resolve_cad_variant,
)
from stockroom.evidence.store import ExactIdentity

_KNOWN_PROVIDER_FAMILIES = ("ultralibrarian", "snapmagic", "samacsys")
_KICAD_FILENAMES = {
    "symbol": "Candidate.kicad_sym",
    "footprint": "Candidate.kicad_mod",
    "model": "Candidate.step",
}


class CrossEdaCandidateVerifier(Protocol):
    def __call__(
        self,
        *,
        identity: ExactIdentity,
        kicad_symbol: Path,
        kicad_footprint: Path,
        step_model: Path,
        altium_sources: tuple[Path, ...],
    ) -> object: ...


@dataclass(frozen=True, slots=True)
class CompatibilityAttempt:
    provider: str
    manifest_digest: str
    accepted: bool
    reason: str


class CompatibleKicadVariantNotFound(ValueError):
    """No complete retained KiCad bundle passed strict cross-EDA verification."""

    def __init__(self, attempts: tuple[CompatibilityAttempt, ...]) -> None:
        self.attempts = attempts
        summary = ", ".join(
            f"{attempt.provider}/{attempt.manifest_digest}: {attempt.reason}"
            for attempt in attempts
        )
        detail = summary or "no complete retained KiCad variants"
        super().__init__(
            "no retained KiCad variant proved terminal, pad, and package equivalence "
            f"({detail})"
        )


@dataclass(frozen=True, slots=True)
class CompatibleKicadVariant:
    resolved: ResolvedCadVariant
    verification: dict[str, object]
    attempts: tuple[CompatibilityAttempt, ...]


@dataclass(slots=True)
class OwnedMaterialization:
    """Temporary files with an explicit, idempotent owner.

    Bare paths are not returned from the factory because doing so loses the only reliable handle
    to their temporary root.  The consumer keeps this object alive until the downstream attach is
    complete, then calls :meth:`cleanup` (or uses it as a context manager).
    """

    root: Path
    paths: tuple[Path, ...]
    _closed: bool = False

    @classmethod
    def from_bytes(
        cls,
        files: Mapping[str, bytes],
        *,
        prefix: str,
        temporary_parent: Path | None = None,
    ) -> "OwnedMaterialization":
        if not files:
            raise ValueError("owned materialization requires at least one file")
        names = tuple(files)
        _validate_materialized_names(names)
        root = Path(
            tempfile.mkdtemp(
                prefix=prefix,
                dir=None if temporary_parent is None else str(temporary_parent),
            )
        )
        try:
            paths: list[Path] = []
            for name, data in files.items():
                if not isinstance(data, bytes) or not data:
                    raise ValueError("owned materialization content must be non-empty bytes")
                destination = root / name
                destination.write_bytes(data)
                if destination.read_bytes() != data:
                    raise OSError(f"could not verify materialized file {name!r}")
                paths.append(destination)
            return cls(root=root, paths=tuple(paths))
        except Exception:
            shutil.rmtree(root, ignore_errors=True)
            raise

    @classmethod
    def adopt(cls, root: Path, paths: tuple[Path, ...]) -> "OwnedMaterialization":
        """Take ownership of already-extracted files beneath one temporary root."""

        owned_root = Path(root)
        try:
            resolved_root = owned_root.resolve(strict=True)
            if not resolved_root.is_dir() or owned_root.is_symlink() or not paths:
                raise ValueError("owned materialization root or paths are invalid")
            resolved_paths: list[Path] = []
            seen: set[str] = set()
            for path in paths:
                candidate = Path(path)
                resolved = candidate.resolve(strict=True)
                if (
                    not resolved.is_file()
                    or candidate.is_symlink()
                    or not resolved.is_relative_to(resolved_root)
                ):
                    raise ValueError("owned materialization file is missing, linked, or outside root")
                key = str(resolved).casefold()
                if key in seen:
                    raise ValueError("owned materialization contains duplicate paths")
                seen.add(key)
                resolved_paths.append(candidate)
            return cls(root=owned_root, paths=tuple(resolved_paths))
        except Exception:
            shutil.rmtree(owned_root, ignore_errors=True)
            raise

    def cleanup(self) -> None:
        if self._closed:
            return
        shutil.rmtree(self.root, ignore_errors=True)
        self._closed = True

    def __enter__(self) -> "OwnedMaterialization":
        if self._closed:
            raise RuntimeError("owned materialization is already closed")
        return self

    def __exit__(self, *_args) -> None:
        self.cleanup()


def provider_family(provider_key: str) -> str:
    """Canonical CAD-author family for deterministic affinity ranking.

    A distributor-prefixed route such as ``digikey-ultralibrarian`` is still Ultra Librarian
    authored. Unknown providers remain their own family; this function never grants trust or
    compatibility.
    """

    key = provider_key.strip().casefold()
    if not key:
        raise ValueError("provider key is required")
    for family in _KNOWN_PROVIDER_FAMILIES:
        if key == family or key.endswith(f"-{family}"):
            return family
    return key


def cross_eda_report_is_proved(report: object) -> bool:
    """Accept only the two strict cross-EDA report contracts Stockroom understands."""

    if not isinstance(report, dict):
        return False
    try:
        canonical = json.loads(
            json.dumps(
                report,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    except (TypeError, ValueError):
        return False
    if not isinstance(canonical, dict) or canonical.get("valid") is not True:
        return False
    explicit = (
        canonical.get("terminal_equivalence"),
        canonical.get("pad_equivalence"),
        canonical.get("package_equivalence"),
    )
    if any(value is not None for value in explicit):
        return all(value is True for value in explicit)
    if canonical.get("schema") != "stockroom.cross-eda-verification/1":
        return False
    terminal_map = canonical.get("terminal_map")
    geometry = canonical.get("geometry")
    kicad = canonical.get("kicad")
    altium = canonical.get("altium")
    if (
        not isinstance(terminal_map, list)
        or not terminal_map
        or not isinstance(geometry, dict)
        or geometry.get("method") != "mapped-pad-distance-and-size-signatures"
        or not isinstance(kicad, dict)
        or not isinstance(altium, dict)
    ):
        return False
    counts = (
        kicad.get("pin_count"),
        kicad.get("pad_count"),
        altium.get("pin_count"),
        altium.get("pad_count"),
    )
    if not all(isinstance(value, int) and not isinstance(value, bool) and value > 0 for value in counts):
        return False
    kicad_pins, kicad_pads, altium_pins, altium_pads = counts
    return (
        kicad_pins == altium_pins == len(terminal_map)
        and kicad_pads == altium_pads
    )


def select_compatible_retained_kicad(
    store: CadVariantEvidence,
    *,
    identity: ExactIdentity,
    altium_provider_key: str,
    altium_sources: tuple[Path, ...],
    verifier: CrossEdaCandidateVerifier,
    preferred_manifest_digest: str = "",
    temporary_parent: Path | None = None,
) -> CompatibleKicadVariant:
    """Return the first strictly compatible retained KiCad bundle.

    Ranking is deterministic: the optional current installed snapshot, exact provider route, same
    CAD-author family, then the evidence store's existing trust order. A failure is
    candidate-local; it never prevents a later retained bundle from being tried.
    """

    sources = tuple(Path(path) for path in altium_sources)
    if not sources:
        raise ValueError("Altium composition requires native source files")
    for source in sources:
        if not source.is_file() or source.is_symlink():
            raise ValueError(f"Altium composition source is missing or linked: {source}")

    requested_family = provider_family(altium_provider_key)
    listed = list_cad_variants(store, identity=identity, tool="kicad")
    indexed = list(enumerate(listed))
    ranked = sorted(
        indexed,
        key=lambda item: (
            0 if item[1].manifest_digest == preferred_manifest_digest else 1,
            0 if item[1].provider == altium_provider_key else 1,
            0 if provider_family(item[1].provider) == requested_family else 1,
            item[0],
        ),
    )
    attempts: list[CompatibilityAttempt] = []
    for _, descriptor in ranked:
        try:
            resolved = resolve_cad_variant(
                store,
                identity=identity,
                tool="kicad",
                manifest_digest=descriptor.manifest_digest,
            )
            report = _verify_resolved_candidate(
                resolved,
                identity=identity,
                altium_sources=sources,
                verifier=verifier,
                temporary_parent=temporary_parent,
            )
        except Exception as exc:  # noqa: BLE001 - one retained candidate may not hide later ones
            attempts.append(
                CompatibilityAttempt(
                    provider=descriptor.provider,
                    manifest_digest=descriptor.manifest_digest,
                    accepted=False,
                    reason=type(exc).__name__,
                )
            )
            continue
        if not cross_eda_report_is_proved(report):
            attempts.append(
                CompatibilityAttempt(
                    provider=descriptor.provider,
                    manifest_digest=descriptor.manifest_digest,
                    accepted=False,
                    reason="strict verification rejected the report",
                )
            )
            continue
        canonical = json.loads(
            json.dumps(
                report,
                allow_nan=False,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        attempts.append(
            CompatibilityAttempt(
                provider=descriptor.provider,
                manifest_digest=descriptor.manifest_digest,
                accepted=True,
                reason="strict cross-EDA verification passed",
            )
        )
        return CompatibleKicadVariant(
            resolved=resolved,
            verification=canonical,
            attempts=tuple(attempts),
        )
    raise CompatibleKicadVariantNotFound(tuple(attempts))


def _verify_resolved_candidate(
    resolved: ResolvedCadVariant,
    *,
    identity: ExactIdentity,
    altium_sources: tuple[Path, ...],
    verifier: CrossEdaCandidateVerifier,
    temporary_parent: Path | None,
) -> object:
    names = _candidate_names(resolved.descriptor)
    with tempfile.TemporaryDirectory(
        prefix="stockroom-compatible-kicad-",
        dir=None if temporary_parent is None else str(temporary_parent),
    ) as temporary:
        root = Path(temporary)
        materialized: dict[str, Path] = {}
        for asset_kind, name in names.items():
            destination = root / name
            data = resolved.data[asset_kind]
            destination.write_bytes(data)
            if destination.read_bytes() != data:
                raise OSError(f"could not verify materialized KiCad {asset_kind}")
            materialized[asset_kind] = destination
        return verifier(
            identity=identity,
            kicad_symbol=materialized["symbol"],
            kicad_footprint=materialized["footprint"],
            step_model=materialized["model"],
            altium_sources=altium_sources,
        )


def _candidate_names(descriptor: CadVariantDescriptor) -> dict[str, str]:
    names: dict[str, str] = {}
    for artifact in descriptor.artifacts:
        fallback = _KICAD_FILENAMES[artifact.asset_kind]
        names[artifact.asset_kind] = artifact.suggested_name or fallback
    if set(names) != set(_KICAD_FILENAMES):
        raise ValueError("retained KiCad variant does not name every materialized role")
    _validate_materialized_names(tuple(names.values()))
    return names


def _validate_materialized_names(names: tuple[str, ...]) -> None:
    folded: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name or name in {".", ".."}:
            raise ValueError("materialized file name is invalid")
        path = Path(name)
        if path.name != name or path.is_absolute():
            raise ValueError("materialized file name must be path-free")
        key = name.casefold()
        if key in folded:
            raise ValueError("materialized file names collide")
        folded.add(key)


__all__ = [
    "CompatibilityAttempt",
    "CompatibleKicadVariant",
    "CompatibleKicadVariantNotFound",
    "OwnedMaterialization",
    "cross_eda_report_is_proved",
    "provider_family",
    "select_compatible_retained_kicad",
]
