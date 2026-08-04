"""Retained candidates: one durable record per artifact discovered in a provider package,
carrying an HONEST validation outcome.

Two rules shape this module.

The first is that a validation result may only assert what existing, tested code actually
proved. Five things can be proved here and nothing else is claimed:

* the real file/container type, through the `capture/classify.py` content sniff;
* parseable structure -- KiCad through `stockroom.kicad` / `stockroom.sexp`, Altium through
  `altium/oleread.py`'s name records, P-CAD through `stockroom.pcad`;
* embedded MPN / manufacturer / package / pin count, where the parser genuinely exposes them;
* symbol pin identifiers against footprint pad identifiers, when BOTH parse;
* a readable ISO-10303-21 STEP model, the same header check the Altium embed path uses;
* a collision with an existing library entry name.

Electrical correctness, geometric correctness beyond what a tested parser returned, 3D
alignment, pin-function semantics and full native Altium validation are NOT claimed anywhere.
An artifact whose container was recognized but whose contents were not proved becomes
``Manual Review Required``. That is the honest default, not a failure.

The second rule is that provenance is never lost to deduplication. Identical bytes from two
providers are ONE retained artifact with TWO provenance records, and re-processing a package
that is already known returns the retained candidates rather than re-judging them. The
original provider package is kept until an import succeeds or the person removes it.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import tempfile
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from enum import Enum
from pathlib import Path

from stockroom.capture.classify import AssetGroup, classify_asset
from stockroom.capture.identity import same_manufacturer, same_mpn
from stockroom.capture.requirements import Requirement
from stockroom.ingest.sandbox import (
    ARCHIVE_SUFFIXES,
    DEFAULT_ARCHIVE_POLICY,
    ArchivePolicy,
    sha256_of,
    unpack_inputs,
)
from stockroom.text import counted

_SCHEMA = "stockroom.retained-candidates/1"


class ValidationOutcome(str, Enum):
    """The complete outcome vocabulary. These exact strings are the wire contract."""

    READY_TO_IMPORT = "Ready To Import"
    PARTIAL_PACKAGE = "Partial Package"
    MANUAL_REVIEW_REQUIRED = "Manual Review Required"
    COMPONENT_MISMATCH = "Component Mismatch"
    PACKAGE_MISMATCH = "Package Mismatch"
    UNSUPPORTED_FILE = "Unsupported File"
    INVALID_FILE = "Invalid File"
    IMPORTED = "Imported"
    IMPORT_FAILED = "Import Failed"


# Artifact kinds, kept to the vocabulary the rest of the backend already speaks.
KIND_SYMBOL = "symbol"
KIND_FOOTPRINT = "footprint"
KIND_MODEL = "model"
KIND_LIBRARY = "library"  # one container holding both a symbol and a footprint
KIND_SUPPORTING = "supporting"
KIND_PROHIBITED = "prohibited"
KIND_UNKNOWN = "unknown"

_FORMAT_BY_SUFFIX = {
    ".kicad_sym": "kicad_symbol_library",
    ".lib": "kicad_legacy_symbol_library",
    ".kicad_mod": "kicad_footprint",
    ".step": "step_model",
    ".stp": "step_model",
    ".wrl": "vrml_model",
    ".schlib": "altium_schlib",
    ".pcblib": "altium_pcblib",
    ".intlib": "altium_intlib",
    ".lia": "pcad_ascii_library",
}

# Property aliases a provider KiCad symbol actually uses, matching capture/cross_eda.py.
_MANUFACTURER_FIELDS = ("manufacturer", "manufacturer name", "manufacturer_name", "mf")
_MPN_FIELDS = (
    "manufacturer part number",
    "manufacturer_part_number",
    "part number",
    "partnumber",
    "mpn",
    "mp",
)
# Deliberately NOT "footprint": that property holds a library reference, not a package name.
_PACKAGE_FIELDS = ("package", "package name", "package_name")

_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"

# The tool-complete role sets. A package that covers neither is genuinely partial.
_KICAD_COMPLETE = frozenset(
    {Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT, Requirement.KICAD_MODEL}
)
_ALTIUM_COMPLETE = frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT})


def _key(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _package_key(value: str) -> str:
    """Compare package names by their alphanumerics: `SOIC-8` and `SOIC8` are one package."""
    return "".join(ch for ch in _key(value) if ch.isalnum())


def _field(properties: dict[str, str], aliases: tuple[str, ...]) -> str:
    normalized = {
        _key(key): value.strip() for key, value in properties.items() if value.strip()
    }
    found = {normalized[alias] for alias in aliases if alias in normalized}
    return found.pop() if len(found) == 1 else ""


@dataclass(frozen=True)
class CandidateProvenance:
    """Where one copy of these exact bytes came from. Never merged away."""

    provider_id: str
    source_package_digest: str
    source_url: str = ""
    original_filename: str = ""


@dataclass(frozen=True)
class ArtifactFacts:
    """Everything one artifact proved about itself, and nothing it did not."""

    kind: str
    detected_format: str
    outcome: ValidationOutcome
    messages: tuple[str, ...] = ()
    requirements: frozenset[Requirement] = frozenset()
    mpn: str = ""
    manufacturer: str = ""
    package: str = ""
    pins: tuple[str, ...] = ()
    pads: tuple[str, ...] = ()

    @property
    def manual_review_required(self) -> bool:
        return self.outcome is ValidationOutcome.MANUAL_REVIEW_REQUIRED

    @property
    def rejected(self) -> bool:
        return self.outcome in {
            ValidationOutcome.INVALID_FILE,
            ValidationOutcome.UNSUPPORTED_FILE,
        }


@dataclass
class RetainedCandidate:
    """One retained artifact, its proven facts, and every provenance that delivered it."""

    candidate_id: str
    component_id: str
    artifact_digest: str
    original_filename: str
    stored_path: str
    artifact_kind: str
    detected_format: str
    validation_result: str
    validation_messages: tuple[str, ...] = ()
    mpn: str = ""
    manufacturer: str = ""
    package: str = ""
    pins: tuple[str, ...] = ()
    pads: tuple[str, ...] = ()
    manual_review_required: bool = False
    rejected: bool = False
    selected_slot: str = ""
    provenances: tuple[CandidateProvenance, ...] = field(default_factory=tuple)

    @property
    def provider_id(self) -> str:
        """The first provider that delivered these bytes; the rest stay in `provenances`."""
        return self.provenances[0].provider_id if self.provenances else ""

    @property
    def source_package_digest(self) -> str:
        return self.provenances[0].source_package_digest if self.provenances else ""

    @property
    def source_url(self) -> str:
        return self.provenances[0].source_url if self.provenances else ""

    @property
    def source_package_digests(self) -> tuple[str, ...]:
        return tuple(item.source_package_digest for item in self.provenances)

    def to_json(self) -> dict:
        data = asdict(self)
        data["provenances"] = [asdict(item) for item in self.provenances]
        for key in ("validation_messages", "pins", "pads"):
            data[key] = list(data[key])
        return data

    @classmethod
    def from_json(cls, data: dict) -> "RetainedCandidate":
        return cls(
            candidate_id=str(data["candidate_id"]),
            component_id=str(data["component_id"]),
            artifact_digest=str(data["artifact_digest"]),
            original_filename=str(data["original_filename"]),
            stored_path=str(data["stored_path"]),
            artifact_kind=str(data["artifact_kind"]),
            detected_format=str(data["detected_format"]),
            validation_result=str(data["validation_result"]),
            validation_messages=tuple(data.get("validation_messages", ())),
            mpn=str(data.get("mpn", "")),
            manufacturer=str(data.get("manufacturer", "")),
            package=str(data.get("package", "")),
            pins=tuple(data.get("pins", ())),
            pads=tuple(data.get("pads", ())),
            manual_review_required=bool(data.get("manual_review_required", False)),
            rejected=bool(data.get("rejected", False)),
            selected_slot=str(data.get("selected_slot", "")),
            provenances=tuple(
                CandidateProvenance(
                    provider_id=str(item.get("provider_id", "")),
                    source_package_digest=str(item.get("source_package_digest", "")),
                    source_url=str(item.get("source_url", "")),
                    original_filename=str(item.get("original_filename", "")),
                )
                for item in data.get("provenances", ())
            ),
        )


# --- validation -------------------------------------------------------------


def _step_is_readable(path: Path) -> bool:
    """The exact ISO-10303-21 header check `altium/native_authoring.py` embeds against."""
    try:
        return b"ISO-10303-21" in path.read_bytes()[:256]
    except OSError:
        return False


def _is_ole(path: Path) -> bool:
    try:
        with open(path, "rb") as handle:
            return handle.read(8) == _OLE_MAGIC
    except OSError:
        return False


def _kicad_symbol_facts(path: Path, expected_mpn: str) -> tuple[dict, list[str], list[str]]:
    """(properties, pin numbers, entry names) for the one entry this artifact is about."""
    from stockroom.kicad.symbol_lib import SymbolLib
    from stockroom.sexp.document import SexpDocument

    lib = SymbolLib.load(path)
    names = lib.symbol_names
    if not names:
        raise ValueError("the KiCad symbol library declares no symbols")
    entry = ""
    if expected_mpn:
        matched = [name for name in names if same_mpn(name, expected_mpn)]
        if len(matched) == 1:
            entry = matched[0]
    if not entry and len(names) == 1:
        entry = names[0]
    if not entry:
        return {}, [], names
    document = SexpDocument.load(path)
    node = next(
        item
        for item in document.root.find_all("symbol")
        if len(item.children) >= 2 and item.children[1].value == entry
    )
    properties: dict[str, str] = {}
    for prop in node.find_all("property"):
        if len(prop.children) >= 3:
            properties[prop.children[1].value] = prop.children[2].value
    pins: list[str] = []
    for child in node.iter_descendants():
        if child.name != "pin":
            continue
        number = child.find("number")
        if number is not None and len(number.children) >= 2:
            value = str(number.children[1].value).strip()
            if value and value not in pins:
                pins.append(value)
    return properties, pins, [entry]


def _classified_facts(path: Path) -> tuple[str, str]:
    """(artifact kind, detected format) from the suffix, falling back to the content sniff."""
    suffix = path.suffix.casefold()
    detected = _FORMAT_BY_SUFFIX.get(suffix, "")
    if detected:
        kind = {
            "kicad_symbol_library": KIND_SYMBOL,
            "kicad_legacy_symbol_library": KIND_SYMBOL,
            "kicad_footprint": KIND_FOOTPRINT,
            "step_model": KIND_MODEL,
            "vrml_model": KIND_MODEL,
            "altium_schlib": KIND_SYMBOL,
            "altium_pcblib": KIND_FOOTPRINT,
            "altium_intlib": KIND_LIBRARY,
            "pcad_ascii_library": KIND_LIBRARY,
        }[detected]
        return kind, detected
    classified = classify_asset(path)
    if classified.tool == "altium" and classified.kind == "symbol":
        return KIND_SYMBOL, "altium_schlib"
    if classified.tool == "altium" and classified.kind == "footprint":
        return KIND_FOOTPRINT, "altium_pcblib"
    return KIND_UNKNOWN, "unknown"


def inspect_artifact(
    path: Path,
    *,
    expected_mpn: str = "",
    expected_manufacturer: str = "",
    expected_package: str = "",
    existing_library_names: Iterable[str] = (),
) -> ArtifactFacts:
    """Prove what can be proved about one artifact and name the outcome honestly."""

    path = Path(path)
    classified = classify_asset(path)
    if classified.group is AssetGroup.PROHIBITED:
        return ArtifactFacts(
            kind=KIND_PROHIBITED,
            detected_format="executable_or_script",
            outcome=ValidationOutcome.INVALID_FILE,
            messages=("the file is executable, script or shortcut content and was refused",),
        )
    if path.suffix.casefold() in ARCHIVE_SUFFIXES:
        return ArtifactFacts(
            kind=KIND_UNKNOWN,
            detected_format="nested_archive",
            outcome=ValidationOutcome.MANUAL_REVIEW_REQUIRED,
            messages=("a nested archive was retained but not expanded",),
        )
    if classified.group is AssetGroup.SUPPORTING:
        return ArtifactFacts(
            kind=KIND_SUPPORTING,
            detected_format=path.suffix.casefold().lstrip(".") or "text",
            outcome=ValidationOutcome.UNSUPPORTED_FILE,
            messages=("supporting material: retained beside the part, never auto-imported",),
        )
    if classified.group is not AssetGroup.IMPORTABLE_CAD:
        return ArtifactFacts(
            kind=KIND_UNKNOWN,
            detected_format="unknown",
            outcome=ValidationOutcome.UNSUPPORTED_FILE,
            messages=("nothing here recognizes this file; it is retained but not importable",),
        )

    kind, detected = _classified_facts(path)
    existing = {_key(name) for name in existing_library_names if str(name).strip()}
    messages: list[str] = []
    mpn = manufacturer = package = ""
    pins: tuple[str, ...] = ()
    pads: tuple[str, ...] = ()
    entry_names: list[str] = []
    # A footprint identifies a PACKAGE and a model identifies nothing; only a symbol or a
    # whole-component library can carry the component's identity. Demanding an embedded MPN
    # from a `.kicad_mod` would manufacture a review requirement out of a format's design.
    identity_checkable = kind in {KIND_SYMBOL, KIND_LIBRARY}

    if detected == "kicad_symbol_library":
        try:
            properties, pin_numbers, entry_names = _kicad_symbol_facts(path, expected_mpn)
        except Exception as exc:  # noqa: BLE001 - an unparseable library is simply invalid
            return ArtifactFacts(
                kind=kind,
                detected_format=detected,
                outcome=ValidationOutcome.INVALID_FILE,
                messages=(f"the KiCad symbol library could not be parsed: {exc}",),
            )
        if not properties and len(entry_names) > 1:
            return ArtifactFacts(
                kind=kind,
                detected_format=detected,
                outcome=ValidationOutcome.MANUAL_REVIEW_REQUIRED,
                requirements=frozenset({Requirement.KICAD_SYMBOL}),
                messages=(
                    f"{len(entry_names)} symbols are present and none uniquely matches the "
                    "component; a person must choose",
                ),
            )
        mpn = _field(properties, _MPN_FIELDS) or (
            entry_names[0] if entry_names and same_mpn(entry_names[0], expected_mpn) else ""
        )
        manufacturer = _field(properties, _MANUFACTURER_FIELDS)
        package = _field(properties, _PACKAGE_FIELDS)
        pins = tuple(pin_numbers)
        messages.append(f"parsed a KiCad symbol library with {len(pins)} numbered pins")
        if not pins:
            messages.append("the symbol exposes no numbered pins")

    elif detected == "kicad_legacy_symbol_library":
        return ArtifactFacts(
            kind=kind,
            detected_format=detected,
            outcome=ValidationOutcome.MANUAL_REVIEW_REQUIRED,
            requirements=frozenset({Requirement.KICAD_SYMBOL}),
            messages=(
                "the legacy KiCad .lib format has no tested parser here; the container was "
                "recognized and nothing about its contents is claimed",
            ),
        )

    elif detected == "kicad_footprint":
        from stockroom.kicad.footprint import Footprint

        try:
            footprint = Footprint.load(path)
            pads = tuple(
                dict.fromkeys(pad.number.strip() for pad in footprint.pads if pad.number.strip())
            )
            package = footprint.name.strip()
        except Exception as exc:  # noqa: BLE001 - an unparseable footprint is simply invalid
            return ArtifactFacts(
                kind=kind,
                detected_format=detected,
                outcome=ValidationOutcome.INVALID_FILE,
                messages=(f"the KiCad footprint could not be parsed: {exc}",),
            )
        entry_names = [package] if package else []
        messages.append(f"parsed a KiCad footprint with {len(pads)} numbered pads")

    elif detected in {"step_model", "vrml_model"}:
        if detected == "step_model":
            if not _step_is_readable(path):
                return ArtifactFacts(
                    kind=kind,
                    detected_format=detected,
                    outcome=ValidationOutcome.INVALID_FILE,
                    messages=("the model has no ISO-10303-21 STEP header",),
                )
            messages.append("read an ISO-10303-21 STEP header; 3D alignment is not claimed")
        else:
            return ArtifactFacts(
                kind=kind,
                detected_format=detected,
                outcome=ValidationOutcome.MANUAL_REVIEW_REQUIRED,
                requirements=frozenset({Requirement.KICAD_MODEL}),
                messages=(
                    "no tested VRML parser exists here; the model was retained unvalidated",
                ),
            )

    elif detected in {"altium_schlib", "altium_pcblib"}:
        from stockroom.altium.oleread import read_footprint_names, read_symbol_names

        reader = read_symbol_names if detected == "altium_schlib" else read_footprint_names
        try:
            entry_names = [name for name in reader(path) if name.strip()]
        except Exception as exc:  # noqa: BLE001 - an unreadable container is simply invalid
            return ArtifactFacts(
                kind=kind,
                detected_format=detected,
                outcome=ValidationOutcome.INVALID_FILE,
                messages=(f"the Altium library could not be read: {exc}",),
            )
        if not entry_names:
            return ArtifactFacts(
                kind=kind,
                detected_format=detected,
                outcome=ValidationOutcome.INVALID_FILE,
                messages=("the Altium library exposes no entry names",),
            )
        if detected == "altium_schlib":
            matched = [name for name in entry_names if same_mpn(name, expected_mpn)]
            mpn = matched[0] if len(matched) == 1 else ""
            if expected_mpn and not matched:
                # The LibRef records are the container's authoritative component list, so a
                # name that disagrees is a proved mismatch, not an absence of evidence.
                return ArtifactFacts(
                    kind=kind,
                    detected_format=detected,
                    outcome=ValidationOutcome.COMPONENT_MISMATCH,
                    requirements=classified.requirements,
                    messages=(
                        f"the Altium library holds {entry_names!r}, none of which is "
                        f"{expected_mpn!r}",
                    ),
                )
        else:
            package = entry_names[0] if len(entry_names) == 1 else ""
            if expected_package:
                matched = [
                    name
                    for name in entry_names
                    if _package_key(name) == _package_key(expected_package)
                ]
                package = matched[0] if len(matched) == 1 else package
        messages.append(
            f"read {counted(len(entry_names), 'entry name')} from the Altium container; its "
            "geometry and electrical content are not validated here"
        )

    elif detected == "altium_intlib":
        if not _is_ole(path):
            return ArtifactFacts(
                kind=kind,
                detected_format=detected,
                outcome=ValidationOutcome.INVALID_FILE,
                messages=("the .IntLib is not an OLE compound file",),
            )
        return ArtifactFacts(
            kind=kind,
            detected_format=detected,
            outcome=ValidationOutcome.MANUAL_REVIEW_REQUIRED,
            requirements=_ALTIUM_COMPLETE,
            messages=(
                "only the compiled Altium container was recognized; its embedded sources must "
                "be extracted and reviewed before anything about them is claimed",
            ),
        )

    elif detected == "pcad_ascii_library":
        from stockroom.pcad import normalize, parse_file

        try:
            library = normalize(parse_file(path))
        except Exception as exc:  # noqa: BLE001 - an unparseable library is simply invalid
            return ArtifactFacts(
                kind=kind,
                detected_format=detected,
                outcome=ValidationOutcome.INVALID_FILE,
                messages=(f"the P-CAD ASCII library could not be parsed: {exc}",),
            )
        mpn = library.mpn
        manufacturer = library.manufacturer
        package = library.default_footprint
        pins = tuple(dict.fromkeys(pin.number for pin in library.symbol.pins if pin.number))
        default = next(
            (item for item in library.footprints if item.default),
            library.footprints[0] if library.footprints else None,
        )
        pads = tuple(dict.fromkeys(pad.number for pad in default.pads)) if default else ()
        entry_names = [package] if package else []
        messages.append(
            "parsed a P-CAD ASCII library; it is importable only through "
            "altium/converter.py's normalization"
        )
    else:
        return ArtifactFacts(
            kind=KIND_UNKNOWN,
            detected_format="unknown",
            outcome=ValidationOutcome.UNSUPPORTED_FILE,
            messages=("nothing here recognizes this file; it is retained but not importable",),
        )

    requirements = classified.requirements
    outcome = ValidationOutcome.READY_TO_IMPORT

    if expected_mpn and identity_checkable:
        if mpn and not same_mpn(mpn, expected_mpn):
            messages.append(f"embedded MPN {mpn!r} does not match {expected_mpn!r}")
            outcome = ValidationOutcome.COMPONENT_MISMATCH
        elif not mpn:
            messages.append(
                f"no embedded identifier proves this artifact belongs to {expected_mpn!r}"
            )
            outcome = ValidationOutcome.MANUAL_REVIEW_REQUIRED
    if (
        outcome is ValidationOutcome.READY_TO_IMPORT
        and expected_manufacturer
        and manufacturer
        and not same_manufacturer(manufacturer, expected_manufacturer)
    ):
        messages.append(
            f"embedded manufacturer {manufacturer!r} does not match {expected_manufacturer!r}"
        )
        outcome = ValidationOutcome.COMPONENT_MISMATCH
    if (
        outcome is ValidationOutcome.READY_TO_IMPORT
        and expected_package
        and package
        and _package_key(package) != _package_key(expected_package)
    ):
        messages.append(f"package {package!r} does not match {expected_package!r}")
        outcome = ValidationOutcome.PACKAGE_MISMATCH
    collisions = [name for name in entry_names if _key(name) in existing]
    if collisions and outcome is ValidationOutcome.READY_TO_IMPORT:
        messages.append(
            f"library entry {collisions[0]!r} already exists; a person must resolve the conflict"
        )
        outcome = ValidationOutcome.MANUAL_REVIEW_REQUIRED

    return ArtifactFacts(
        kind=kind,
        detected_format=detected,
        outcome=outcome,
        messages=tuple(messages),
        requirements=requirements,
        mpn=mpn,
        manufacturer=manufacturer,
        package=package,
        pins=pins,
        pads=pads,
    )


def assess_package(facts: Sequence[ArtifactFacts]) -> list[ArtifactFacts]:
    """Cross-artifact checks: pin/pad agreement, then whole-package completeness.

    Both are package-level truths a single artifact cannot know, and both only ever
    DOWNGRADE a `Ready To Import`. Nothing is ever promoted here.
    """

    results = list(facts)
    symbol = next(
        (item for item in results if item.kind == KIND_SYMBOL and item.pins), None
    )
    footprint = next(
        (item for item in results if item.kind == KIND_FOOTPRINT and item.pads), None
    )
    if symbol is not None and footprint is not None:
        if {_key(pin) for pin in symbol.pins} != {_key(pad) for pad in footprint.pads}:
            note = (
                f"the symbol's {len(symbol.pins)} pin identifiers and the footprint's "
                f"{len(footprint.pads)} pad identifiers are not the same set"
            )
            for index, item in enumerate(results):
                if item is symbol or item is footprint:
                    results[index] = replace(
                        item,
                        outcome=ValidationOutcome.PACKAGE_MISMATCH,
                        messages=item.messages + (note,),
                    )

    covered: set[Requirement] = set()
    for item in results:
        if item.outcome in {ValidationOutcome.INVALID_FILE, ValidationOutcome.UNSUPPORTED_FILE}:
            continue
        covered |= set(item.requirements)
    if _KICAD_COMPLETE <= covered or _ALTIUM_COMPLETE <= covered:
        return results
    note = "the package does not carry one complete symbol, footprint and model set"
    return [
        replace(
            item,
            outcome=ValidationOutcome.PARTIAL_PACKAGE,
            messages=item.messages + (note,),
        )
        if item.outcome is ValidationOutcome.READY_TO_IMPORT
        else item
        for item in results
    ]


# --- retention --------------------------------------------------------------


def candidate_id_for(component_id: str, artifact_digest: str) -> str:
    """A stable id: the same component and the same bytes always name the same candidate."""
    seed = f"{component_id}\x00{artifact_digest}".encode()
    return hashlib.sha256(seed).hexdigest()[:32]


class RetainedCandidateStore:
    """Durable retained candidates for one library root.

    Layout under `root`:
      * `candidates.json` -- the index;
      * `artifacts/<digest>/<filename>` -- one copy of each distinct artifact;
      * `packages/<digest>/<filename>` -- the untouched provider package, kept until every
        candidate it produced has imported or the person releases it.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._index = self.root / "candidates.json"
        self._candidates: list[RetainedCandidate] = []
        self._load()

    # -- persistence
    def _load(self) -> None:
        if not self._index.is_file():
            return
        try:
            data = json.loads(self._index.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return
        self._candidates = [
            RetainedCandidate.from_json(item) for item in data.get("candidates", [])
        ]

    def _save(self) -> None:
        payload = {
            "schema": _SCHEMA,
            "candidates": [item.to_json() for item in self._candidates],
        }
        self._index.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    # -- reads
    def all_candidates(self) -> list[RetainedCandidate]:
        return list(self._candidates)

    def candidates_for(self, component_id: str) -> list[RetainedCandidate]:
        return [item for item in self._candidates if item.component_id == component_id]

    def candidate(self, candidate_id: str) -> RetainedCandidate | None:
        return next(
            (item for item in self._candidates if item.candidate_id == candidate_id), None
        )

    def package_path(self, package_digest: str) -> Path | None:
        directory = self.root / "packages" / package_digest
        if not directory.is_dir():
            return None
        return next((item for item in sorted(directory.iterdir()) if item.is_file()), None)

    # -- writes
    def retain_package(
        self,
        *,
        component_id: str,
        provider_id: str,
        package_path: Path,
        source_url: str = "",
        expected_mpn: str = "",
        expected_manufacturer: str = "",
        expected_package: str = "",
        existing_library_names: Iterable[str] = (),
        policy: ArchivePolicy = DEFAULT_ARCHIVE_POLICY,
    ) -> list[RetainedCandidate]:
        """Retain one provider package's artifacts, or return what is already retained.

        The bounded sandbox does the extraction, so an unsafe archive raises `IngestError`
        from there rather than becoming a quietly-degraded candidate. A package that has
        already been processed for this component is NOT re-judged: its retained candidates
        are returned as they stand, which is why re-processing can never report `Invalid File`
        for work that already succeeded.
        """

        package_path = Path(package_path)
        if not package_path.is_file():
            raise ValueError(f"a provider package must be a file: {package_path}")
        package_digest = sha256_of(package_path)
        known = [
            item
            for item in self._candidates
            if item.component_id == component_id
            and package_digest in item.source_package_digests
        ]
        if known:
            return known

        workdir = Path(tempfile.mkdtemp(prefix="sr-candidates-"))
        try:
            unpacked = unpack_inputs([package_path], workdir, policy=policy)
            artifacts = sorted(
                (
                    path
                    for item in unpacked
                    for path in item.root.rglob("*")
                    if path.is_file()
                ),
                key=lambda path: str(path).casefold(),
            )
            facts = assess_package(
                [
                    inspect_artifact(
                        path,
                        expected_mpn=expected_mpn,
                        expected_manufacturer=expected_manufacturer,
                        expected_package=expected_package,
                        existing_library_names=existing_library_names,
                    )
                    for path in artifacts
                ]
            )
            retained = [
                self._retain(
                    component_id=component_id,
                    path=path,
                    facts=fact,
                    provenance=CandidateProvenance(
                        provider_id=provider_id,
                        source_package_digest=package_digest,
                        source_url=source_url,
                        original_filename=path.name,
                    ),
                )
                for path, fact in zip(artifacts, facts)
            ]
            self._keep_provider_package(package_digest, package_path)
            self._save()
            return retained
        finally:
            shutil.rmtree(workdir, ignore_errors=True)

    def _retain(
        self,
        *,
        component_id: str,
        path: Path,
        facts: ArtifactFacts,
        provenance: CandidateProvenance,
    ) -> RetainedCandidate:
        digest = sha256_of(path)
        existing = next(
            (
                item
                for item in self._candidates
                if item.component_id == component_id and item.artifact_digest == digest
            ),
            None,
        )
        if existing is not None:
            # Same bytes, different download: ONE artifact, one more provenance. The
            # earlier validation stands -- identical bytes cannot validate differently.
            if provenance not in existing.provenances:
                existing.provenances = existing.provenances + (provenance,)
            return existing
        stored = self.root / "artifacts" / digest / path.name
        stored.parent.mkdir(parents=True, exist_ok=True)
        if not stored.exists():
            shutil.copyfile(path, stored)
        candidate = RetainedCandidate(
            candidate_id=candidate_id_for(component_id, digest),
            component_id=component_id,
            artifact_digest=digest,
            original_filename=path.name,
            stored_path=stored.relative_to(self.root).as_posix(),
            artifact_kind=facts.kind,
            detected_format=facts.detected_format,
            validation_result=facts.outcome.value,
            validation_messages=facts.messages,
            mpn=facts.mpn,
            manufacturer=facts.manufacturer,
            package=facts.package,
            pins=facts.pins,
            pads=facts.pads,
            manual_review_required=facts.manual_review_required,
            rejected=facts.rejected,
            provenances=(provenance,),
        )
        self._candidates.append(candidate)
        return candidate

    def _keep_provider_package(self, package_digest: str, package_path: Path) -> None:
        """Hold the untouched download until an import succeeds or the person releases it."""
        destination = self.root / "packages" / package_digest / package_path.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists():
            shutil.copyfile(package_path, destination)

    def select_slot(self, candidate_id: str, slot: str) -> RetainedCandidate:
        candidate = self._require(candidate_id)
        candidate.selected_slot = slot
        self._save()
        return candidate

    def reject(self, candidate_id: str, reason: str) -> RetainedCandidate:
        candidate = self._require(candidate_id)
        candidate.rejected = True
        candidate.validation_messages = candidate.validation_messages + (reason,)
        self._save()
        return candidate

    def mark_imported(self, candidate_id: str) -> RetainedCandidate:
        candidate = self._require(candidate_id)
        candidate.validation_result = ValidationOutcome.IMPORTED.value
        candidate.manual_review_required = False
        self._save()
        self._release_finished_packages()
        return candidate

    def mark_import_failed(self, candidate_id: str, reason: str) -> RetainedCandidate:
        candidate = self._require(candidate_id)
        candidate.validation_result = ValidationOutcome.IMPORT_FAILED.value
        candidate.validation_messages = candidate.validation_messages + (reason,)
        self._save()
        return candidate

    def release_package(self, package_digest: str) -> None:
        """The person removes the retained provider package."""
        shutil.rmtree(self.root / "packages" / package_digest, ignore_errors=True)

    def _release_finished_packages(self) -> None:
        directory = self.root / "packages"
        if not directory.is_dir():
            return
        for stored in sorted(directory.iterdir()):
            if not stored.is_dir():
                continue
            produced = [
                item
                for item in self._candidates
                if stored.name in item.source_package_digests and not item.rejected
            ]
            importable = [
                item
                for item in produced
                if item.validation_result
                not in {
                    ValidationOutcome.UNSUPPORTED_FILE.value,
                    ValidationOutcome.INVALID_FILE.value,
                }
            ]
            if importable and all(
                item.validation_result == ValidationOutcome.IMPORTED.value
                for item in importable
            ):
                shutil.rmtree(stored, ignore_errors=True)

    def _require(self, candidate_id: str) -> RetainedCandidate:
        candidate = self.candidate(candidate_id)
        if candidate is None:
            raise KeyError(f"no retained candidate {candidate_id!r}")
        return candidate


__all__ = [
    "ArtifactFacts",
    "CandidateProvenance",
    "KIND_FOOTPRINT",
    "KIND_LIBRARY",
    "KIND_MODEL",
    "KIND_PROHIBITED",
    "KIND_SUPPORTING",
    "KIND_SYMBOL",
    "KIND_UNKNOWN",
    "RetainedCandidate",
    "RetainedCandidateStore",
    "ValidationOutcome",
    "assess_package",
    "candidate_id_for",
    "inspect_artifact",
]
