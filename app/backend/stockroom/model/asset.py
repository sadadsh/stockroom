"""One EDA asset: WHERE it is, WHERE IT CAME FROM, and WHAT HAS BEEN CHECKED about it.

Spec section 9. The three parts are deliberately separate objects, because they answer three
different questions and have three different lifetimes:

    ref     the reference itself - a library nickname + entry name, or a file path.
    origin  which vendor supplied it, from what URL, and when. Capture is human-driven across
            several vendors and "SnapMagic, 2026-07-27" and "Ultra Librarian, 2026-07-27" carry
            DIFFERENT trust weight. Without this the library cannot answer the owner's original
            complaint verbatim: "its not trusted where we've gotten them".
    checks  the measurements taken against it. Facts only; the verdict is DERIVED on read (see
            model/trust.py), never stored.

A tool-shaped fact never appears here. `lib` is a KiCad `.kicad_sym` nickname or an Altium
`.SchLib` / `.PcbLib` filename, `name` is the exact entry inside it, `file` is the repo-relative
path of a file-shaped asset such as a 3D model; which of those a kind uses is the kind's
business, and per-tool facts live in `stockroom.eda.registry`.

PRIOR ART (checked before writing, 2026-07-27): the closest published thing is the software
supply-chain attestation shape - SLSA provenance and in-toto attestations pair a subject with
"who produced it, from what, when", and SPDX/CycloneDX carry per-component supplier and
verification data. That is the same problem (an artifact you did not build yourself, whose
trustworthiness depends on where it came from), and the split adopted here - subject / origin /
independently recomputable checks - is taken from it. The formats themselves are REJECTED as a
dependency: they describe build pipelines and package graphs, they are signed documents rather
than editable record fields, and a `.kicad_sym` entry is not a package. The idea travels; the
schema does not.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from stockroom.model.trust import AssetCheck

# The asset slots one tool bundle carries. The names come from the EDA registry's
# `asset_kinds`; they are spelled out here because a dataclass needs real attributes, and
# `tests/backend/model/test_eda_assets.py` locks the two together so a registry that grows a
# kind cannot silently leave this behind.
ASSET_KINDS: tuple[str, ...] = ("symbol", "footprint", "model")


@dataclass
class AssetRef:
    """WHERE an asset is. Vendor library files are stored verbatim; Stockroom only reads their
    entry names."""

    lib: str = ""
    name: str = ""
    file: str = ""

    def is_present(self) -> bool:
        """True when this resolves to something. A container with no entry (`lib` alone) is
        NOT present - that half-filled state is what produced the dangling `Footprint`
        property fixed in 21fce45."""
        return bool(self.name or self.file)

    def to_dict(self) -> dict:
        return {"lib": self.lib, "name": self.name, "file": self.file}

    @classmethod
    def from_dict(cls, d: dict) -> "AssetRef":
        return cls(lib=d.get("lib", ""), name=d.get("name", ""), file=d.get("file", ""))


@dataclass
class AssetOrigin:
    """WHERE AN ASSET CAME FROM. `vendor` is the source key ("ultralibrarian", "samacsys",
    "snapmagic", "kicad-official"), `url` the exact page or endpoint it was taken from, and
    `captured_at` when - so a file acquired before a vendor was distrusted can be found."""

    vendor: str = ""
    url: str = ""
    captured_at: str = ""
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            **self.extra,
            "vendor": self.vendor,
            "url": self.url,
            "captured_at": self.captured_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AssetOrigin":
        known = {"vendor", "url", "captured_at"}
        return cls(
            vendor=d.get("vendor", ""),
            url=d.get("url", ""),
            captured_at=d.get("captured_at", ""),
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class Asset:
    """One asset a part holds for one tool: its reference, its provenance, its evidence."""

    ref: AssetRef = field(default_factory=AssetRef)
    # None means "attached before anyone recorded where it came from". That is a real state
    # and it is not the same as an empty origin: an unattributed asset must read as
    # unattributed, never as one whose vendor happens to be the empty string.
    origin: AssetOrigin | None = None
    checks: list[AssetCheck] = field(default_factory=list)
    extra: dict = field(default_factory=dict)

    def is_present(self) -> bool:
        return self.ref.is_present()

    # The reference's fields, READ-ONLY. An asset's `name` is unambiguously its reference's
    # name - `origin` spells its fields `vendor`/`url`, `checks` spells its `check` - so there
    # is no second meaning for these three to collide with, and a reader holding an Asset
    # should not have to know whether a slot was filled with an Asset or a bare AssetRef.
    #
    # Deliberately not writable. A write has to say WHICH of the three parts it is changing:
    # repointing an asset is `slot = AssetRef(...)` (which drops the stale origin and checks
    # with it, because they described the OLD file), and editing a reference in place is
    # `asset.ref.name = ...`. A silent `asset.name = ...` would leave provenance and evidence
    # attached to a file they were never measured against, which is the one thing this schema
    # exists to prevent.
    @property
    def lib(self) -> str:
        return self.ref.lib

    @property
    def name(self) -> str:
        return self.ref.name

    @property
    def file(self) -> str:
        return self.ref.file

    @classmethod
    def of(cls, value) -> "Asset | None":
        """Coerce a bare `AssetRef` (or an existing `Asset`, or None) into an Asset.

        A bare reference becomes an asset with NO origin and NO checks, which is exactly what
        it is: attached, unattributed, unchecked.
        """
        if value is None or isinstance(value, cls):
            return value
        if isinstance(value, AssetRef):
            return cls(ref=value)
        raise TypeError(f"an asset slot takes an Asset or an AssetRef, not {type(value).__name__}")

    def to_dict(self) -> dict:
        out: dict = {**self.extra, "ref": self.ref.to_dict()}
        # `origin` and `checks` are omitted while empty so adopting this schema does not
        # rewrite every part in a real library to carry a null and an empty list, and a
        # one-field edit stays a one-line diff.
        if self.origin is not None:
            out["origin"] = self.origin.to_dict()
        if self.checks:
            out["checks"] = [c.to_dict() for c in self.checks]
        return out

    @classmethod
    def from_dict(cls, d: dict) -> "Asset":
        known = {"ref", "origin", "checks"}
        origin = d.get("origin")
        return cls(
            ref=AssetRef.from_dict(d.get("ref") or {}),
            origin=AssetOrigin.from_dict(origin) if origin else None,
            checks=[AssetCheck.from_dict(c) for c in (d.get("checks") or []) if isinstance(c, dict)],
            extra={k: v for k, v in d.items() if k not in known},
        )


@dataclass
class EdaAssets:
    """Everything ONE EDA tool holds for one part.

    Each tool gets a full, symmetric bundle. That symmetry is the point: the pre-v2 record had
    implicitly-KiCad flat `symbol`/`footprint`/`model` fields plus bolted-on `altium_symbol` /
    `altium_footprint` and NO Altium model slot, so readiness code had to branch on the tool -
    which is how every part read "CAD Incomplete" forever and how an Altium attach silently
    clobbered the KiCad reference.

    Assigning a bare `AssetRef` to a slot is accepted and wrapped (see `Asset.of`), so
    `record.assets_for("kicad").symbol = AssetRef(...)` keeps meaning "file this reference,
    provenance unknown for now" rather than silently discarding the origin/checks structure.
    """

    symbol: Asset | None = None
    footprint: Asset | None = None
    model: Asset | None = None

    def __setattr__(self, key: str, value) -> None:
        if key in ASSET_KINDS:
            value = Asset.of(value)
        object.__setattr__(self, key, value)

    def get(self, kind: str) -> Asset | None:
        """The Asset for a kind, or None. Lets generic code iterate a tool's registered
        `asset_kinds` instead of naming symbol/footprint/model by hand."""
        if kind not in ASSET_KINDS:
            return None
        return getattr(self, kind, None)

    def set(self, kind: str, value) -> None:
        if kind not in ASSET_KINDS:
            raise KeyError(f"unknown asset kind {kind!r}")
        setattr(self, kind, value)

    def ref(self, kind: str) -> AssetRef | None:
        """Just the reference for a kind, for callers that only need where the asset is."""
        asset = self.get(kind)
        return asset.ref if asset is not None else None

    def is_empty(self) -> bool:
        return all(self.get(k) is None for k in ASSET_KINDS)

    def to_dict(self) -> dict:
        return {k: (a.to_dict() if (a := self.get(k)) else None) for k in ASSET_KINDS}

    @classmethod
    def from_dict(cls, d: dict) -> "EdaAssets":
        out = cls()
        for kind in ASSET_KINDS:
            raw = d.get(kind)
            if isinstance(raw, dict) and raw:
                out.set(kind, Asset.from_dict(raw))
        return out
