from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

import stockroom.eda.kicad_links as kicad_links
from stockroom.eda import (
    ArtifactDigest,
    DualEdaProjectionResult,
    KiCadLinkConflict,
    KiCadLinkProjectionError,
    ObservedPad,
    ObservedPin,
    ToolBinding,
    ToolProjection,
    project_portable_kicad_links,
)
from stockroom.kicad.lib_table import LibTable
from stockroom.sexp.document import SexpDocument


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _projection(
    component_character: str,
    *,
    symbol_digest_character: str,
    footprint_digest_character: str,
) -> DualEdaProjectionResult:
    component_id = f"cmp_{component_character * 52}"
    nickname = f"Stockroom_{component_id}"
    symbol_digest = _digest(symbol_digest_character)
    footprint_digest = _digest(footprint_digest_character)
    symbol_path = f"EDA/KiCad/Symbols/{symbol_digest.removeprefix('sha256:')}/S1M.kicad_sym"
    footprint_library = (
        f"EDA/KiCad/Footprints/{footprint_digest.removeprefix('sha256:')}/S1M.pretty"
    )
    footprint_path = f"{footprint_library}/S1M.kicad_mod"
    symbol_ref = f"{nickname}:S1M"
    footprint_ref = f"{nickname}:S1M"
    kicad = ToolProjection(
        tool="kicad",
        tool_version="10.0.4",
        fixture_mode=False,
        binding=ToolBinding(
            symbol_template_id="shared.passive.diode.two_pin.v1",
            footprint_template_id="shared.passive.diode.sma_do_214ac.v1",
            source_symbol_reference="Device:D",
            source_footprint_reference="Diode_SMD:D_SMA",
            symbol_library=symbol_path,
            symbol_library_nickname=nickname,
            symbol_ref=symbol_ref,
            footprint_library=footprint_library,
            footprint_library_nickname=nickname,
            footprint_ref=footprint_ref,
        ),
        artifacts=(
            ArtifactDigest(
                tool="kicad",
                kind="symbol",
                template_id="shared.passive.diode.two_pin.v1",
                reference=symbol_ref,
                relative_path=symbol_path,
                digest=symbol_digest,
                size_bytes=10,
            ),
            ArtifactDigest(
                tool="kicad",
                kind="footprint",
                template_id="shared.passive.diode.sma_do_214ac.v1",
                reference=footprint_ref,
                relative_path=footprint_path,
                digest=footprint_digest,
                size_bytes=20,
            ),
        ),
        pins=(
            ObservedPin(native_number="1", name="K", tool_terminal="1"),
            ObservedPin(native_number="2", name="A", tool_terminal="2"),
        ),
        pads=(
            ObservedPad(native_number="1", tool_terminal="1"),
            ObservedPad(native_number="2", tool_terminal="2"),
        ),
    )
    altium = ToolProjection(
        tool="altium",
        tool_version="",
        fixture_mode=True,
        binding=ToolBinding(
            symbol_template_id="shared.passive.diode.two_pin.v1",
            footprint_template_id="shared.passive.diode.sma_do_214ac.v1",
            source_symbol_reference="S1M",
            source_footprint_reference="DIOM5227X270N",
            symbol_library="EDA/Altium/Symbols/library/S1M.SchLib",
            symbol_library_nickname=None,
            symbol_ref="S1M",
            footprint_library="EDA/Altium/Footprints/library/S1M.PcbLib",
            footprint_library_nickname=None,
            footprint_ref="DIOM5227X270N",
        ),
        artifacts=(
            ArtifactDigest(
                tool="altium",
                kind="symbol",
                template_id="shared.passive.diode.two_pin.v1",
                reference="S1M",
                relative_path=(
                    f"EDA/Altium/Symbols/{_digest('d').removeprefix('sha256:')}/S1M.SchLib"
                ),
                digest=_digest("d"),
                size_bytes=30,
            ),
            ArtifactDigest(
                tool="altium",
                kind="footprint",
                template_id="shared.passive.diode.sma_do_214ac.v1",
                reference="DIOM5227X270N",
                relative_path=(
                    f"EDA/Altium/Footprints/{_digest('e').removeprefix('sha256:')}/S1M.PcbLib"
                ),
                digest=_digest("e"),
                size_bytes=40,
            ),
        ),
        pins=(
            ObservedPin(native_number="C", name="K", tool_terminal="C"),
            ObservedPin(native_number="A", name="A", tool_terminal="A"),
        ),
        pads=(
            ObservedPad(native_number="C", tool_terminal="C"),
            ObservedPad(native_number="A", tool_terminal="A"),
        ),
    )
    return DualEdaProjectionResult(
        canonical_bundle_digest=_digest(component_character),
        canonical_terminal_numbers=("1", "2"),
        kicad=kicad,
        altium=altium,
    )


def _rows(path: Path) -> list[tuple[str, str]]:
    document = SexpDocument.load(path)
    rows: list[tuple[str, str]] = []
    for node in document.root.find_all("lib"):
        name = node.find("name")
        uri = node.find("uri")
        assert name is not None
        assert uri is not None
        rows.append((name.children[1].value, uri.children[1].value))
    return rows


def test_projects_one_result_to_named_portable_tables_with_exact_readback(tmp_path):
    staging = tmp_path / "staging"
    staging.mkdir()
    source = _projection(
        "a",
        symbol_digest_character="1",
        footprint_digest_character="2",
    )

    projected = project_portable_kicad_links((source,), staging)

    symbol_path = staging / Path(projected.symbol_table.relative_path)
    footprint_path = staging / Path(projected.footprint_table.relative_path)
    assert symbol_path.name == "Stockroom-Portable-Symbol-Libraries.kicad-table"
    assert footprint_path.name == "Stockroom-Portable-Footprint-Libraries.kicad-table"
    assert symbol_path.is_file()
    assert footprint_path.is_file()
    assert "sym-lib-table" not in symbol_path.name
    assert "fp-lib-table" not in footprint_path.name
    assert LibTable.load(symbol_path).kind == "sym_lib_table"
    assert LibTable.load(footprint_path).kind == "fp_lib_table"

    nickname = source.kicad.binding.symbol_library_nickname
    assert nickname is not None
    expected_symbol_uri = f"${{SR_LIB}}/{source.kicad.binding.symbol_library}"
    expected_footprint_uri = f"${{SR_LIB}}/{source.kicad.binding.footprint_library}"
    assert _rows(symbol_path) == [(nickname, expected_symbol_uri)]
    assert _rows(footprint_path) == [(nickname, expected_footprint_uri)]
    assert projected.symbol_rows[0].library_reference == f"{nickname}:S1M"
    assert projected.footprint_rows[0].library_reference == f"{nickname}:S1M"
    assert projected.requires_machine_local_install is True
    for artifact, path in (
        (projected.symbol_table, symbol_path),
        (projected.footprint_table, footprint_path),
    ):
        assert artifact.digest == (f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}")
        assert artifact.size_bytes == path.stat().st_size


def test_multiple_results_are_byte_deterministic_regardless_of_input_order(tmp_path):
    first = _projection(
        "a",
        symbol_digest_character="1",
        footprint_digest_character="2",
    )
    second = _projection(
        "b",
        symbol_digest_character="3",
        footprint_digest_character="4",
    )
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()

    left_result = project_portable_kicad_links((first, second), left)
    right_result = project_portable_kicad_links((second, first), right)

    assert (left / left_result.symbol_table.relative_path).read_bytes() == (
        right / right_result.symbol_table.relative_path
    ).read_bytes()
    assert (left / left_result.footprint_table.relative_path).read_bytes() == (
        right / right_result.footprint_table.relative_path
    ).read_bytes()
    assert left_result == right_result


def test_conflicting_nickname_and_path_are_rejected_before_writes(tmp_path):
    first = _projection(
        "a",
        symbol_digest_character="1",
        footprint_digest_character="2",
    )
    same_nickname_new_path = _projection(
        "a",
        symbol_digest_character="3",
        footprint_digest_character="4",
    )
    nickname_staging = tmp_path / "nickname"
    nickname_staging.mkdir()
    with pytest.raises(KiCadLinkConflict, match="nickname"):
        project_portable_kicad_links(
            (first, same_nickname_new_path),
            nickname_staging,
        )
    assert list(nickname_staging.iterdir()) == []

    second = _projection(
        "b",
        symbol_digest_character="3",
        footprint_digest_character="4",
    )
    shared_symbol_binding = replace(
        second.kicad.binding,
        symbol_library=first.kicad.binding.symbol_library,
    )
    shared_symbol_artifact = replace(
        second.kicad.artifacts[0],
        relative_path=first.kicad.artifacts[0].relative_path,
        digest=first.kicad.artifacts[0].digest,
    )
    path_conflict = replace(
        second,
        kicad=replace(
            second.kicad,
            binding=shared_symbol_binding,
            artifacts=(shared_symbol_artifact, second.kicad.artifacts[1]),
        ),
    )
    path_staging = tmp_path / "path"
    path_staging.mkdir()
    with pytest.raises(KiCadLinkConflict, match="path"):
        project_portable_kicad_links((first, path_conflict), path_staging)
    assert list(path_staging.iterdir()) == []


def test_bare_reference_is_rejected_before_writes(tmp_path):
    source = _projection(
        "a",
        symbol_digest_character="1",
        footprint_digest_character="2",
    )
    object.__setattr__(source.kicad.binding, "symbol_ref", "S1M")
    staging = tmp_path / "staging"
    staging.mkdir()

    with pytest.raises(KiCadLinkProjectionError, match="must not be bare"):
        project_portable_kicad_links((source,), staging)

    assert list(staging.iterdir()) == []


def test_readback_failure_leaves_no_partial_tables(tmp_path, monkeypatch):
    source = _projection(
        "a",
        symbol_digest_character="1",
        footprint_digest_character="2",
    )
    staging = tmp_path / "staging"
    staging.mkdir()
    original = kicad_links._verify_table

    def fail_footprint(path, kind, rows):
        if kind == "footprint":
            raise KiCadLinkProjectionError("forced readback failure")
        original(path, kind, rows)

    monkeypatch.setattr(kicad_links, "_verify_table", fail_footprint)

    with pytest.raises(KiCadLinkProjectionError, match="forced readback"):
        project_portable_kicad_links((source,), staging)

    assert list(staging.iterdir()) == []
