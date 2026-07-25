"""Durable placement bindings (punch 17): which library part a PLACED component is bound to,
carried by the placement itself where the EDA tool allows it and by the project record where it
does not, read through one generic path that has no per-tool branch.

The property under test throughout: a binding survives the things that break a ref-keyed map,
namely a re-annotate (the reference changes) and a Value edit.
"""

from __future__ import annotations

from stockroom.model.project import ProjectRecord
from stockroom.projects import binding


def _kicad_comp(**over):
    comp = {"ref": "R1", "uuid": "01e92f3b-cbf5-4d8d-bdf6-bdf8dd46460f", "lib_id": "Device:R",
            "props": {"Reference": "R1", "Value": "10k"}}
    comp.update(over)
    return comp


# -- the placement key ---------------------------------------------------------


def test_the_placement_key_is_the_tools_own_stable_id_not_the_reference():
    """A reference is renumbered by annotation; the KiCad symbol uuid is not. Verified against a
    real KiCad V10 sheet: every placed (symbol ...) carries a (uuid ...) that annotation leaves
    alone."""
    comp = _kicad_comp()
    before = binding.placement_key(comp)
    comp["ref"] = "R47"
    comp["props"]["Reference"] = "R47"
    comp["props"]["Value"] = "47k"
    assert binding.placement_key(comp) == before
    assert before == "01e92f3b-cbf5-4d8d-bdf6-bdf8dd46460f"


def test_a_placement_with_no_stable_id_falls_back_to_a_SELF_DESCRIBING_weak_key():
    """A file (or an EDA tool) that supplies no per-placement id must not silently produce a key
    that LOOKS as strong as a uuid. The weak key says so in its own text."""
    key = binding.placement_key({"ref": "R1", "props": {}})
    assert key == "ref:R1"
    assert binding.is_weak_key(key) is True
    assert binding.is_weak_key("01e92f3b-cbf5-4d8d-bdf6-bdf8dd46460f") is False


def test_a_placement_with_neither_an_id_nor_a_reference_has_no_key():
    assert binding.placement_key({"ref": "", "props": {}}) == ""


# -- resolving a binding: tool-native field first, project record second --------


def test_a_kicad_placement_carries_its_own_binding_in_the_schematic():
    comps = [_kicad_comp(props={"Reference": "R1", "Value": "10k",
                                binding.field_for("kicad"): "r10k"})]
    binding.resolve(comps, "kicad")
    assert binding.bound_part_id(comps[0]) == "r10k"


def test_an_altium_placement_binding_comes_from_the_project_record():
    """Stockroom never writes Altium binary, so the record is the ONLY home an Altium binding
    can have. Same read path, no branch."""
    comps = [{"ref": "R1", "uuid": "UID-1", "lib_id": "altium:RES", "props": {"Reference": "R1"}}]
    rec = ProjectRecord(id="p", name="P", root="/tmp/p", eda="altium",
                        bindings={"altium": {"UID-1": "r10k"}})
    binding.resolve(comps, "altium", stored=binding.stored_for(rec, "altium"))
    assert binding.bound_part_id(comps[0]) == "r10k"


def test_a_natively_placed_altium_component_carries_the_dblib_column_with_no_record_entry():
    """A component placed from Stockroom's DbLib carries the Stockroom id as a parameter that
    ALTIUM wrote, so it is bound without Stockroom ever having recorded anything."""
    comps = [{"ref": "U1", "uuid": "UID-9", "lib_id": "altium:STM32",
              "props": {"Reference": "U1", binding.field_for("altium"): "stm32f405"}}]
    binding.resolve(comps, "altium", stored={})
    assert binding.bound_part_id(comps[0]) == "stm32f405"


def test_the_placements_own_field_wins_over_a_stale_record_entry():
    """The design file is the truth. A record entry that disagrees is stale by definition, and
    picking the record would silently overrule what the user's schematic actually says."""
    comps = [_kicad_comp(props={"Reference": "R1", binding.field_for("kicad"): "r10k"})]
    binding.resolve(comps, "kicad", stored={"01e92f3b-cbf5-4d8d-bdf6-bdf8dd46460f": "r47k"})
    assert binding.bound_part_id(comps[0]) == "r10k"


def test_an_unbound_placement_stays_honestly_unbound():
    comps = [_kicad_comp()]
    binding.resolve(comps, "kicad", stored={})
    assert binding.bound_part_id(comps[0]) == ""


def test_resolve_stamps_the_placement_key_so_later_stages_keep_it():
    """The BOM carries components as (ref, lib_id, props) triples, which drop the uuid. The key
    therefore has to ride inside props or the binding cannot be looked up downstream."""
    comps = [_kicad_comp()]
    binding.resolve(comps, "kicad", stored={})
    assert comps[0]["props"][binding.PLACEMENT_KEY] == "01e92f3b-cbf5-4d8d-bdf6-bdf8dd46460f"


def test_resolve_reads_the_key_back_out_of_props_when_the_comp_has_no_uuid():
    """Downstream stages hand on props alone; a second resolve over those must find the same
    binding rather than degrade to a weak ref key."""
    comps = [_kicad_comp()]
    binding.resolve(comps, "kicad", stored={"01e92f3b-cbf5-4d8d-bdf6-bdf8dd46460f": "r10k"})
    downstream = [{"ref": "R99", "props": comps[0]["props"]}]  # renumbered, uuid gone
    binding.resolve(downstream, "kicad", stored={"01e92f3b-cbf5-4d8d-bdf6-bdf8dd46460f": "r10k"})
    assert binding.bound_part_id(downstream[0]) == "r10k"


# -- where a binding is WRITTEN is registry data, not a branch ------------------


def test_the_registry_decides_whether_a_binding_is_written_into_the_design():
    assert binding.writes_into_design("kicad") is True
    assert binding.writes_into_design("altium") is False


def test_stored_bindings_are_read_and_merged_per_tool():
    rec = ProjectRecord(id="p", name="P", root="/tmp/p",
                        bindings={"kicad": {"u1": "r10k"}, "altium": {"UID": "c100n"}})
    assert binding.stored_for(rec, "altium") == {"UID": "c100n"}
    assert binding.stored_for(rec, "eagle") == {}
    merged = binding.merged_bindings(rec, "altium", {"UID2": "r47k"})
    assert merged == {"kicad": {"u1": "r10k"}, "altium": {"UID": "c100n", "UID2": "r47k"}}
    # never mutates the record in place; the caller decides when to persist
    assert rec.bindings["altium"] == {"UID": "c100n"}


def test_merging_an_empty_part_id_UNBINDS_rather_than_storing_a_blank():
    rec = ProjectRecord(id="p", name="P", root="/tmp/p", bindings={"altium": {"UID": "c100n"}})
    assert binding.merged_bindings(rec, "altium", {"UID": ""}) == {"altium": {}}
