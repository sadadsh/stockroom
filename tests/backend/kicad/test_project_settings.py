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
