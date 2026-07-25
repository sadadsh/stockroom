"""The EDA tool registry: the one place a tool's facts live.

Owner directive 2026-07-24: no major system may be specific to one EDA tool. These tests
lock the properties that make that true -- above all, that adding a third tool is ADDING A
REGISTRY ENTRY and not editing call sites.
"""
import pytest

from stockroom.eda.registry import (
    EdaTool,
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
