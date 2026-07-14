"""M7e-1: the targeted .kicad_pro JSON editor.

A .kicad_pro is JSON that KiCad serializes with nlohmann::json: 2-space indent,
alphabetically-sorted keys, a trailing newline (verified byte-for-byte against a
real KiCad 10 project, version 20260206). This editor loads a project file,
partial-merges only the named keys (a KinJector-style deep merge so editing net
classes never rewrites the design-rules block), and re-serializes in KiCad's
exact format so an unchanged key stays byte-identical. The Transaction owns the
git-atomic commit; this module owns the minimal-diff byte edit.
"""

from __future__ import annotations

import json

from stockroom.kicad import project_settings as ps

# A canonical .kicad_pro fragment in KiCad's exact serialization (2-space indent,
# sorted keys, trailing newline). Round-tripping this proves the serializer
# reproduces KiCad's format, so a real project file edits to a minimal diff.
CANONICAL = (
    "{\n"
    '  "board": {\n'
    '    "design_settings": {\n'
    '      "rules": {\n'
    '        "min_clearance": 0.2,\n'
    '        "min_track_width": 0.2,\n'
    '        "use_height_for_length_calcs": true\n'
    "      },\n"
    '      "track_widths": []\n'
    "    }\n"
    "  },\n"
    '  "meta": {\n'
    '    "filename": "board.kicad_pro",\n'
    '    "version": 3\n'
    "  },\n"
    '  "net_settings": {\n'
    '    "classes": [\n'
    "      {\n"
    '        "clearance": 0.2,\n'
    '        "name": "Default",\n'
    '        "track_width": 0.2\n'
    "      }\n"
    "    ],\n"
    '    "meta": {\n'
    '      "version": 5\n'
    "    }\n"
    "  }\n"
    "}\n"
)


def test_serialize_reproduces_kicad_format_byte_for_byte():
    # parse then re-serialize the canonical text -> byte-identical (the serializer
    # matches KiCad's nlohmann::json dump exactly, so untouched files never churn).
    assert ps.serialize(ps.parse(CANONICAL)) == CANONICAL


def test_serialize_orders_an_insertion_ordered_dict_like_kicad():
    # KiCad stores objects in a sorted map, but a dict Stockroom BUILDS (a reconciled net
    # class, a new class from defaults) is in insertion order. The serializer must reorder
    # its keys to KiCad's alphabetical order, else a new class's block lands unsorted and
    # KiCad re-sorts it on the next save, breaking the minimal diff. A round-trip of already
    # sorted text cannot catch this, so feed a deliberately UNSORTED dict.
    out = ps.serialize({"name": "PWR", "via_drill": 0.3, "clearance": 0.2, "bus_width": 12})
    keys = [ln.split('"')[1] for ln in out.splitlines() if ln.startswith('  "')]
    assert keys == ["bus_width", "clearance", "name", "via_drill"]  # alphabetical, not insertion


def test_apply_empty_patch_is_byte_identical():
    # a no-op edit must leave the file byte-for-byte unchanged (zero-diff invariant).
    assert ps.apply_patch_text(CANONICAL, {}) == CANONICAL


def test_partial_merge_edits_only_the_named_leaf():
    # editing a single design-rule leaf changes ONLY that value; every other byte
    # (net_settings, meta, the sibling rule) is untouched.
    out = ps.apply_patch_text(
        CANONICAL, {"board": {"design_settings": {"rules": {"min_track_width": 0.15}}}}
    )
    assert '"min_track_width": 0.15' in out
    assert '"min_clearance": 0.2' in out  # sibling rule preserved
    assert '"use_height_for_length_calcs": true' in out
    # the whole net_settings block is byte-identical to the original slice
    assert CANONICAL[CANONICAL.index('"net_settings"'):] == out[out.index('"net_settings"'):]
    # and it is still valid JSON that round-trips through the serializer
    assert ps.serialize(ps.parse(out)) == out


def test_editing_net_classes_leaves_design_settings_byte_identical():
    # the KinJector partial-merge value: a net-class edit must not rewrite the
    # design-rules block at all.
    before_ds = CANONICAL[CANONICAL.index('"board"'):CANONICAL.index('"meta"')]
    out = ps.apply_patch_text(
        CANONICAL,
        {"net_settings": {"classes": [{"name": "Default", "clearance": 0.15, "track_width": 0.15}]}},
    )
    assert before_ds == out[out.index('"board"'):out.index('"meta"')]
    assert '"clearance": 0.15' in out


def test_merge_replaces_a_list_wholesale():
    # lists are replaced, not concatenated (the reconciled class list is computed
    # upstream, then handed to merge as the full new value).
    base = {"net_settings": {"classes": [{"name": "A"}, {"name": "B"}]}}
    merged = ps.merge(base, {"net_settings": {"classes": [{"name": "C"}]}})
    assert merged["net_settings"]["classes"] == [{"name": "C"}]


def test_merge_recurses_into_nested_dicts_preserving_siblings():
    base = {"board": {"design_settings": {"rules": {"a": 1, "b": 2}, "defaults": {"x": 9}}}}
    merged = ps.merge(base, {"board": {"design_settings": {"rules": {"b": 3}}}})
    assert merged["board"]["design_settings"]["rules"] == {"a": 1, "b": 3}
    assert merged["board"]["design_settings"]["defaults"] == {"x": 9}  # untouched sibling


def test_merge_does_not_mutate_the_base_argument():
    base = {"board": {"rules": {"a": 1}}}
    ps.merge(base, {"board": {"rules": {"a": 2}}})
    assert base["board"]["rules"]["a"] == 1  # caller's dict is not clobbered


def test_merge_result_does_not_alias_an_untouched_nested_container_of_base():
    # a nested container on a key the patch does NOT touch must be a copy, not aliased:
    # mutating it through the returned dict must not reach back into base.
    base = {"net_settings": {"classes": [{"name": "Default"}]}, "other": {"x": 1}}
    merged = ps.merge(base, {"net_settings": {"meta": {"version": 5}}})
    merged["net_settings"]["classes"].append({"name": "PWR"})  # mutate a preserved list
    merged["other"]["x"] = 99  # mutate a preserved dict
    assert base["net_settings"]["classes"] == [{"name": "Default"}]  # base untouched
    assert base["other"]["x"] == 1


def test_merge_result_does_not_alias_the_patch_container():
    # a container coming from the patch must also be copied, so mutating the result does
    # not reach back into the caller's patch dict.
    patch = {"net_settings": {"classes": [{"name": "PWR"}]}}
    merged = ps.merge({}, patch)
    merged["net_settings"]["classes"].append({"name": "X"})
    assert patch["net_settings"]["classes"] == [{"name": "PWR"}]


def test_merge_type_change_dict_to_scalar_patch_wins():
    base = {"k": {"nested": 1}}
    merged = ps.merge(base, {"k": 5})
    assert merged["k"] == 5


def test_apply_patch_writes_the_file(tmp_path):
    p = tmp_path / "board.kicad_pro"
    p.write_text(CANONICAL, encoding="utf-8")
    ps.apply_patch(p, {"board": {"design_settings": {"rules": {"min_track_width": 0.15}}}})
    text = p.read_text(encoding="utf-8")
    assert '"min_track_width": 0.15' in text
    assert json.loads(text)["board"]["design_settings"]["rules"]["min_clearance"] == 0.2


# A canonical .kicad_pro fragment WITH a top-level text_variables map (KiCad's real
# home for project text variables), used to prove the wholesale-replace path a
# deletion needs (the deep-merge alone can only add/update, never remove a key).
CANONICAL_TV = (
    "{\n"
    '  "meta": {\n'
    '    "version": 3\n'
    "  },\n"
    '  "text_variables": {\n'
    '    "KEEP": "one",\n'
    '    "REMOVE": "two"\n'
    "  }\n"
    "}\n"
)


def test_merge_alone_cannot_delete_a_text_variable():
    # This is WHY replace_keys exists: a plain partial-merge of the desired map keeps a
    # key the caller wanted removed (merge only adds/updates), so a UI "Remove" would not
    # actually drop the var from the file.
    out = ps.apply_patch_text(CANONICAL_TV, {"text_variables": {"KEEP": "one"}})
    assert '"REMOVE": "two"' in out  # merge could not delete it


def test_replace_keys_replaces_a_top_level_key_wholesale():
    # With the key named in replace_keys, the desired map REPLACES the on-disk one wholesale,
    # so a var absent from the desired map (REMOVE) is deleted while KEEP survives.
    out = ps.apply_patch_text(
        CANONICAL_TV, {"text_variables": {"KEEP": "one"}}, replace_keys=("text_variables",)
    )
    assert json.loads(out)["text_variables"] == {"KEEP": "one"}
    assert "REMOVE" not in out


def test_replace_keys_can_clear_a_map_to_empty():
    # deleting every var yields an empty desired map, which must write text_variables: {}
    # (matching KiCad, which keeps the empty key), not leave the old vars behind.
    out = ps.apply_patch_text(
        CANONICAL_TV, {"text_variables": {}}, replace_keys=("text_variables",)
    )
    assert json.loads(out)["text_variables"] == {}


def test_replace_keys_updates_a_value_as_a_minimal_diff():
    # changing one var's value (no deletions) is still a minimal diff: only that line differs.
    out = ps.apply_patch_text(
        CANONICAL_TV,
        {"text_variables": {"KEEP": "one", "REMOVE": "changed"}},
        replace_keys=("text_variables",),
    )
    assert out == CANONICAL_TV.replace('"two"', '"changed"')


def test_replace_keys_wholesale_identical_map_is_byte_identical():
    # replacing with the SAME content KiCad wrote must churn nothing (zero-diff invariant),
    # because the serializer sorts keys exactly as KiCad does.
    out = ps.apply_patch_text(
        CANONICAL_TV,
        {"text_variables": {"KEEP": "one", "REMOVE": "two"}},
        replace_keys=("text_variables",),
    )
    assert out == CANONICAL_TV


def test_replace_keys_ignores_a_key_absent_from_the_patch():
    # a replace_key the patch does not carry is simply not replaced (no KeyError), so callers
    # can pass a fixed replace_keys tuple without guarding every key's presence.
    out = ps.apply_patch_text(CANONICAL_TV, {"meta": {"version": 4}}, replace_keys=("text_variables",))
    assert json.loads(out)["text_variables"] == {"KEEP": "one", "REMOVE": "two"}
    assert '"version": 4' in out


def test_apply_patch_threads_replace_keys_to_the_file(tmp_path):
    p = tmp_path / "board.kicad_pro"
    p.write_text(CANONICAL_TV, encoding="utf-8")
    ps.apply_patch(p, {"text_variables": {"KEEP": "one"}}, replace_keys=("text_variables",))
    assert json.loads(p.read_text(encoding="utf-8"))["text_variables"] == {"KEEP": "one"}
