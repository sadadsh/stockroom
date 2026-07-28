"""Unit tests for the 3D model → GLB converter (M6d). The real STEP path is guarded
behind requires_glb_tooling; the failure paths run everywhere."""

from __future__ import annotations

import glob
import json
import math
import shutil
import struct

import pytest

from stockroom.kicad.model_convert import (
    GLB_MAGIC,
    ModelConversionError,
    ModelToolingMissing,
    _normalise_step_basis,
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


def _json_only_glb(gltf: dict) -> bytes:
    """Build the smallest valid GLB needed to test JSON-only conversion contracts."""
    payload = json.dumps(gltf, separators=(",", ":")).encode()
    payload += b" " * (-len(payload) % 4)
    return (
        GLB_MAGIC
        + struct.pack("<II", 2, 12 + 8 + len(payload))
        + struct.pack("<II", len(payload), 0x4E4F534A)
        + payload
    )


def _srgb(base_color):
    """glTF states baseColorFactor in LINEAR light; a colour a person can reason about is sRGB."""
    return [round((max(c, 0.0) ** (1 / 2.2)) * 255) for c in base_color[:3]]


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
    frame = _gltf_json(data)["asset"]["extras"]["stockroom"]
    assert frame == {
        "sourceFormat": "OBJ",
        "sourceUpAxis": "unknown",
        "sourceUnits": "unknown",
        "renderUpAxis": "Y",
        "renderUnits": "m",
        "basisTransform": "identity",
        "frameConfidence": "unresolved",
    }


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


def test_step_basis_normalisation_wraps_authored_roots_without_rewriting_them():
    """STEP is Z-up while glTF is Y-up; the conversion must state that mapping.

    This is a scene transform, not a vertex rewrite: geometry, normals, materials, and
    any converter-authored node transforms stay byte-for-byte represented by their
    original nodes beneath one explicit parent.
    """
    authored_nodes = [
        {"mesh": 0, "translation": [1, 2, 3]},
        {"mesh": 1, "rotation": [0, 0, 0, 1]},
    ]
    source = {
        "asset": {"version": "2.0", "extras": {"vendor": "preserved"}},
        "scene": 0,
        "scenes": [{"nodes": [0, 1]}],
        "nodes": authored_nodes,
        "meshes": [{"primitives": []}, {"primitives": []}],
    }

    produced = _gltf_json(_normalise_step_basis(_json_only_glb(source)))
    assert produced["nodes"][:2] == authored_nodes
    assert produced["asset"]["extras"]["vendor"] == "preserved"
    basis = produced["asset"]["extras"]["stockroom"]
    assert basis == {
        "sourceFormat": "STEP",
        "sourceUpAxis": "Z",
        "sourceUnits": "model-declared",
        "renderUpAxis": "Y",
        "renderUnits": "m",
        "basisTransform": "rotateX(-90deg)",
        "frameConfidence": "declared",
    }
    for scene in produced["scenes"]:
        assert len(scene["nodes"]) == 1
        wrapper = produced["nodes"][scene["nodes"][0]]
        assert wrapper["name"].startswith("Stockroom STEP Basis")
        assert wrapper["children"], "the wrapper must retain the converter-authored roots"
        assert wrapper["rotation"] == pytest.approx(
            [-math.sqrt(0.5), 0.0, 0.0, math.sqrt(0.5)]
        )


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
        # A material may legitimately be fully metallic now (a recognised pin colour, see
        # surface_finish), but a DARK one may not: metal has no diffuse response, so its
        # reflectance IS its base colour and a near-black metal renders as an unlit silhouette.
        if pbr["metallicFactor"] >= 1.0:
            assert max(_srgb(pbr.get("baseColorFactor", [0, 0, 0, 1]))) > 120, (
                f"{path}: {mat.get('name')} is fully metallic with a dark base colour, "
                "which renders as a black silhouette"
            )


@requires_glb_tooling
def test_model_to_glb_states_a_matte_finish_so_a_dark_body_is_not_a_mirror():
    """The stated finish must be MATTE MOULDED PLASTIC, because that is the class it is
    defaulting for - the constant's own reasoning is that "most of a package's visible
    surface is moulded plastic or ceramic".

    A semi-gloss default is not neutral, it is a third material that is neither. MEASURED
    in the running viewer on the owner's TPD6E05U06RVZR, whose body albedo is 0.0097
    (near black): at roughness 0.45 the package's top face rendered rgb(144,144,144), a
    MID GREY, because a near-black dielectric has almost no diffuse response and the only
    thing left to see is a broad 4% specular lobe reflecting the studio environment. The
    render was a mirror of the room, not a picture of the part, which is what the owner
    reported as "a flat dark box". Raising the finish to matte dropped the same face to
    rgb(90,90,90) and the body read as epoxy for the first time.

    The band, not a point value: below ~0.7 the environment starts to wash out the albedo
    again; at ~0.95+ the surface is chalk, which kills every highlight and is just as
    wrong for a moulded package."""
    path, _ = _find_step_with_colours(minimum=1)
    materials = _gltf_json(model_to_glb(path))["materials"]
    assert materials, f"{path}: converted with no materials at all"
    for mat in materials:
        pbr = mat["pbrMetallicRoughness"]
        # metals are deliberately smoother than moulded plastic; the matte band is about the
        # DIELECTRIC default, which is what a package body gets.
        if pbr["metallicFactor"] >= 1.0:
            continue
        roughness = pbr["roughnessFactor"]
        assert 0.7 <= roughness < 0.95, (
            f"{path}: {mat.get('name')} is stated at roughness {roughness}, outside the "
            "matte-moulded-plastic band; a semi-gloss default makes a near-black body "
            "render as a mid-grey mirror of the studio environment"
        )


@requires_glb_tooling
def test_model_to_glb_states_metal_for_a_known_pin_colour_but_not_for_nylon():
    """Leads are METAL and the converter has to say so, because STEP cannot.

    A tinned lead left at `metallicFactor 0` renders as salmon-coloured PLASTIC, and a dark matte
    body beside genuinely specular metal is most of what makes a real component photograph read as
    real. The signal is an EXACT match against the small palette the ecosystem actually emits -
    MEASURED over 130 real KiCad models, which between them use only 41 distinct colours, of which
    `(209,208,198)` (84 models) and `(218,187,126)` (42 models) are the tin and gold the generator
    gives pins.

    Exactness is the whole point, and this is the case that proves it: `(227,226,206)` is WHITE
    NYLON. It differs from the tin colour by 18/18/8 and any saturation-or-lightness rule that
    catches the tin catches the nylon too (both are achromatic and light). Verified on
    Molex_KK-254 by bounding volume - the nylon is the 344.7mm3 housing, the tin is the 28.9mm3
    pins - so a fuzzy rule would chrome-plate a connector body."""
    from stockroom.kicad.model_convert import surface_finish

    tin = surface_finish((209, 208, 198), "")
    gold = surface_finish((218, 187, 126), "")
    nylon = surface_finish((227, 226, 206), "")
    epoxy = surface_finish((42, 42, 42), "")

    assert tin.metallic == 1.0, "KiCad's tin pin colour must read as metal"
    assert gold.metallic == 1.0, "KiCad's gold pin colour must read as metal"
    assert nylon.metallic == 0.0, "white nylon housing must NOT be metal (Molex KK-254 body)"
    assert epoxy.metallic == 0.0, "black epoxy body must NOT be metal"
    # a metal is smoother than moulded plastic, but a plated lead is not a mirror
    assert 0.2 <= tin.roughness <= 0.5
    assert 0.7 <= epoxy.roughness < 0.95


@requires_glb_tooling
def test_model_to_glb_reads_a_vendors_leadframe_mesh_name_when_the_palette_is_unknown():
    """The palette table is a KiCad-ecosystem fact and a vendor STEP does not follow it.

    The owner's TPD6E05U06RVZR states its leads as (255,157,132), which is in no generator palette,
    so the colour table alone leaves them plastic. cascadio DOES preserve the vendor's own solid
    names though, and TI splits that part into `FRAME` (the leadframe) and `BODY`.

    This fallback fires RARELY and fails SAFE, which is the only reason it is defensible: MEASURED
    across 24 sampled KiCad models, every single one has exactly ONE mesh named after the FOOTPRINT
    (`PinHeader_2x29_P254mm_Vertical`), so the vocabulary never matches and they fall through to the
    palette. It must never override a colour the palette already recognises as non-metal."""
    from stockroom.kicad.model_convert import surface_finish

    assert surface_finish((255, 157, 132), "FRAME").metallic == 1.0
    assert surface_finish((255, 157, 132), "BODY").metallic == 0.0
    # a footprint-named mesh is the ordinary KiCad case and must not be read as a leadframe
    assert surface_finish((42, 42, 42), "PinHeader_2x29_P254mm_Vertical").metallic == 0.0
    # the vocabulary must not fire on a substring inside an unrelated word
    assert surface_finish((42, 42, 42), "MAINFRAMEWORK").metallic == 0.0


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
