"""The record data each EDA tool consumes is REGISTRY DATA, and it is the single source of truth.

Why this exists: the detail sheet has to answer "what does an EDA tool actually receive from this
part", and that question had three separate answers in the codebase - `altium/dblib.FIELD_MAP`,
`altium/datasource.ALTIUM_COLUMNS` and `projects/fill.COMPLETION_FIELDS` - none of which knew about
the others. A fourth hand-typed copy in the frontend would have made the surface lie the first time
a column changed. So the registry owns the list and the adapters derive from it.

The gates below are the load-bearing half: they assert the DERIVED artifacts still contain exactly
what they contained before this refactor, so "generic now" cannot quietly mean "different".
"""
from __future__ import annotations

from stockroom.eda.registry import all_tools, data_field_union, get_tool


def test_kicad_declares_the_fields_a_schematic_fill_writes():
    """KiCad's handoff is the five properties `proposed_changes` stamps onto a component."""
    kicad = get_tool("kicad")
    assert [f.key for f in kicad.data_fields] == [
        "mpn", "manufacturer", "datasheet", "description", "footprint", "symbol"
    ]
    # The tool's own name for the field is what lands in the .kicad_sch, so it must be exact.
    assert [f.tool_field for f in kicad.data_fields] == [
        "MPN", "Manufacturer", "Datasheet", "Description", "Footprint", "lib_id"
    ]
    # The symbol is structural (a placed component always has a lib_id), so it is declared for the
    # handoff band but must never be counted as a fillable gap.
    assert [f.key for f in kicad.data_fields if not f.passport] == ["symbol"]


def test_altium_declares_more_than_kicad_and_says_so_per_field():
    """Altium's DbLib carries commercial columns KiCad has no property for. That asymmetry is the
    whole reason this is per-tool data rather than one global list."""
    altium = get_tool("altium")
    keys = {f.key for f in altium.data_fields}
    assert {"supplier", "price", "stock", "lifecycle", "category", "value"} <= keys
    # ... and KiCad genuinely does not carry them, or the union below would be meaningless.
    assert not ({"price", "stock", "lifecycle"} & {f.key for f in get_tool("kicad").data_fields})


def test_every_declared_field_is_well_formed():
    """A blank key or label would render an unlabelled cell in the handoff band."""
    for tool in all_tools():
        assert tool.data_fields, f"{tool.key} declares no data fields"
        for f in tool.data_fields:
            assert f.key and f.key == f.key.lower().strip(), f"{tool.key}: bad key {f.key!r}"
            assert f.label.strip(), f"{tool.key}: {f.key} has no label"
            assert f.tool_field.strip(), f"{tool.key}: {f.key} has no tool field name"
        # A key declared twice for ONE tool would emit a duplicate column.
        keys = [f.key for f in tool.data_fields]
        assert len(keys) == len(set(keys)), f"{tool.key} declares a duplicate field key"


def test_union_reports_which_tools_consume_each_field():
    """What the surface renders: one row per field, naming every tool that receives it. Ordered by
    registry declaration, so presentation order is a registry decision and not a sort."""
    union = data_field_union()
    by_key = {f.key: f for f in union}

    # A field both tools take names both, in registry order (KiCad leads; see `_REGISTRY`).
    assert by_key["mpn"].tools == ("kicad", "altium")
    # A field only one tool takes names only that tool - this is what stops the band claiming a
    # value reaches KiCad when no KiCad property exists for it.
    assert by_key["price"].tools == ("altium",)
    assert by_key["stock"].tools == ("altium",)
    assert by_key["footprint"].tools == ("kicad", "altium")
    # The symbol reaches BOTH tools, by different mechanisms. Asserted because the alternative -
    # declaring it for Altium alone - made the handoff band tell a person their symbol was not
    # going to KiCad, which is the exact class of surface lie this whole registry exists to stop.
    assert by_key["symbol"].tools == ("kicad", "altium")

    # The union is deduplicated and KiCad's fields lead, because KiCad is the first registered tool.
    assert len(union) == len({f.key for f in union})
    assert [f.key for f in union][:5] == [
        "mpn", "manufacturer", "datasheet", "description", "footprint"
    ]


def test_union_says_who_owns_each_field():
    """The handoff band renders the CURATED fields only, so this is what decides the surface.

    A price is refreshed from a distributor and is the Sourcing column's subject; a `value` is
    computed at emit time from other fields and is stored nowhere, so a cell for it could only be
    filled by re-implementing `derive_value` in the frontend. Both are excluded, for different
    reasons, and the reason is the data."""
    from stockroom.eda.registry import FIELD_ORIGINS

    by_key = {f.key: f for f in data_field_union()}
    assert [k for k, f in by_key.items() if f.origin == "curated"] == [
        "mpn", "manufacturer", "datasheet", "description", "footprint", "symbol", "category",
    ]
    assert {k for k, f in by_key.items() if f.origin == "vendor"} == {
        "supplier", "supplier_part_number", "supplier_url", "price", "stock", "lifecycle",
    }
    assert [k for k, f in by_key.items() if f.origin == "derived"] == ["value"]
    # Every declared origin must name a real field, or the map is silently stale.
    assert set(FIELD_ORIGINS) <= set(by_key)
    # Only the three known origins exist: a typo would default a field to "curated" and put a
    # vendor-owned value into the band claiming a person maintains it.
    assert {f.origin for f in by_key.values()} <= {"curated", "vendor", "derived"}


def test_union_label_is_stable_across_tools_that_share_a_field():
    """Two tools naming the same record field differently must not produce two rows, and the label
    shown to a person is the FIRST registered one rather than whichever tool won a race."""
    union = data_field_union()
    by_key = {f.key: f for f in union}
    assert by_key["description"].label == "Description"
    assert by_key["mpn"].label == "MPN"


def test_altium_dblib_wire_format_is_unchanged_by_this_refactor():
    """The .DbLib column layout is a WIRE FORMAT and stays owned by the adapter (see the FINDING in
    the ledger): it carries paired columns a record-field list cannot express - an asset ref splits
    into Ref + Path, a datasheet into a link Description + URL - plus reserved bracket syntax and
    the placement binding. Forcing that shape onto the UI's record-field list would have made both
    worse. What ties them is the agreement gate below, not a derivation.

    This test's job is to pin the emitted format so "the registry now owns the data question" can
    never quietly mean "the DbLib columns changed"."""
    from stockroom.altium.dblib import FIELD_MAP

    assert [c for c, _p, _v in FIELD_MAP] == [
        "MPN", "Library Ref", "Library Path", "Footprint Ref", "Footprint Path",
        "Value", "Manufacturer", "Description", "Comment",
        "ComponentLink1Description", "ComponentLink1URL",
        "Supplier", "SupplierPartNumber", "SupplierURL",
        "Price", "Stock", "Lifecycle", "Category",
        "Stockroom ID",
    ]
    # The Altium Design Parameter names carry reserved bracket syntax; losing a bracket silently
    # turns a model binding into an ordinary parameter, so they are asserted verbatim too.
    assert [p for _c, p, _v in FIELD_MAP] == [
        "MPN", "[Library Ref]", "[Library Path]", "[Footprint Ref]", "[Footprint Path]",
        "Value", "Manufacturer", "[Description]", "[Comment]",
        "ComponentLink1Description", "ComponentLink1URL",
        "Supplier", "SupplierPartNumber", "SupplierURL",
        "Price", "Stock", "Lifecycle", "Category",
        "Stockroom ID",
    ]
    assert [v for _c, _p, v in FIELD_MAP] == [
        True, False, False, False, False,
        True, True, True, True,
        False, False,
        False, False, False,
        False, False, False, False,
        False,
    ]


def test_altium_datasource_columns_match_the_dblib_exactly():
    """These two have to agree or the DbLib queries a column the SQLite table does not have. They
    were two hand-typed lists; now one derives from the other."""
    from stockroom.altium.datasource import ALTIUM_COLUMNS
    from stockroom.altium.dblib import FIELD_MAP

    assert ALTIUM_COLUMNS == [c for c, _p, _v in FIELD_MAP]


def test_every_altium_data_field_really_reaches_a_dblib_column():
    """THE AGREEMENT GATE, direction 1: a field the registry claims Altium receives must actually be
    carried by a column. Without this the handoff band could promise a value reaches Altium while
    the emitted DbLib has nowhere to put it - a surface telling a confident lie."""
    from stockroom.altium.dblib import FIELD_MAP

    params = {p for _c, p, _v in FIELD_MAP}
    for f in get_tool("altium").data_fields:
        assert f.tool_field in params, (
            f"registry says Altium receives {f.key!r} as {f.tool_field!r}, but no .DbLib column "
            f"declares that Design Parameter"
        )


def test_every_dblib_column_is_either_a_registry_field_or_declared_plumbing():
    """THE AGREEMENT GATE, direction 2, and the one that catches the real drift: a column added to
    the wire format must be either a declared data field or explicitly named as plumbing. Otherwise
    a new column is invisible to the handoff band forever, which is precisely how
    country_of_origin + tariff_rate were dropped at two layers before Batch 3."""
    from stockroom.altium.dblib import FIELD_MAP, NON_FIELD_COLUMNS

    declared = {f.tool_field for f in get_tool("altium").data_fields}
    for col, param, _v in FIELD_MAP:
        assert param in declared or col in NON_FIELD_COLUMNS, (
            f".DbLib column {col!r} is neither a registry data field nor listed in "
            f"NON_FIELD_COLUMNS. Add it to the Altium tool's data_fields so the handoff band "
            f"shows it, or name it as plumbing with a reason."
        )


def test_plumbing_columns_are_real_columns():
    """A stale NON_FIELD_COLUMNS entry would silently widen the exemption above, so the escape
    hatch is itself checked: every named plumbing column must still exist in the wire format."""
    from stockroom.altium.dblib import FIELD_MAP, NON_FIELD_COLUMNS

    cols = {c for c, _p, _v in FIELD_MAP}
    assert set(NON_FIELD_COLUMNS) <= cols, (
        f"NON_FIELD_COLUMNS names columns the .DbLib no longer has: "
        f"{sorted(set(NON_FIELD_COLUMNS) - cols)}"
    )


def test_kicad_completion_fields_come_from_the_registry():
    """`component_completion` measures a placed component against KiCad's handoff, so its field list
    is BUILT from the registry's KiCad declaration and cannot drift from what the fill writes.

    The values are pinned too: this refactor must not change which fields a project audit counts."""
    from stockroom.projects.fill import COMPLETION_FIELDS

    assert COMPLETION_FIELDS == (
        ("Footprint", "Footprint"),
        ("MPN", "MPN"),
        ("Manufacturer", "Manufacturer"),
        ("Datasheet", "Datasheet"),
        ("Description", "Description"),
    )
    # ... and they really are the registry's KiCad fields, not a coincidentally equal literal.
    # The passport measures only what a component can actually be missing, so `lib_id` is
    # deliberately absent: it is declared for the handoff band, not for counting gaps.
    assert {k for k, _l in COMPLETION_FIELDS} == {
        f.tool_field for f in get_tool("kicad").data_fields if f.passport
    }
