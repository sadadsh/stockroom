"""Verify Stockroom's model placement against KiCad using real historical CAD.

The ten 270-degree cases are recovered byte-for-byte from the last historical
Stockroom library commit that contained them.  The live library is never read or
written.  For each pair this script:

1. verifies the fixed Git blob identities of the footprint and STEP model;
2. asks the installed KiCad CLI to export the footprint's placed component as GLB;
3. converts the same STEP through Stockroom's production converter; and
4. compares the resulting world-space geometry after Stockroom's placement matrix.

Evidence and intermediate files are written under ``--output``.  The script is an
explicit machine-dependent proof, not part of the ordinary unit-test gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, cast

import numpy as np
import trimesh

from stockroom.kicad.footprint import Footprint, ModelPlacement
from stockroom.kicad.model_convert import model_to_glb

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
SOURCE_REVISION = "dbaaf71f3aeb04cc322e76975a6549372a69142e"
# KiCad 10.0.4's native GLB export mounts front-side components 15 µm above
# the 1.6 mm board defined in BOARD_PREFIX.  This constant is the only allowed
# world-frame difference; asserting it prevents source-Z offset errors from
# being hidden by the comparison-frame alignment below.
EXPECTED_BOARD_MOUNT_ELEVATION_MM = 1.615


@dataclass(frozen=True)
class CorpusCase:
    name: str
    footprint_path: str
    footprint_blob: str
    model_path: str
    model_blob: str
    model_bytes: int


@dataclass(frozen=True)
class InstalledCase:
    name: str
    footprint_relative: str
    model_relative: str


CORPUS_270 = (
    CorpusCase(
        "73251-2120",
        "libraries/Stockroom/footprints/SR-Connectors.pretty/73251-2120.kicad_mod",
        "ef978568216287b9a66fca383994abaf4c48a7a4",
        "libraries/Stockroom/models/73251-2120.step",
        "e1c89c9d7c3fa80d63ab622601c7fb6375be02e6",
        2_070_230,
    ),
    CorpusCase(
        "103AT-2",
        "libraries/Stockroom/footprints/SR-Diodes.pretty/103AT-2.kicad_mod",
        "775d9d5e476f7d9bca5cea1c69c98760f3598053",
        "libraries/Stockroom/models/103AT-2.step",
        "562705b0fdedd332338b5092d6456d2b4afcf2e1",
        406_909,
    ),
    CorpusCase(
        "TPD4E05U06DQAR",
        "libraries/Stockroom/footprints/SR-Diodes.pretty/TPD4E05U06DQAR.kicad_mod",
        "8198518ba1bcb36b7f3573b2fd7ed0225c539d7a",
        "libraries/Stockroom/models/TPD4E05U06DQAR.step",
        "6f87f145ccec2806157b4f6109fed8f13d95f43b",
        1_951_679,
    ),
    CorpusCase(
        "DRV2605LDGSR",
        "libraries/Stockroom/footprints/SR-ICs.pretty/DRV2605LDGSR.kicad_mod",
        "5087a644dd5271bcef9df4ca23b1a5b934023461",
        "libraries/Stockroom/models/DRV2605LDGSR.step",
        "f75bdcd379eecf0cd086c834b3ad7b45b13a6628",
        3_725_997,
    ),
    CorpusCase(
        "MAX6817EUT+T",
        "libraries/Stockroom/footprints/SR-ICs.pretty/MAX6817EUT+T.kicad_mod",
        "f41d28f37a82ee3098a5c012f4b9fec99c7bf72a",
        "libraries/Stockroom/models/MAX6817EUT+T.step",
        "07fc99fd1836ea7e566f1e03acdf114f08c1521c",
        3_277_159,
    ),
    CorpusCase(
        "TLV7021DBVR",
        "libraries/Stockroom/footprints/SR-Other.pretty/TLV7021DBVR.kicad_mod",
        "028e822e6ad8e1a582325ca9b2096660c96ce168",
        "libraries/Stockroom/models/TLV7021DBVR.step",
        "d01507eb4b1ac140183cce633e4c4de171141bcb",
        1_599_556,
    ),
    CorpusCase(
        "AF0603FR-072R2L",
        "libraries/Stockroom/footprints/SR-Resistors.pretty/AF0603FR-072R2L.kicad_mod",
        "32dea0ebb7903aa30037b61591ed098bf8d67637",
        "libraries/Stockroom/models/AF0603FR-072R2L.step",
        "07e4a27ac8457657fa4e7d2758db843755c6b890",
        1_046_656,
    ),
    CorpusCase(
        "TPS2121RUXR",
        "libraries/Stockroom/footprints/SR-Switches.pretty/TPS2121RUXR.kicad_mod",
        "a20f1029faeeae58dcffbc14aec4d18c5ec48bf6",
        "libraries/Stockroom/models/TPS2121RUXR.step",
        "2774e0d01e4c6cf0ff859e75297cbb8e5076af18",
        2_110_038,
    ),
    CorpusCase(
        "DMG3414U-7",
        "libraries/Stockroom/footprints/SR-Transistors.pretty/DMG3414U-7.kicad_mod",
        "d99fedb8ca22d5eb172f86eeeddc545ae552aeda",
        "libraries/Stockroom/models/DMG3414U-7.step",
        "0a9a5a0061b0cc64eca22d9f1e81e696dd899f94",
        1_214_930,
    ),
    CorpusCase(
        "DMN2056U-7",
        "libraries/Stockroom/footprints/SR-Transistors.pretty/DMN2056U-7.kicad_mod",
        "8c235d4398c9254e9524889643e989fee79cc00d",
        "libraries/Stockroom/models/DMN2056U-7.step",
        "0a9a5a0061b0cc64eca22d9f1e81e696dd899f94",
        1_214_930,
    ),
)

INSTALLED_FIELD_COVERAGE = (
    InstalledCase(
        "KiCad Bosch LGA Offset",
        "footprints/Package_LGA.pretty/Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.kicad_mod",
        "3dmodels/Package_LGA.3dshapes/Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering.step",
    ),
    InstalledCase(
        "KiCad Finder Relay Offset",
        "footprints/Relay_THT.pretty/Relay_SPST_Finder_32.21-x300.kicad_mod",
        "3dmodels/Relay_THT.3dshapes/Relay_SPST_Finder_32.21-x300.step",
    ),
)

# Current KiCad library policy requires STEP models to be authored at identity
# scale and placement.  Consequently there is no honest current upstream
# non-identity STEP scale pair to cite.  This stress placement is kept separate
# from the real corpus: it uses the real Bosch LGA footprint and STEP bytes,
# but asks both KiCad and Stockroom to apply the same deliberately difficult
# transform so every affine field and multiplication-order interaction is tested.
FIELD_STRESS_PLACEMENT = ModelPlacement(
    offset=(8.89, -24.13, 1.25),
    scale=(1.2, 0.8, 1.5),
    rotate=(35.0, -20.0, 270.0),
)


BOARD_PREFIX = """(kicad_pcb
\t(version 20260206)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(general (thickness 1.6))
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(31 "B.Cu" signal)
\t\t(36 "B.SilkS" user "b.silkscreen")
\t\t(37 "F.SilkS" user "f.silkscreen")
\t\t(44 "Edge.Cuts" user)
\t)
\t(setup (pad_to_mask_clearance 0))
\t(net 0 "")
"""


def _run(
    args: list[str],
    *,
    cwd: Path = REPOSITORY_ROOT,
    check: bool = True,
) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        args,
        cwd=cwd,
        check=check,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def _git_bytes(revision: str, path: str) -> bytes:
    return _run(["git", "show", f"{revision}:{path}"]).stdout


def _git_blob(revision: str, path: str) -> str:
    return _run(["git", "rev-parse", f"{revision}:{path}"]).stdout.decode().strip()


def _historical_corpus() -> tuple[CorpusCase, ...]:
    paths = (
        _run(
            [
                "git",
                "ls-tree",
                "-r",
                "--name-only",
                SOURCE_REVISION,
                "--",
                "libraries/Stockroom/footprints",
            ]
        )
        .stdout.decode()
        .splitlines()
    )
    cases: list[CorpusCase] = []
    for footprint_path in paths:
        if not footprint_path.endswith(".kicad_mod"):
            continue
        footprint_bytes = _git_bytes(SOURCE_REVISION, footprint_path)
        match = re.search(rb'\(model\s+"(\$\{SR_LIB\}/[^"]+\.(?:step|stp))"', footprint_bytes, re.I)
        if match is None:
            continue
        model_path = "libraries/Stockroom/" + match.group(1).decode().removeprefix("${SR_LIB}/")
        try:
            model_bytes = _git_bytes(SOURCE_REVISION, model_path)
        except subprocess.CalledProcessError:
            continue
        cases.append(
            CorpusCase(
                name=Path(footprint_path).stem,
                footprint_path=footprint_path,
                footprint_blob=_git_blob(SOURCE_REVISION, footprint_path),
                model_path=model_path,
                model_blob=_git_blob(SOURCE_REVISION, model_path),
                model_bytes=len(model_bytes),
            )
        )
    return tuple(cases)


def _find_kicad_cli() -> str:
    candidates = [
        shutil.which("kicad-cli"),
        shutil.which("kicad-cli.cmd"),
        str(
            Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
            / "KiCad/10.0/bin/kicad-cli.exe"
        ),
        str(REPOSITORY_ROOT.parent.parent / "System/Capabilities/Bin/kicad-cli.cmd"),
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return candidate
    raise RuntimeError("KiCad 10 CLI was not found")


def _find_kicad_share() -> Path:
    configured = os.environ.get("KICAD10_SHARE")
    candidates = [
        Path(configured) if configured else None,
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "KiCad/10.0/share/kicad",
    ]
    for candidate in candidates:
        if candidate and (candidate / "footprints").is_dir() and (candidate / "3dmodels").is_dir():
            return candidate
    raise RuntimeError("KiCad 10 footprint and 3D-model libraries were not found")


def _write_verified_blob(case: CorpusCase, output: Path, *, footprint: bool) -> Path:
    source_path = case.footprint_path if footprint else case.model_path
    expected_blob = case.footprint_blob if footprint else case.model_blob
    actual_blob = _git_blob(SOURCE_REVISION, source_path)
    if actual_blob != expected_blob:
        raise RuntimeError(f"{source_path}: expected Git blob {expected_blob}, got {actual_blob}")
    data = _git_bytes(SOURCE_REVISION, source_path)
    if not footprint and len(data) != case.model_bytes:
        raise RuntimeError(f"{source_path}: expected {case.model_bytes} bytes, got {len(data)}")
    target = output / source_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _board_with_one_footprint(footprint_path: Path) -> str:
    footprint = footprint_path.read_text(encoding="utf-8")
    # A library footprint has no board position.  Place it at the board origin so
    # KiCad's export contains only the model-placement transform under test.
    if not re.search(r"^\s*\(at\s", footprint, flags=re.MULTILINE):
        footprint = re.sub(
            r'(\n\s*\(layer\s+"F\.Cu"\)\s*)',
            r"\1\n\t(at 0 0)\n",
            footprint,
            count=1,
        )
    return f"{BOARD_PREFIX}{footprint}\n)\n"


def _replace_model_placement(text: str, placement: ModelPlacement) -> str:
    def replace(key: str, values: tuple[float, float, float]) -> None:
        nonlocal text
        rendered = " ".join(f"{value:g}" for value in values)
        pattern = rf"(\({key}\s*\(xyz\s+)[^\)]+(\)\s*\))"
        text, count = re.subn(pattern, rf"\g<1>{rendered}\g<2>", text, count=1)
        if count != 1:
            raise RuntimeError(f"could not replace the model {key} block")

    replace("offset", placement.offset)
    replace("scale", placement.scale)
    replace("rotate", placement.rotate)
    return text


def _scene_mesh(path: Path) -> trimesh.Trimesh:
    scene = cast(trimesh.Scene, trimesh.load(path, force="scene"))
    mesh = scene.to_mesh()
    if len(mesh.vertices) == 0:
        raise RuntimeError(f"{path}: GLB contains no geometry")
    return mesh


def _stockroom_placement_matrix(placement: ModelPlacement) -> np.ndarray[Any, np.dtype[np.float64]]:
    """The exact column-vector matrix order used by placementTransform.ts."""

    def rotation_x(degrees: float) -> np.ndarray[Any, np.dtype[np.float64]]:
        angle = math.radians(-degrees)
        c, s = math.cos(angle), math.sin(angle)
        return np.array(((1, 0, 0, 0), (0, c, -s, 0), (0, s, c, 0), (0, 0, 0, 1)), dtype=float)

    def rotation_y(degrees: float) -> np.ndarray[Any, np.dtype[np.float64]]:
        angle = math.radians(-degrees)
        c, s = math.cos(angle), math.sin(angle)
        return np.array(((c, 0, s, 0), (0, 1, 0, 0), (-s, 0, c, 0), (0, 0, 0, 1)), dtype=float)

    def rotation_z(degrees: float) -> np.ndarray[Any, np.dtype[np.float64]]:
        angle = math.radians(-degrees)
        c, s = math.cos(angle), math.sin(angle)
        return np.array(((c, -s, 0, 0), (s, c, 0, 0), (0, 0, 1, 0), (0, 0, 0, 1)), dtype=float)

    translation = np.eye(4)
    translation[:3, 3] = placement.offset
    scale = np.diag((*placement.scale, 1.0))
    source = (
        translation
        @ rotation_z(placement.rotate[2])
        @ rotation_y(placement.rotate[1])
        @ rotation_x(placement.rotate[0])
        @ scale
    )
    # Stockroom's STEP converter has already wrapped model vertices in B.  The
    # frontend therefore applies B K B^-1 around those converted vertices.
    basis = np.array(
        ((1, 0, 0, 0), (0, 0, 1, 0), (0, -1, 0, 0), (0, 0, 0, 1)),
        dtype=float,
    )
    return basis @ source @ np.linalg.inv(basis)


def _glb_json(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    offset = 12
    while offset + 8 <= len(data):
        length = int.from_bytes(data[offset : offset + 4], "little")
        kind = int.from_bytes(data[offset + 4 : offset + 8], "little")
        if kind == 0x4E4F534A:
            return json.loads(data[offset + 8 : offset + 8 + length])
        offset += 8 + length
    raise RuntimeError(f"{path}: GLB has no JSON chunk")


def _node_matrix(node: dict[str, Any]) -> np.ndarray[Any, np.dtype[np.float64]]:
    if "matrix" in node:
        return np.asarray(node["matrix"], dtype=float).reshape((4, 4), order="F")
    translation = np.eye(4)
    translation[:3, 3] = node.get("translation", (0.0, 0.0, 0.0))
    x, y, z, w = node.get("rotation", (0.0, 0.0, 0.0, 1.0))
    rotation = trimesh.transformations.quaternion_matrix((w, x, y, z))
    scale = np.diag((*node.get("scale", (1.0, 1.0, 1.0)), 1.0))
    return translation @ rotation @ scale


def _kicad_component_matrix(
    path: Path,
) -> tuple[np.ndarray[Any, np.dtype[np.float64]], dict[str, Any]]:
    gltf = _glb_json(path)
    candidates = [
        node
        for node in gltf.get("nodes", [])
        if node.get("name") == "REF**" or str(node.get("name", "")).startswith("REF")
    ]
    if len(candidates) != 1:
        raise RuntimeError(f"{path}: expected one KiCad component node, found {len(candidates)}")
    return _node_matrix(candidates[0]), candidates[0]


def _geometry_summary(mesh: trimesh.Trimesh) -> dict[str, Any]:
    bounds = mesh.bounds
    return {
        "vertices": int(len(mesh.vertices)),
        "faces": int(len(mesh.faces)),
        "centroid_mm": mesh.centroid.tolist(),
        "bounds": bounds.tolist(),
        "extents": (bounds[1] - bounds[0]).tolist(),
        "area_mm2": float(mesh.area),
    }


def _verify_materialized_case(
    *,
    name: str,
    case_dir: Path,
    footprint_path: Path,
    model_path: Path,
    kicad_cli: str,
    define_vars: dict[str, Path],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    placement = Footprint.load(footprint_path).model_placement
    if placement is None:
        raise RuntimeError(f"{name}: footprint has no model placement")

    board_path = case_dir / f"{name}.kicad_pcb"
    board_path.write_text(_board_with_one_footprint(footprint_path), encoding="utf-8", newline="")
    kicad_glb = case_dir / "KiCad Placed.glb"
    command = [
        kicad_cli,
        "pcb",
        "export",
        "glb",
        "--force",
        "--no-board-body",
    ]
    for key, value in define_vars.items():
        command.extend(("--define-var", f"{key}={value}"))
    command.extend(("--output", str(kicad_glb), str(board_path)))
    completed = _run(command)
    if not kicad_glb.exists():
        detail = (completed.stdout + completed.stderr).decode(errors="replace")
        raise RuntimeError(f"{name}: KiCad did not create GLB: {detail}")

    stockroom_glb = case_dir / "Stockroom Converted.glb"
    stockroom_glb.write_bytes(model_to_glb(model_path))

    # KiCad's GLB is in metres.  Stockroom's Three scene multiplies the converted
    # model by 1000 before applying the footprint matrix, so both are normalized
    # to millimetres here.
    kicad_mesh = _scene_mesh(kicad_glb)
    kicad_mesh.apply_scale(1000.0)
    stockroom_mesh = _scene_mesh(stockroom_glb)
    stockroom_mesh.apply_scale(1000.0)
    stockroom_matrix = _stockroom_placement_matrix(placement)
    stockroom_mesh.apply_transform(stockroom_matrix)

    kicad_matrix_m, kicad_node = _kicad_component_matrix(kicad_glb)
    kicad_matrix_mm = kicad_matrix_m.copy()
    kicad_matrix_mm[:3, 3] *= 1000.0
    translation_delta = kicad_matrix_mm[:3, 3] - stockroom_matrix[:3, 3]
    # The only expected difference is KiCad's constant board-front mounting
    # elevation.  Applying it puts both meshes in exactly the same world frame.
    stockroom_mesh.apply_translation(translation_delta)

    stockroom_linear = stockroom_matrix[:3, :3]
    stockroom_column_scales = np.linalg.norm(stockroom_linear, axis=0)
    # KiCad's GLB exporter bakes non-identity model scale into the exported
    # vertices while retaining rotation on the component node.  Compare that
    # node with Stockroom's scale-stripped rotation, and compare the resulting
    # world geometry below to prove scale itself.
    if np.any(stockroom_column_scales <= 1e-12):
        stockroom_rotation = stockroom_linear
        kicad_export_baked_scale = False
    else:
        stockroom_rotation = stockroom_linear / stockroom_column_scales
        kicad_export_baked_scale = not np.allclose(stockroom_column_scales, 1.0)
    linear_error = float(np.max(np.abs(kicad_matrix_mm[:3, :3] - stockroom_rotation)))
    horizontal_translation_error = float(np.max(np.abs(translation_delta[[0, 2]])))
    board_mount_elevation_error_mm = float(
        abs(translation_delta[1] - EXPECTED_BOARD_MOUNT_ELEVATION_MM)
    )
    bounds_error_mm = float(np.max(np.abs(kicad_mesh.bounds - stockroom_mesh.bounds)))
    extents_error_mm = float(np.max(np.abs(kicad_mesh.extents - stockroom_mesh.extents)))
    centroid_error_mm = float(np.linalg.norm(kicad_mesh.centroid - stockroom_mesh.centroid))
    area_relative_error = float(
        abs(kicad_mesh.area - stockroom_mesh.area) / max(kicad_mesh.area, stockroom_mesh.area)
    )
    opposite = ModelPlacement(
        offset=placement.offset,
        scale=placement.scale,
        rotate=(-placement.rotate[0], -placement.rotate[1], -placement.rotate[2]),
    )
    opposite_sign_linear_error = float(
        np.max(np.abs(kicad_matrix_mm[:3, :3] - _stockroom_placement_matrix(opposite)[:3, :3]))
    )
    passed = (
        linear_error <= 1e-9
        and horizontal_translation_error <= 1e-6
        and board_mount_elevation_error_mm <= 1e-6
        and bounds_error_mm <= 0.002
        and extents_error_mm <= 0.002
        and area_relative_error <= 0.02
    )
    return {
        **provenance,
        "name": name,
        "placement": asdict(placement),
        "footprint_sha256": hashlib.sha256(footprint_path.read_bytes()).hexdigest(),
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "kicad_cli": (completed.stdout + completed.stderr).decode(errors="replace").strip(),
        "kicad_component_node": kicad_node,
        "kicad_component_matrix_mm": kicad_matrix_mm.tolist(),
        "stockroom_component_matrix_mm": stockroom_matrix.tolist(),
        "stockroom_column_scales": stockroom_column_scales.tolist(),
        "kicad_export_baked_scale": kicad_export_baked_scale,
        "board_mount_translation_mm": translation_delta.tolist(),
        "linear_matrix_error": linear_error,
        "horizontal_translation_error_mm": horizontal_translation_error,
        "board_mount_elevation_error_mm": board_mount_elevation_error_mm,
        "opposite_sign_linear_error": opposite_sign_linear_error,
        "bounds_error_mm": bounds_error_mm,
        "extents_error_mm": extents_error_mm,
        "surface_centroid_error_mm": centroid_error_mm,
        "surface_area_relative_error": area_relative_error,
        "kicad": _geometry_summary(kicad_mesh),
        "stockroom": _geometry_summary(stockroom_mesh),
        "passed": passed,
    }


def verify_case(case: CorpusCase, output: Path, kicad_cli: str) -> dict[str, Any]:
    case_dir = output / "Cases" / case.name
    footprint_path = _write_verified_blob(case, case_dir, footprint=True)
    model_path = _write_verified_blob(case, case_dir, footprint=False)
    return _verify_materialized_case(
        name=case.name,
        case_dir=case_dir,
        footprint_path=footprint_path,
        model_path=model_path,
        kicad_cli=kicad_cli,
        define_vars={"SR_LIB": case_dir / "libraries/Stockroom"},
        provenance=asdict(case) | {"source": "historical-stockroom-git"},
    )


def verify_installed_case(
    case: InstalledCase,
    output: Path,
    kicad_cli: str,
    kicad_share: Path,
) -> dict[str, Any]:
    case_dir = output / "Cases" / case.name
    case_dir.mkdir(parents=True, exist_ok=True)
    footprint_source = kicad_share / case.footprint_relative
    model_source = kicad_share / case.model_relative
    if not footprint_source.is_file() or not model_source.is_file():
        raise RuntimeError(f"{case.name}: installed KiCad pair is missing")
    footprint_path = case_dir / footprint_source.name
    shutil.copyfile(footprint_source, footprint_path)
    return _verify_materialized_case(
        name=case.name,
        case_dir=case_dir,
        footprint_path=footprint_path,
        model_path=model_source,
        kicad_cli=kicad_cli,
        define_vars={"KICAD10_3DMODEL_DIR": kicad_share / "3dmodels"},
        provenance={
            "source": "installed-kicad-10-library",
            "footprint_path": str(footprint_source),
            "model_path": str(model_source),
            "footprint_blob": None,
            "model_blob": None,
            "model_bytes": model_source.stat().st_size,
        },
    )


def verify_field_stress(
    source: InstalledCase,
    output: Path,
    kicad_cli: str,
    kicad_share: Path,
) -> dict[str, Any]:
    case_dir = output / "Cases" / "Native KiCad Full Affine Field Stress"
    case_dir.mkdir(parents=True, exist_ok=True)
    footprint_source = kicad_share / source.footprint_relative
    model_source = kicad_share / source.model_relative
    footprint_path = case_dir / footprint_source.name
    footprint_path.write_text(
        _replace_model_placement(
            footprint_source.read_text(encoding="utf-8"),
            FIELD_STRESS_PLACEMENT,
        ),
        encoding="utf-8",
        newline="",
    )
    return _verify_materialized_case(
        name="Native KiCad Full Affine Field Stress",
        case_dir=case_dir,
        footprint_path=footprint_path,
        model_path=model_source,
        kicad_cli=kicad_cli,
        define_vars={"KICAD10_3DMODEL_DIR": kicad_share / "3dmodels"},
        provenance={
            "source": "explicit-native-kicad-field-stress",
            "real_pair_source": asdict(source),
            "placement_original": False,
            "purpose": "prove combined rotate + offset + anisotropic scale and order",
            "model_bytes": model_source.stat().st_size,
            "footprint_blob": None,
            "model_blob": None,
        },
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=REPOSITORY_ROOT / "work/Library Punch Completion/3D Rotation Proof",
    )
    parser.add_argument("--case")
    parser.add_argument(
        "--scope",
        choices=("270", "full"),
        default="full",
        help="Use only the ten 270-degree cases or all 58 historical real pairs.",
    )
    parser.add_argument(
        "--skip-installed-coverage",
        action="store_true",
        help="Skip the two installed KiCad pairs and the explicit full-affine stress case.",
    )
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    kicad_cli = _find_kicad_cli()
    historical = _historical_corpus()
    if len(historical) != 58:
        raise RuntimeError(f"expected 58 real historical pairs, found {len(historical)}")
    by_name = {case.name: case for case in historical}
    for expected in CORPUS_270:
        actual = by_name.get(expected.name)
        if actual != expected:
            raise RuntimeError(f"{expected.name}: fixed 270-degree corpus identity changed")
    selected = list(CORPUS_270 if args.scope == "270" else historical)
    if args.case:
        selected = [case for case in selected if case.name == args.case]
        if not selected:
            raise RuntimeError(f"case {args.case!r} is not in the selected historical scope")
    kicad_share = None if args.skip_installed_coverage else _find_kicad_share()
    report = {
        "schema": "stockroom-3d-placement-proof/1",
        "source_revision": SOURCE_REVISION,
        "kicad_cli": kicad_cli,
        "historical_pair_count": len(historical),
        "historical_rotation_distribution": {},
        "cases": [],
    }
    for case in historical:
        data = _git_bytes(SOURCE_REVISION, case.footprint_path)
        temporary = output / "Placement Readback.kicad_mod"
        temporary.write_bytes(data)
        placement = Footprint.load(temporary).model_placement
        key = "missing" if placement is None else ",".join(str(value) for value in placement.rotate)
        distribution = report["historical_rotation_distribution"]
        distribution[key] = distribution.get(key, 0) + 1
    for case in selected:
        print(f"Verifying {case.name}...", flush=True)
        report["cases"].append(verify_case(case, output, kicad_cli))
    if kicad_share is not None and args.case is None:
        for case in INSTALLED_FIELD_COVERAGE:
            print(f"Verifying {case.name}...", flush=True)
            report["cases"].append(verify_installed_case(case, output, kicad_cli, kicad_share))
        print("Verifying native KiCad full affine field stress...", flush=True)
        report["cases"].append(
            verify_field_stress(
                INSTALLED_FIELD_COVERAGE[0],
                output,
                kicad_cli,
                kicad_share,
            )
        )
    report["passed"] = all(case["passed"] for case in report["cases"])
    report["passed_count"] = sum(case["passed"] for case in report["cases"])
    report["failed_count"] = sum(not case["passed"] for case in report["cases"])
    report_path = output / "Report.json"
    report_path.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8", newline="")
    print(report_path)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
