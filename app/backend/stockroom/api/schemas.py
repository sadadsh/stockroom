"""Thin response DTOs over the engine dataclasses. These are a PRESENTATION shape,
never a second schema of record: the source of truth stays the PartRecord JSON and
the derived index (spec sections 5.1, 5.2)."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator

from stockroom.store.index import Facets as _Facets
from stockroom.store.index import IndexRow
from stockroom.store.parametric import ParametricFacets as _ParametricFacets
from stockroom.store.project_index import ProjectIndexRow


class PartSummary(BaseModel):
    id: str
    display_name: str
    category: str
    mpn: str
    manufacturer: str
    is_complete: bool
    missing: list[str] = []

    @classmethod
    def from_row(cls, row: IndexRow) -> "PartSummary":
        return cls(
            id=row.id,
            display_name=row.display_name,
            category=row.category,
            mpn=row.mpn,
            manufacturer=row.manufacturer,
            is_complete=row.is_complete,
            missing=list(row.missing),
        )


def _scalar_specs(specs: dict) -> dict:
    """The scalar spec values only (str / number / bool, non-empty) - the structured entries
    in the bag (the pinout list, per-key provenance) are not table columns, so they are dropped
    from the search row. Mirrors the parametric aggregator's notion of a facetable value, so a
    column and its facet always agree on what counts as a spec."""
    out: dict = {}
    for key, value in (specs or {}).items():
        if isinstance(value, str):
            if value.strip():
                out[key] = value
        elif isinstance(value, (int, float, bool)):
            out[key] = value
    return out


def _row_sourcing(record) -> tuple[int | None, float | None, str]:
    """A flat ``(stock, unit_price, currency)`` from a record's stored purchase list for the
    Stock / Unit columns: the qty-1 (lowest tier) price off the purchase that carries breaks,
    else the first purchase's stock. Null-safe - a part with no purchase reports ``(None, None,
    "")`` rather than raising. Mirrors ``library_price_index``'s best-purchase choice."""
    purchases = list(getattr(record, "purchase", None) or [])
    best = next((p for p in purchases if getattr(p, "price_breaks", None)), None)
    if best is None:
        best = purchases[0] if purchases else None
    if best is None:
        return None, None, ""
    breaks = []
    for b in (getattr(best, "price_breaks", None) or []):
        try:
            breaks.append((int(b["qty"]), float(b["price"])))
        except (KeyError, TypeError, ValueError):
            continue
    breaks.sort(key=lambda qp: qp[0])
    unit_price = breaks[0][1] if breaks else None
    return getattr(best, "stock", None), unit_price, getattr(best, "currency", "") or ""


class SearchRow(BaseModel):
    """A RICH results row for the modular search table: the lean identity plus the part's own
    spec bag and a flattened sourcing summary. The table picks its columns from ``specs`` on the
    frontend, so a new spec becomes a column with zero backend change - the endpoint hands over
    the data, never a hardcoded per-category column list."""

    id: str
    display_name: str
    category: str
    mpn: str
    manufacturer: str
    is_complete: bool
    missing: list[str] = []
    specs: dict[str, Any] = {}
    stock: int | None = None
    unit_price: float | None = None
    currency: str = ""

    @classmethod
    def from_row_and_record(cls, row: IndexRow, record) -> "SearchRow":
        stock, unit_price, currency = _row_sourcing(record)
        return cls(
            id=row.id,
            display_name=row.display_name,
            category=row.category,
            mpn=row.mpn,
            manufacturer=row.manufacturer,
            is_complete=row.is_complete,
            missing=list(row.missing),
            specs=_scalar_specs(getattr(record, "specs", None) or {}),
            stock=stock,
            unit_price=unit_price,
            currency=currency,
        )


class FacetsDTO(BaseModel):
    by_category: dict[str, int]
    by_manufacturer: dict[str, int]
    complete: int
    incomplete: int

    @classmethod
    def from_facets(cls, f: _Facets) -> "FacetsDTO":
        return cls(
            by_category=f.by_category,
            by_manufacturer=f.by_manufacturer,
            complete=f.complete,
            incomplete=f.incomplete,
        )


class FacetOptionDTO(BaseModel):
    value: str
    count: int


class ParametricFacetDTO(BaseModel):
    """One filter dimension GENERATED from the spec bag (never a hardcoded parameter
    list). `kind` is "options" (top-N distinct values with counts) or "range" (a numeric
    min/max, with `unit` when the values agree on one). Only the fields the kind uses are
    populated; the others stay null (an options facet leaves min/max/unit null, a range
    facet leaves options null)."""

    key: str
    label: str
    kind: str
    count: int
    options: list[FacetOptionDTO] | None = None
    min: float | None = None
    max: float | None = None
    unit: str | None = None


class ParametricFacetsDTO(BaseModel):
    category: str | None = None
    facets: list[ParametricFacetDTO]
    total: int

    @classmethod
    def from_aggregate(cls, agg: _ParametricFacets) -> "ParametricFacetsDTO":
        return cls(
            category=agg.category,
            facets=[
                ParametricFacetDTO(
                    key=f.key,
                    label=f.label,
                    kind=f.kind,
                    count=f.count,
                    options=(
                        [FacetOptionDTO(value=o.value, count=o.count) for o in f.options]
                        if f.options is not None
                        else None
                    ),
                    min=f.min,
                    max=f.max,
                    unit=f.unit,
                )
                for f in agg.facets
            ],
            total=agg.total,
        )


class DuplicateGroup(BaseModel):
    """Parts that share one duplicate key (an MPN or a footprint name), the members
    ordered most-complete-first so the keep-candidate is the first entry."""

    key: str
    parts: list[PartSummary]


class DuplicatesDTO(BaseModel):
    by_mpn: list[DuplicateGroup]
    by_footprint: list[DuplicateGroup]


class EditFieldBody(BaseModel):
    field: str
    value: object


class MoveBody(BaseModel):
    category: str


class ProjectSummary(BaseModel):
    """The list shape for a registered KiCad project (M7), served from the derived
    project index. board_count/sheet_count and has_git are the digest fields the
    Projects list renders; the full record (paths, git_root, audit_digest) loads on
    detail. A presentation shape, never a second schema of record."""

    id: str
    name: str
    root: str
    board_count: int
    sheet_count: int
    has_git: bool
    registered_at: str

    @classmethod
    def from_row(cls, row: ProjectIndexRow) -> "ProjectSummary":
        return cls(
            id=row.id,
            name=row.name,
            root=row.root,
            board_count=row.board_count,
            sheet_count=row.sheet_count,
            has_git=row.has_git,
            registered_at=row.registered_at,
        )


class RegisterProjectBody(BaseModel):
    """Register an external KiCad project by its directory path (absolute). A bad or
    non-project dir raises ValueError in the store, mapped to 400 by the error layer."""

    root: str


class SetLibraryBody(BaseModel):
    """First-run onboarding: point the app at a library (M9b). `mode` is open / create /
    clone; `path` (open, or an explicit create/clone dir), `url` (clone source), and `dest`
    (clone destination) are used per mode. A bad mode or a bad path raises ValueError in the
    onboarding layer, mapped to 400 by the error layer, so a stray value never fabricates a
    library. `mode` is required; the rest default blank."""

    mode: str
    path: str = ""
    url: str = ""
    dest: str = ""


class SetSpecsBody(BaseModel):
    """Persist canonical spec data onto a record (M6i). `specs` maps a spec name to
    {value, source?, confidence?}; a typed body means a malformed container (a list or
    scalar instead of an object) is a clean 422, never an opaque 500 from set_specs
    calling .items() on a non-mapping. Inner values stay Any (the value is free-form)."""

    specs: dict[str, Any] = {}
    overwrite: bool = False


class NetClassDTO(BaseModel):
    """One net class the Editor submits (M7e). `name` is required and non-blank (a blank
    name is a clean 422, never a silent drop by the reconcile which keys on a truthy name);
    every other KiCad-10 dimension/color field is optional and passes through (extra=allow)
    so the reconcile can field-merge only the edited keys onto the on-disk class, preserving
    fields the UI never models."""

    model_config = ConfigDict(extra="allow")

    name: str

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a net class name must not be blank")
        return v


class SetNetClassesBody(BaseModel):
    """Edit a project's net classes (M7e). `classes` is the full edited set; `deleted`
    names classes to remove; `floor` selects the fab-house dimension floor the returned
    validation checks against (default no floor)."""

    classes: list[NetClassDTO]
    deleted: list[str] = []
    floor: str = "none"


class SetDesignRulesBody(BaseModel):
    """Edit a project's board design-rule constraints (M7e). `rules` field-merges into
    board.design_settings.rules (an omitted rule is preserved); the size lists, when
    provided, replace their board.design_settings arrays wholesale."""

    rules: dict[str, Any]
    track_widths: list[Any] | None = None
    via_dimensions: list[Any] | None = None
    diff_pair_dimensions: list[Any] | None = None


class NetclassPatternDTO(BaseModel):
    """One netclass-pattern assignment the Editor submits (roadmap #4): a net-name glob
    `pattern` bound to a `netclass`. Both are required and non-blank (a blank one is a clean
    422); the engine additionally checks the netclass exists among the project's classes. Only
    these two keys are modeled because they are the only ones KiCad 10 writes for a pattern row
    (verified against the real NETDECK .kicad_pro)."""

    pattern: str
    netclass: str

    @field_validator("pattern", "netclass")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a netclass pattern's pattern and net class must not be blank")
        return v


class SetNetclassPatternsBody(BaseModel):
    """Replace a project's netclass-pattern assignments (roadmap #4). `patterns` is the FULL
    edited list (the editor re-sends every row); an empty list clears every pattern."""

    patterns: list[NetclassPatternDTO]


class FieldEditDTO(BaseModel):
    """One field-cell edit the KiField bulk editor submits (M7h): set component `ref`'s `field`
    to `value`. `ref` and `field` are required and non-blank (a blank one is a clean 422); `value`
    is free text and may be empty (clearing the field). Editing the Reference field is refused by
    the engine (annotation owns designators, which also syncs the netlist path reference), a 400."""

    ref: str
    field: str
    value: str = ""

    @field_validator("ref", "field")
    @classmethod
    def _not_blank(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("a field edit's ref and field must not be blank")
        return v


class SetFieldsBody(BaseModel):
    """Apply a batch of field-cell edits to a project's schematic components (M7h), all as ONE
    atomic commit on the project's own git. `edits` is the full set of changed cells the editor
    submits; an empty list is a no-op."""

    edits: list[FieldEditDTO] = []


class SetSettingsBody(BaseModel):
    """Edit a project's board setup + overall thickness (its .kicad_pcb) and/or its .kicad_pro
    settings: ERC/DRC rule severities, the ERC pin-conflict matrix, project text variables
    (M7f-A + A2). Every field is optional so the editor can save any concern alone; whichever
    are given land in one atomic commit on the project's own git. The engine validates each and
    surfaces a bad value (unsupported key, non-positive thickness, unknown severity rule id,
    malformed pin map, blank text-var name) as a 400.

    `erc_severities`/`drc_severities` are {rule_id: level} maps merged per-rule (a sibling rule
    is preserved); `erc_pin_map` is the full 12x12 matrix; `text_variables` is the COMPLETE
    desired map (a key absent from it is deleted). text_variables uses None for 'not submitted'
    so an empty {} still means 'clear all vars'."""

    board_setup: dict[str, Any] | None = None
    thickness: float | None = None
    erc_severities: dict[str, Any] | None = None
    drc_severities: dict[str, Any] | None = None
    erc_pin_map: list[list[int]] | None = None
    text_variables: dict[str, Any] | None = None


class ConformTarget(BaseModel):
    """The target size/thickness (mm) for one object-conform category (M7f-B). Either may be None
    to leave that dimension untouched; the engine rejects a category that sets neither, and a
    non-positive or non-finite value, as a 400."""

    size: float | None = None
    thickness: float | None = None


class ConformBody(BaseModel):
    """Preview or apply an object conform (M7f-B): normalize the font size (and, where a font
    carries one, its thickness) of existing text objects to a house standard. `pcb_targets` keys
    are silk/fab/copper; `sch_targets` keys are text/labels; only the categories present are
    conformed. An empty selection is a 400."""

    pcb_targets: dict[str, ConformTarget] | None = None
    sch_targets: dict[str, ConformTarget] | None = None

    def pcb(self) -> dict:
        return {k: v.model_dump() for k, v in (self.pcb_targets or {}).items()}

    def sch(self) -> dict:
        return {k: v.model_dump() for k, v in (self.sch_targets or {}).items()}


class StackupBody(BaseModel):
    """Preview or apply a stackup change (M7f-C): EITHER apply a fab preset via `preset_key` (a
    whole-block generate that also sets board thickness), OR edit individual fields
    (`copper_finish`, `dielectric_constraints`, and per-layer `layer_edits` =
    {layer_name: {thickness?, material?, epsilon_r?, loss_tangent?}}). Exactly one mode per request;
    the engine rejects both / neither, an unknown or layer-count-mismatched preset, and a bad field
    value (blank finish, non-positive/non-finite number, a JSON bool where a number is expected) as
    a 400. `layer_edits` values are left loosely typed so a bool reaches the validator (which rejects
    it) instead of being silently coerced to a number."""

    preset_key: str | None = None
    copper_finish: str | None = None
    dielectric_constraints: bool | None = None
    layer_edits: dict[str, dict[str, Any]] | None = None


class ManualFillBody(BaseModel):
    """Manually link one placed component to a chosen shared-library part (M7f-D): the residual
    filler for a component Prepare / Complete-All could not match automatically. `ref` is the
    component's reference designator, `part_id` the library part id. Fills ALL of the part's identity
    fields (overwrite allowed, since this is an explicit user choice) and repoints the symbol lib_id, as
    one atomic commit. An unknown part or a missing ref is a 400."""

    ref: str
    part_id: str


class StmStatusDTO(BaseModel):
    """The STM index build/health probe (stm-viewer INTERFACES.md section 4). Never gated on
    409 - this IS the "is it built" check a 409-gated read endpoint routes the frontend to."""

    built: bool
    building: bool
    source_path: str
    source_present: bool
    all_families: bool
    device_xml_count: int
    family_count: int
    families: list[str] = []
    mcu_count: int
    classifier_rev: int
    af_schema_rev: int
    geometry_rev: int
    source_sha256: str
    built_at: str

    @classmethod
    def from_dict(cls, d: dict) -> "StmStatusDTO":
        return cls(
            built=bool(d.get("built", False)),
            building=bool(d.get("building", False)),
            source_path=d.get("source_path", "") or "",
            source_present=bool(d.get("source_present", False)),
            all_families=bool(d.get("all_families", False)),
            device_xml_count=int(d.get("device_xml_count", 0) or 0),
            family_count=int(d.get("family_count", 0) or 0),
            families=list(d.get("families", []) or []),
            mcu_count=int(d.get("mcu_count", 0) or 0),
            classifier_rev=int(d.get("classifier_rev", 0) or 0),
            af_schema_rev=int(d.get("af_schema_rev", 0) or 0),
            geometry_rev=int(d.get("geometry_rev", 0) or 0),
            source_sha256=d.get("source_sha256", "") or "",
            built_at=d.get("built_at", "") or "",
        )


class McuSpecRow(BaseModel):
    """One spec-matrix row (ST-MCU-FINDER-shaped columns), stm-viewer INTERFACES.md section 4.
    `part` (ref_name) is the addressable id used as the `?part=` query param; `mpn_example` is a
    display-only expanded real MPN (the exact-match MPN resolution lives in stm.authority.
    resolve_part, Phase 3 plan 03-02 - this is purely a readable example string for the table)."""

    part: str
    mpn_example: str
    series: str
    line: str
    core: str
    package: str
    pin_count: int
    io_count: int
    flash_kb: int | None = None
    ram_kb: int | None = None
    max_freq_mhz: int | None = None
    vdd_min: float | None = None
    vdd_max: float | None = None
    temp_min_c: int | None = None
    temp_max_c: int | None = None
    peripherals: dict[str, int] = {}

    @classmethod
    def from_dict(cls, d: dict) -> "McuSpecRow":
        return cls(
            part=d["part"],
            mpn_example=d.get("mpn_example", "") or "",
            series=d.get("series", "") or "",
            line=d.get("line", "") or "",
            core=d.get("core", "") or "",
            package=d.get("package", "") or "",
            pin_count=int(d.get("pin_count", 0) or 0),
            io_count=int(d.get("io_count", 0) or 0),
            flash_kb=d.get("flash_kb"),
            ram_kb=d.get("ram_kb"),
            max_freq_mhz=d.get("max_freq_mhz"),
            vdd_min=d.get("vdd_min"),
            vdd_max=d.get("vdd_max"),
            temp_min_c=d.get("temp_min_c"),
            temp_max_c=d.get("temp_max_c"),
            peripherals=dict(d.get("peripherals", {}) or {}),
        )
