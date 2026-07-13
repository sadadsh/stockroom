from stockroom.verify.record_diff import extract_symbol_node, field_diff


def _changes(before, after, **kw):
    return {c.key: (c.status, c.before, c.after) for c in field_diff(before, after, **kw)}


def test_added_removed_and_changed_scalars():
    before = {"mpn": "", "manufacturer": "TI", "category": "ICs"}
    after = {"mpn": "TPS62130", "manufacturer": "", "category": "Regulators"}
    c = _changes(before, after)
    assert c["mpn"] == ("added", "", "TPS62130")
    assert c["manufacturer"] == ("removed", "TI", "")
    assert c["category"] == ("changed", "ICs", "Regulators")


def test_identical_records_have_no_changes():
    rec = {"mpn": "X", "datasheet": {"file": "x.pdf"}, "tags": ["a"]}
    assert field_diff(rec, dict(rec)) == []


def test_nested_dict_none_to_object_flattens_to_leaf_paths():
    # datasheet goes from null to a real object: the meaningful leaf is datasheet.file,
    # not a coarse "datasheet" replaced-whole-object churn.
    before = {"datasheet": None}
    after = {"datasheet": {"file": "tps.pdf", "source_url": "", "fetched_at": ""}}
    c = _changes(before, after)
    # datasheet was null, so the .file leaf did not exist before (None, not "")
    assert c["datasheet.file"] == ("added", None, "tps.pdf")
    # empty-to-empty sub-fields (None -> "") are not reported as changes
    assert "datasheet.source_url" not in c


def test_list_valued_field_is_a_single_leaf():
    before = {"purchase": []}
    after = {"purchase": [{"vendor": "LCSC", "url": "https://x/p"}]}
    c = _changes(before, after)
    assert c["purchase"][0] == "added"
    assert c["purchase"][2] == [{"vendor": "LCSC", "url": "https://x/p"}]
    assert "purchase[0].url" not in c  # lists are one leaf, not index-exploded


def test_before_none_treats_the_whole_record_as_added():
    after = {"mpn": "X", "category": "ICs"}
    c = _changes(None, after)
    assert c["mpn"] == ("added", None, "X")
    assert c["category"] == ("added", None, "ICs")


def test_after_none_treats_the_whole_record_as_removed():
    before = {"mpn": "X"}
    c = _changes(before, None)
    assert c["mpn"] == ("removed", "X", None)


def test_exclude_drops_internal_keys():
    before = {"mpn": "X", "hashes": {"symbol_content": "aaa"}, "id": "p"}
    after = {"mpn": "Y", "hashes": {"symbol_content": "bbb"}, "id": "p"}
    c = _changes(before, after, exclude={"id", "hashes"})
    assert set(c) == {"mpn"}


def test_specs_pinout_reads_as_one_added_field():
    before = {"specs": {}}
    after = {"specs": {"pinout": [{"pin": "1", "name": "A"}, {"pin": "2", "name": "B"}]}}
    c = _changes(before, after)
    assert c["specs.pinout"][0] == "added"
    assert len(c["specs.pinout"][2]) == 2


# --- extract_symbol_node ---------------------------------------------------

_LIB = (
    "(kicad_symbol_lib\n"
    '\t(symbol "TPS62130"\n'
    '\t\t(property "Reference" "U" (at 0 0 0))\n'
    '\t\t(symbol "TPS62130_1_1"\n'
    "\t\t\t(pin power_in line (at 0 0 0))\n"
    "\t\t)\n"
    "\t)\n"
    '\t(symbol "MYSTERY"\n'
    '\t\t(property "Reference" "U" (at 0 0 0))\n'
    "\t)\n"
    ")\n"
)


def test_extract_symbol_node_returns_the_named_block_including_subunits():
    node = extract_symbol_node(_LIB, "TPS62130")
    assert node is not None
    assert node.startswith('(symbol "TPS62130"')
    assert "TPS62130_1_1" in node  # the nested sub-unit is inside the block
    assert "MYSTERY" not in node  # the sibling symbol is not


def test_extract_symbol_node_does_not_match_a_subunit_name_as_top_level():
    # asking for the exact top-level name only; a suffix sub-unit is not a top symbol
    assert extract_symbol_node(_LIB, "TPS62130_1_1") is None


def test_extract_symbol_node_absent_returns_none():
    assert extract_symbol_node(_LIB, "NOTHERE") is None


def test_extract_symbol_node_balances_parens_inside_quoted_strings():
    lib = (
        "(kicad_symbol_lib\n"
        '\t(symbol "PART"\n'
        '\t\t(property "Description" "a (weird) ) value" (at 0 0 0))\n'
        "\t)\n"
        '\t(symbol "OTHER" )\n'
        ")\n"
    )
    node = extract_symbol_node(lib, "PART")
    assert node is not None
    assert "a (weird) ) value" in node
    assert "OTHER" not in node
