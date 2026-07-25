"""The EDA tool registry: the one place a tool's facts live.

Owner directive 2026-07-24: no major system may be specific to one EDA tool. These tests
lock the properties that make that true -- above all, that adding a third tool is ADDING A
REGISTRY ENTRY and not editing call sites.
"""
import pytest

from stockroom.eda.registry import (
    EdaTool,
    PlacementBinding,
    all_tools,
    get_tool,
    workspace_gitattributes,
    workspace_gitignore,
)


def test_the_registry_knows_the_shipped_tools():
    keys = {t.key for t in all_tools()}
    assert {"kicad", "altium"} <= keys
    for tool in all_tools():
        assert tool.label, f"{tool.key} has no display label"


def test_an_unknown_tool_is_a_clear_error_not_a_silent_default():
    """A typo must never resolve to KiCad by accident -- that class of silent fallback is
    what produced the attach-clobber bug."""
    with pytest.raises(KeyError, match="eagle"):
        get_tool("eagle")


def test_kicad_ignores_the_per_user_files_that_break_peer_sync():
    """The measured cause of the owner's peer-sync errors: .kicad_prl is per-user project
    state and fp-info-cache is a regenerated machine cache. KiCad's own docs say not to
    commit them; committed, two peers conflict on every pull while the real design files
    merge fine."""
    lines = [ln.strip() for ln in workspace_gitignore(["kicad"]).splitlines()]
    for pattern in ("*.kicad_prl", "fp-info-cache", "*.lck", "*-backups/"):
        assert pattern in lines, f"{pattern} is not ignored"
    # The actual design sources must NEVER be ignored. Compare LINE-EXACT: a substring
    # check would false-positive on the backup patterns (`*.kicad_sch-bak` contains
    # `*.kicad_sch`) and report a bug that is not there.
    for never in ("*.kicad_sch", "*.kicad_pcb", "*.kicad_pro", "*.kicad_mod"):
        assert never not in lines


def test_altium_binaries_are_marked_binary_and_unmergeable_but_its_text_formats_are_not():
    attrs = workspace_gitattributes(["altium"])
    assert "*.PcbLib binary" in attrs
    assert "*.SchLib binary" in attrs
    # .DbLib is generated INI text -- marking it binary would destroy its diffability.
    assert "*.DbLib binary" not in attrs


def test_hygiene_composes_across_tools_without_duplication():
    both = workspace_gitignore(["kicad", "altium"])
    assert "*.kicad_prl" in both  # kicad's rules present
    assert both.count("*.kicad_prl") == 1  # and not duplicated
    # Order must be deterministic so the generated file does not churn between runs.
    assert workspace_gitignore(["altium", "kicad"]) == both


def test_adding_a_third_tool_requires_no_change_to_the_generic_code():
    """The whole point of the registry. A new tool is DATA; the hygiene generator that
    consumes it is untouched."""
    eagle = EdaTool(
        key="eagle",
        label="EAGLE",
        ignore=("*.b#*", "*.s#*"),
        binary=("*.lbr",),
        text=("*.epf",),
    )
    ignore = workspace_gitignore(["kicad"], extra_tools=[eagle])
    attrs = workspace_gitattributes(["kicad"], extra_tools=[eagle])
    assert "*.b#*" in ignore
    assert "*.lbr binary" in attrs
    assert "*.epf text" in attrs


def test_generated_files_are_self_identifying():
    """A human opening the file must know it is generated and must not hand-edit it."""
    for text in (workspace_gitignore(["kicad"]), workspace_gitattributes(["kicad"])):
        assert "Stockroom" in text
        assert text.endswith("\n")


# -- placement bindings: which field carries a Stockroom part id on a placement ----


def test_every_tool_declares_how_a_placement_carries_its_stockroom_binding():
    """A durable assignment needs somewhere to live. That is per-tool DATA, never a branch:
    the field name a placement carries it in, and whether Stockroom can WRITE that field."""
    for tool in all_tools():
        pb = tool.placement_binding
        assert pb.field, f"{tool.key} declares no placement binding field"


def test_kicad_placements_are_writable_and_altium_placements_are_not():
    """The asymmetry that decides where a binding is STORED. Stockroom writes .kicad_sch
    byte-preservingly, so a KiCad binding lives in the design itself; it never writes Altium
    binary, so an Altium binding must live on the project record instead."""
    assert get_tool("kicad").placement_binding.writable is True
    assert get_tool("altium").placement_binding.writable is False
    assert get_tool("altium").placement_binding.reason


def test_a_third_tool_declares_its_binding_as_data_too():
    eagle = EdaTool(key="eagle", label="EAGLE",
                    placement_binding=PlacementBinding(field="SR_ID", writable=True))
    assert eagle.placement_binding.field == "SR_ID"
    assert eagle.placement_binding.writable is True
    # A tool that says nothing still has a usable default rather than None, so generic code
    # never has to test for absence.
    assert EdaTool(key="x", label="X").placement_binding.field


# -- path contracts: how a library reference resolves the same on a peer's machine ----


def test_every_tool_declares_how_its_library_paths_stay_portable():
    """A project references library assets by path. Whether that path means the same thing on a
    peer's machine is a fact ABOUT THE TOOL, so it is data here rather than a branch in whatever
    surface happens to be explaining it."""
    for tool in all_tools():
        pc = tool.path_contract
        assert pc.kind in ("env_var", "relative"), f"{tool.key} declares no path contract kind"
        assert pc.description, f"{tool.key} declares no path contract description"


def test_kicad_resolves_through_an_env_var_and_altium_resolves_relatively():
    """The concrete asymmetry the pin surface has to explain. KiCad needs SR_LIB set on every
    machine; an Altium DbLib names its data source relative to its own folder and needs nothing."""
    kicad = get_tool("kicad").path_contract
    assert kicad.kind == "env_var"
    assert kicad.variable == "SR_LIB"
    assert kicad.config_file == "kicad_common.json"
    assert kicad.prefix == "${SR_LIB}/"

    altium = get_tool("altium").path_contract
    assert altium.kind == "relative"
    assert altium.variable == ""


def test_a_tool_that_needs_no_variable_still_has_a_contract():
    """Generic code must never have to test for absence; an unset contract is still an answer."""
    assert EdaTool(key="x", label="X").path_contract.kind == "relative"


# -- derived artifacts: files Stockroom GENERATES and must not share through git ----


def test_altium_declares_its_generated_data_source_as_derived():
    """`stockroom-parts.db` is emitted from the JSON records. Sharing a derived binary through git
    means two peers who each add a different part produce two different unmergeable files for a
    file that carries no information the records do not already hold."""
    assert "stockroom-parts.db" in get_tool("altium").derived
    # the .DbLib is NOT derived in this sense: it is deterministic TEXT that only changes when the
    # column map does, and a human reviews it, so it stays shared
    assert not any("DbLib" in p for p in get_tool("altium").derived)


def test_a_derived_file_is_ignored_and_says_why_in_the_generated_file():
    text = workspace_gitignore(["altium"])
    assert "stockroom-parts.db" in text
    # a person opening the file must be able to tell a derived artifact from a per-user one,
    # because the remedy for each is completely different
    assert "regenerated" in text.lower()


def test_derived_patterns_join_the_ignore_set_used_to_untrack():
    """The untrack decision reads `ignored_patterns`, not `ignore`, or a derived file already
    committed would stay committed forever while the generated rules claimed otherwise."""
    tool = get_tool("altium")
    assert set(tool.ignore) <= set(tool.ignored_patterns())
    assert set(tool.derived) <= set(tool.ignored_patterns())


def test_a_tool_with_nothing_derived_emits_no_derived_section():
    text = workspace_gitignore(["kicad"])
    assert "Derived" not in text
