"""Unit tests for the 3D model → GLB converter (M6d). The real STEP path is guarded
behind requires_glb_tooling; the failure paths run everywhere."""

from __future__ import annotations

import glob
import json
import shutil
import struct

import pytest

from stockroom.kicad.model_convert import (
    GLB_MAGIC,
    ModelConversionError,
    ModelToolingMissing,
    model_to_glb,
)
from tests.backend.conftest import requires_glb_tooling


def _gltf_json(data: bytes) -> dict:
    """Parse the JSON chunk out of GLB bytes. The viewer reads exactly this, so a test
    that asserts on it is asserting on what three.js will actually be handed."""
    assert data[:4] == GLB_MAGIC
    offset = 12
    while offset < len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        if kind == 0x4E4F534A:  # 'JSON'
            return json.loads(data[offset + 8 : offset + 8 + length])
        offset += 8 + length
    raise AssertionError("GLB has no JSON chunk")


def _find_step_with_colours(minimum: int = 2):
    """A system KiCad STEP whose own conversion yields >= `minimum` materials.

    Searched rather than hardcoded: which files ship, and which carry more than one
    colour, differs per KiCad install, and a fixture pinned to one filename would go
    silently unrun on a machine that lacks it."""
    cascadio = pytest.importorskip("cascadio")
    import tempfile

    for path in sorted(glob.glob("/usr/share/kicad/3dmodels/**/*.step", recursive=True))[:40]:
        out = tempfile.mktemp(suffix=".glb")
        try:
            cascadio.step_to_glb(path, out)
            with open(out, "rb") as fh:
                source = _gltf_json(fh.read())
        except Exception:
            continue
        if len(source.get("materials", [])) >= minimum:
            return path, source
    pytest.skip("no multi-colour system KiCad STEP model available")


@requires_glb_tooling
def test_model_to_glb_converts_a_trimesh_native_mesh(tmp_path):
    # A box exported to OBJ (a trimesh-native format) exercises the load→GLB path
    # with no dependence on cascadio or a system model file, so it is deterministic.
    import trimesh

    src = tmp_path / "box.obj"
    trimesh.creation.box(extents=(1, 1, 1)).export(str(src))
    data = model_to_glb(src)
    assert data[:4] == GLB_MAGIC
    assert len(data) > 100


@requires_glb_tooling
def test_model_to_glb_converts_a_real_kicad_step(tmp_path):
    steps = glob.glob("/usr/share/kicad/3dmodels/**/*.step", recursive=True)
    if not steps:
        pytest.skip("no system KiCad STEP models to convert")
    src = tmp_path / "part.step"
    shutil.copyfile(steps[0], src)
    data = model_to_glb(src)
    assert data[:4] == GLB_MAGIC
    assert len(data) > 100


@requires_glb_tooling
def test_model_to_glb_keeps_every_colour_the_step_declares():
    """The owner's ask is that a model be "coloured accordingly to what the model is".
    A STEP states its colours; the GLB we hand the viewer must state the same ones, or
    a gold-pinned black-bodied part arrives as one flat colour and no amount of viewer
    work can recover it."""
    path, source = _find_step_with_colours()
    expected = [m["pbrMetallicRoughness"]["baseColorFactor"] for m in source["materials"]]
    produced = _gltf_json(model_to_glb(path))
    actual = [m["pbrMetallicRoughness"]["baseColorFactor"] for m in produced["materials"]]
    assert sorted(map(tuple, actual)) == sorted(map(tuple, expected)), (
        f"{path}: the STEP declares {len(expected)} colours, the GLB carries {len(actual)}"
    )


@requires_glb_tooling
def test_model_to_glb_keeps_the_vertex_normals_the_conversion_produced():
    """A primitive with no NORMAL attribute shades flat and makes a screen-space
    ambient-occlusion pass reconstruct garbage, which is what rendered the model black.
    OpenCASCADE writes normals for every primitive; none may be dropped on the way out."""
    path, _ = _find_step_with_colours()
    produced = _gltf_json(model_to_glb(path))
    missing = [
        mesh.get("name", "?")
        for mesh in produced["meshes"]
        for prim in mesh["primitives"]
        if "NORMAL" not in prim["attributes"]
    ]
    assert missing == [], f"{path}: primitives with no NORMAL attribute: {missing}"


@requires_glb_tooling
def test_model_to_glb_states_a_surface_finish_instead_of_taking_gltfs_metal_default():
    """A STEP carries COLOUR, and nothing else. glTF's defaults for the two properties it
    therefore leaves unstated are `metallicFactor: 1.0` and `roughnessFactor: 1.0` - a
    fully metallic, fully rough surface - so a black epoxy body arrives as a metal whose
    reflectance is its own near-black colour and renders as a silhouette with no form.
    MEASURED in the running viewer on the owner's TPD6E05U06RVZR: the package's top face
    and its front face both read rgb(4,4,4) and rgb(2,2,2), identical with the ambient
    occlusion pass on and off, so the pass was never the cause.

    Omitting the factors is not neutrality: glTF fills them in either way. The converter
    states the finish a moulded/machined part actually has, and states it only where
    cascadio left the property unset, so a source that ever does declare one still wins."""
    path, _ = _find_step_with_colours(minimum=1)
    materials = _gltf_json(model_to_glb(path))["materials"]
    assert materials, f"{path}: converted with no materials at all"
    for mat in materials:
        pbr = mat["pbrMetallicRoughness"]
        assert "metallicFactor" in pbr, f"{path}: {mat.get('name')} defaults to metal"
        assert "roughnessFactor" in pbr, f"{path}: {mat.get('name')} defaults to fully rough"
        assert pbr["metallicFactor"] < 1.0, (
            f"{path}: {mat.get('name')} is fully metallic, which renders a dark colour black"
        )


def test_model_to_glb_gives_wrl_an_honest_message_not_install_cascadio(tmp_path):
    # WRL is a format the library legitimately stores, but trimesh has no VRML loader.
    # The failure must say STEP-only, NEVER tell the user to install cascadio (which is
    # already present and cannot convert WRL).
    wrl = tmp_path / "part.wrl"
    wrl.write_text("#VRML V2.0 utf8\n", encoding="utf-8")
    with pytest.raises(ModelConversionError) as exc:
        model_to_glb(wrl)
    msg = str(exc.value).lower()
    assert "step" in msg
    assert "cascadio" not in msg


def test_model_to_glb_raises_on_an_unconvertible_file(tmp_path):
    # Tooling present → a garbage STEP is a ModelConversionError; tooling absent → a
    # ModelToolingMissing on import. Either way it is one of the two honest 502 errors,
    # never a bare crash.
    bad = tmp_path / "bad.step"
    bad.write_text("this is not a real STEP file", encoding="utf-8")
    with pytest.raises((ModelConversionError, ModelToolingMissing)):
        model_to_glb(bad)
