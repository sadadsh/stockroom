"""3D model → GLB conversion for the web 3D preview (M6d).

The library stores each part's 3D model as the KiCad file the user dropped in, which
is normally STEP (a footprint may instead carry a WRL/VRML mesh). The browser's
three.js viewer wants GLB, so a STEP is converted by cascadio (OpenCASCADE) and its
bytes are handed straight through; anything else trimesh loads natively is exported by
trimesh. trimesh has no VRML loader, so WRL/VRML models are not convertible yet and are
reported honestly (never a "install cascadio" misdirection). The stack is OPTIONAL
tooling: when trimesh/cascadio are not installed the caller surfaces an honest 502,
never a crash, and the symbol/footprint SVG previews still work without it.

**STEP does NOT go through trimesh, deliberately.** It used to, and the round trip
through trimesh's scene model silently destroyed two things the viewer needs, because
trimesh re-exports its own idea of the scene rather than passing the bytes on:
  * every material past the first was MERGED AWAY. Measured: the owner's part declares
    three colours (grey leads / orange pin-1 marker / black epoxy) and arrived with two;
    a stock `PinHeader_2x31` and `DIP-4_W7.62mm_SMDSocket` each declare two and arrived
    with one. The surviving colour was also requantised to 8 bits.
  * `NORMAL` attributes were DROPPED from primitives that had them, so the model shaded
    flat and a screen-space ambient-occlusion pass reconstructed garbage from the
    missing normals and rendered it black.
A single-colour model survived either path intact, which is why the loss went unseen.
Both outputs are in glTF's mandated METRES (verified: a 3.5mm part measures 0.0035 on
both paths), so the viewer's millimetre normalisation is unaffected by the route taken."""

from __future__ import annotations

import importlib
import json
import math
import re
import struct
import tempfile
from pathlib import Path
from typing import NamedTuple

# GLB (binary glTF) starts with the ASCII magic "glTF"; named here so the converter
# and its tests share one contract for "this really is a GLB".
GLB_MAGIC = b"glTF"

# Mesh formats trimesh cannot load here (no VRML loader). A part legitimately stores a
# WRL, so it gets an honest "not convertible yet" message, not a tooling-missing one.
_UNSUPPORTED_SUFFIXES = {".wrl", ".vrml", ".x3d"}

# STEP is converted by cascadio directly rather than through trimesh (see the module
# docstring). Both spellings are in real use in KiCad libraries.
_STEP_SUFFIXES = {".step", ".stp"}


class ModelToolingMissing(RuntimeError):
    """trimesh (and cascadio for STEP) are not installed, so 3D previews cannot be
    produced on this machine. Surfaced as a 502 with guidance, never a 500."""


class ModelConversionError(RuntimeError):
    """The model file is present but could not be turned into a GLB (an unreadable
    STEP, an empty mesh, a format trimesh has no loader for). Honest, not a crash."""


def _glb_mesh_count(data: bytes) -> int:
    """How many meshes the GLB declares, read from its JSON chunk.

    An empty conversion is a real outcome (a STEP that carries only assembly structure,
    or geometry OpenCASCADE could not tessellate), and it must be an honest 502 rather
    than a valid-looking GLB the viewer renders as a blank canvas. A JSON chunk we
    cannot parse counts as no meshes for the same reason."""
    if data[:4] != GLB_MAGIC:
        return 0
    offset = 12
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        if kind == 0x4E4F534A:  # 'JSON'
            try:
                return len(json.loads(data[offset + 8 : offset + 8 + length]).get("meshes", []))
            except Exception:
                return 0
        offset += 8 + length
    return 0


# The surface finish a STEP-derived material is given when it states none of its own.
#
# STEP carries COLOUR and nothing else - there is no metalness or roughness anywhere in
# the format - so glTF's own defaults decide, and they are the worst possible pair for a
# component: `metallicFactor: 1.0`, `roughnessFactor: 1.0`. A fully metallic surface has
# no diffuse response at all; its reflectance IS its base colour. So the black epoxy an
# IC package is made of (measured on the owner's TPD6E05U06RVZR: baseColorFactor 0.0097)
# became a metal that reflects almost nothing, and rendered as a black silhouette with no
# form - the "model renders pure black" symptom that had been attributed to the ambient
# occlusion pass for two sessions. Disabling that pass changes the measured body colour by
# nothing at all (rgb(4,4,4) either way); these two numbers are the whole cause.
#
# A DIELECTRIC is the right default because most of a package's visible surface is moulded
# plastic or ceramic. The leads genuinely are metal and will read as light grey rather than
# as chrome; that is accepted deliberately, because the only signal available to tell metal
# from plastic is the colour, and "grey means metal" is a guess that would repaint every
# grey ceramic body as steel. cascadio names its materials mat_0..mat_n, so there is no
# material name to read either.
_STEP_METALLIC = 0.0
# MATTE, because that is the class this constant is defaulting FOR - the paragraph above
# picks a dielectric on the grounds that "most of a package's visible surface is moulded
# plastic or ceramic", and then stated a semi-gloss 0.45 that is neither plastic nor metal.
# 0.45 was a number with no reasoning attached, and on a dark body it was the whole defect:
#
# MEASURED in the running viewer on the owner's TPD6E05U06RVZR (body albedo 0.0097, i.e.
# near black), top face of the package, dark theme, same camera and same lighting:
#     roughness 0.45 -> rgb(144,144,144)      roughness 0.85 -> rgb(90,90,90)
# A near-black dielectric has essentially no diffuse response, so all that remains is the
# ~4% specular lobe - and at 0.45 that lobe is tight enough to hand back a clean image of
# the studio environment. The viewer was rendering the ROOM, not the part, which is what
# the owner reported as the body being "a flat dark box". Widening the lobe lets the albedo
# win again and the epoxy reads as epoxy.
#
# 0.8 rather than a tuned number: it is the practitioner-consensus value for black moulded
# plastic in glTF/three.js PBR, and it sits inside the band the test pins (>=0.7, or the
# environment starts washing the albedo out again; <0.95, or the surface is chalk and every
# highlight dies). The leads keep this finish too - see the metal caveat above, which is
# unchanged and still deliberate.
_STEP_ROUGHNESS = 0.8

# The finish of a surface the converter has decided is PLATED METAL rather than moulded plastic.
# A lead left dielectric renders as coloured PLASTIC, and a dark matte body beside genuinely
# specular metal is most of what makes a real component photograph read as real. Not a mirror:
# a reflowed tin or gold plating is satin, and 0.0 would make every lead a chrome bead.
_METAL_METALLIC = 1.0
_METAL_ROUGHNESS = 0.35

# Colours that ARE metal, matched EXACTLY (within rounding). MEASURED over 130 real KiCad models,
# which between them use only 41 distinct colours - the ecosystem emits a small fixed palette, so an
# exact table covers most of it. `(209,208,198)` appears in 84 of those 130 models and
# `(218,187,126)` in 42; both were confirmed as pins/leads by bounding volume on real parts
# (Molex_KK-254, PinHeader, an LED, a tantalum cap).
#
# EXACTNESS IS THE WHOLE DESIGN, and this is the case that forces it: `(227,226,206)` is WHITE
# NYLON - the 344.7mm3 housing of Molex_KK-254, beside its 28.9mm3 tin pins. It sits 18/18/8 away
# from the tin colour, and BOTH are light and achromatic, so any saturation-or-lightness rule that
# catches the tin also chrome-plates the connector body. That is why the broader "grey means metal"
# rule was rejected before, and re-rejected here on measurement rather than on principle.
_METAL_PALETTE: tuple[tuple[int, int, int], ...] = (
    (209, 208, 198),  # tin / silver plating - the generator's default pin finish
    (218, 187, 126),  # gold
    (218, 187, 125),  # gold, the other rounding the generator emits
)
# Tolerance per channel. Small deliberately: it absorbs sRGB rounding and nothing else. The nearest
# NON-metal in the corpus is 8 away on its closest channel, so this cannot reach it.
_METAL_MATCH_TOLERANCE = 3

# Words a vendor uses for the LEADFRAME in its own STEP assembly, as a fallback for a part whose
# colours are not in any generator palette. cascadio preserves the vendor's solid names, and the
# owner's TPD6E05U06RVZR splits into `FRAME` and `BODY` with leads stated as (255,157,132), which no
# palette knows.
#
# This fires RARELY and fails SAFE, which is the only thing that makes it defensible rather than a
# "works on my one file" feature: MEASURED across 24 sampled KiCad models, every single one has
# exactly ONE mesh named after the FOOTPRINT (`PinHeader_2x29_P254mm_Vertical`), so the vocabulary
# never matches there and they fall through to the palette. Matched as whole TOKENS, never as
# substrings, so `MAINFRAMEWORK` is not a leadframe.
_LEADFRAME_WORDS = frozenset(
    {"FRAME", "LEADFRAME", "LEAD", "LEADS", "PIN", "PINS", "TERMINAL", "TERMINALS", "CONTACT",
     "CONTACTS"}
)


class SurfaceFinish(NamedTuple):
    """The two properties a STEP cannot state, decided per surface rather than per file."""

    metallic: float
    roughness: float


def _tokens(name: str) -> set[str]:
    """Upper-case word tokens of a mesh/solid name, split on anything that is not alphanumeric."""
    return {t for t in re.split(r"[^A-Za-z0-9]+", name.upper()) if t}


def surface_finish(srgb: tuple[int, int, int], mesh_name: str = "") -> SurfaceFinish:
    """Decide one surface's finish from the only two signals a converted STEP actually carries:
    its colour, and the name the vendor gave the solid it belongs to.

    Order matters. The PALETTE wins, because it is an ecosystem fact measured over a corpus; the
    NAME is only consulted when the colour is unrecognised, so a vocabulary word can never override
    a colour already known to be non-metal."""
    for metal in _METAL_PALETTE:
        if all(abs(a - b) <= _METAL_MATCH_TOLERANCE for a, b in zip(srgb, metal)):
            return SurfaceFinish(_METAL_METALLIC, _METAL_ROUGHNESS)
    if _tokens(mesh_name) & _LEADFRAME_WORDS:
        return SurfaceFinish(_METAL_METALLIC, _METAL_ROUGHNESS)
    return SurfaceFinish(_STEP_METALLIC, _STEP_ROUGHNESS)


def _srgb8(base_color: list[float]) -> tuple[int, int, int]:
    """glTF states baseColorFactor in LINEAR light; the palette above is written in the sRGB bytes
    a person reads off a colour picker, so the comparison happens in sRGB."""
    converted = [round((max(c, 0.0) ** (1 / 2.2)) * 255) for c in base_color[:3]]
    if len(converted) != 3:
        raise ValueError("base color must contain at least three channels")
    return (converted[0], converted[1], converted[2])


# The GLB JSON chunk's type, as the little-endian u32 the container stores it as.
_CHUNK_JSON = 0x4E4F534A


def _read_gltf_json(data: bytes) -> dict | None:
    """Read the JSON document from a binary glTF without touching its geometry chunks."""
    offset = 12
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        if kind == _CHUNK_JSON:
            try:
                return json.loads(data[offset + 8 : offset + 8 + length])
            except (UnicodeDecodeError, json.JSONDecodeError):
                return None
        offset += 8 + length
    return None


def _with_gltf_json(data: bytes, gltf: dict) -> bytes:
    """Re-emit GLB `data` carrying `gltf` as its JSON chunk.

    The container is rebuilt rather than patched in place because the JSON almost always
    changes LENGTH, and both the chunk header and the file header carry that length. Each
    chunk is padded to a 4-byte boundary with its own mandated filler (spaces for JSON,
    zeros for BIN), which is what keeps the BIN chunk's accessor offsets valid. A chunk's
    stored length already INCLUDES its padding, so the walk needs no extra alignment step;
    the re-emit is where the padding has to be recomputed."""
    offset = 12
    chunks: list[tuple[int, bytes]] = []
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        payload = data[offset + 8 : offset + 8 + length]
        chunks.append((kind, json.dumps(gltf, separators=(",", ":")).encode("utf-8")
                       if kind == _CHUNK_JSON else payload))
        offset += 8 + length

    out = bytearray(b"glTF" + struct.pack("<II", 2, 0))
    for kind, payload in chunks:
        pad = -len(payload) % 4
        filler = b" " if kind == _CHUNK_JSON else b"\x00"
        out += struct.pack("<II", len(payload) + pad, kind) + payload + filler * pad
    struct.pack_into("<I", out, 8, len(out))
    return bytes(out)


def _state_surface_finish(data: bytes) -> bytes:
    """Fill in the metalness/roughness a STEP cannot state (see _STEP_METALLIC).

    Only a property cascadio left UNSET is written, so if a future converter version ever
    does describe a surface, what it says wins over this default."""
    offset = 12
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        if kind == _CHUNK_JSON:
            gltf = json.loads(data[offset + 8 : offset + 8 + length])
            # Which SOLID each material belongs to. A material carries no name worth reading
            # (cascadio emits mat_0..mat_n), but the MESH it is used by keeps the vendor's own
            # name, and that is the leadframe signal. A material used by more than one mesh gets
            # all their names, so a leadframe word anywhere it is used counts.
            names: dict[int, set[str]] = {}
            for mesh in gltf.get("meshes", []):
                for prim in mesh.get("primitives", []):
                    index = prim.get("material")
                    if index is not None:
                        names.setdefault(index, set()).add(mesh.get("name") or "")
            touched = False
            for index, material in enumerate(gltf.get("materials", [])):
                pbr = material.setdefault("pbrMetallicRoughness", {})
                finish = surface_finish(
                    _srgb8(pbr.get("baseColorFactor", [0.0, 0.0, 0.0, 1.0])),
                    " ".join(sorted(names.get(index, set()))),
                )
                if "metallicFactor" not in pbr:
                    pbr["metallicFactor"] = finish.metallic
                    touched = True
                if "roughnessFactor" not in pbr:
                    pbr["roughnessFactor"] = finish.roughness
                    touched = True
            return _with_gltf_json(data, gltf) if touched else data
        offset += 8 + length
    return data


def _normalise_step_basis(data: bytes) -> bytes:
    """Declare a STEP model in glTF's Y-up coordinate basis without touching its mesh.

    OpenCASCADE writes STEP's native Z-up coordinates straight into POSITION accessors,
    while glTF defines +Y as up. The file is structurally valid, but every conforming
    viewer therefore stands a board-mounted part on its side. Wrap the authored scene
    roots in a -90° X rotation: source ``(x, y, z)`` becomes render ``(x, z, -y)``.

    A parent node is deliberate. Rewriting vertex buffers would risk normals, morphs,
    precision, and future mesh attributes; modifying an existing root would compound
    vendor transforms. The wrapper preserves both exactly and makes the conversion
    explicit in asset metadata for any downstream consumer.
    """
    offset = 12
    while offset + 8 <= len(data):
        length, kind = struct.unpack_from("<II", data, offset)
        if kind == _CHUNK_JSON:
            gltf = json.loads(data[offset + 8 : offset + 8 + length])
            scenes = gltf.get("scenes", [])
            if not scenes:
                return data

            nodes = gltf.setdefault("nodes", [])
            half_sqrt = math.sqrt(0.5)
            for index, scene in enumerate(scenes):
                authored_roots = list(scene.get("nodes", []))
                if not authored_roots:
                    continue
                wrapper_index = len(nodes)
                nodes.append(
                    {
                        "name": f"Stockroom STEP Basis — Scene {index + 1}",
                        "rotation": [-half_sqrt, 0.0, 0.0, half_sqrt],
                        "children": authored_roots,
                    }
                )
                scene["nodes"] = [wrapper_index]

            asset = gltf.setdefault("asset", {})
            extras = asset.setdefault("extras", {})
            stockroom = extras.setdefault("stockroom", {})
            stockroom.update(
                {
                    "sourceFormat": "STEP",
                    "sourceUpAxis": "Z",
                    "sourceUnits": "model-declared",
                    "renderUpAxis": "Y",
                    "renderUnits": "m",
                    "basisTransform": "rotateX(-90deg)",
                    "frameConfidence": "declared",
                }
            )
            return _with_gltf_json(data, gltf)
        offset += 8 + length
    return data


def _state_mesh_frame(data: bytes, src: Path) -> bytes:
    """Describe what is and is not known about a non-STEP mesh's coordinate frame.

    glTF/GLB have a standard Y-up, metre coordinate system. OBJ, STL, PLY, and most other
    interchange meshes do not declare either an up axis or a unit reliably. Trimesh can turn those
    bytes into a valid GLB, but that act does not magically make the source convention known. The
    renderer may still offer a raw preview and run plausibility checks; it must not present a guessed
    rotation or scale as accepted placement.
    """
    suffix = src.suffix.lower()
    standard_gltf = suffix in {".glb", ".gltf"}
    gltf = _read_gltf_json(data)
    if gltf is None:
        return data
    asset = gltf.setdefault("asset", {})
    extras = asset.setdefault("extras", {})
    stockroom = extras.setdefault("stockroom", {})
    stockroom.update(
        {
            "sourceFormat": suffix.lstrip(".").upper() or "UNKNOWN",
            "sourceUpAxis": "Y" if standard_gltf else "unknown",
            "sourceUnits": "m" if standard_gltf else "unknown",
            "renderUpAxis": "Y",
            "renderUnits": "m",
            "basisTransform": "identity",
            "frameConfidence": "standard" if standard_gltf else "unresolved",
        }
    )
    return _with_gltf_json(data, gltf)


def _step_to_glb(src: Path) -> bytes:
    """Convert a STEP with cascadio, keeping every byte of its geometry.

    Passing the geometry through is the whole point: cascadio writes one material per STEP
    colour and a NORMAL attribute per primitive, and re-encoding the result through any
    scene model risks losing exactly those (which is what trimesh did). cascadio only
    writes to a path, so it goes to a temp file that is read back and discarded. The one
    edits made on the way out are JSON-only: the surface finish above adds two numbers
    per material, and a parent node converts STEP's Z-up basis to glTF's mandated Y-up
    basis. Neither operation touches a geometry buffer."""
    try:
        cascadio = importlib.import_module("cascadio")
    except Exception as exc:  # ImportError, or a broken partial install
        raise ModelToolingMissing(
            "3D preview needs the 'cascadio' package to read STEP files; install it to "
            "enable 3D model previews"
        ) from exc

    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "model.glb"
        try:
            cascadio.step_to_glb(str(src), str(out))
        except Exception as exc:
            raise ModelConversionError(f"could not read the 3D model: {exc}") from exc
        if not out.exists():
            raise ModelConversionError("the 3D exporter did not produce a valid GLB")
        data = out.read_bytes()

    if not data.startswith(GLB_MAGIC):
        raise ModelConversionError("the 3D exporter did not produce a valid GLB")
    if _glb_mesh_count(data) == 0:
        raise ModelConversionError("the 3D model has no geometry to show")
    return _state_surface_finish(_normalise_step_basis(data))


def model_to_glb(src: Path) -> bytes:
    """Convert a STEP/WRL model file to GLB bytes.

    Raises ModelToolingMissing when the conversion stack is absent and
    ModelConversionError when the file cannot be converted; both map to a 502
    upstream. The caller has already checked the file exists (a missing model is a
    404, decided before we get here)."""
    src = Path(src)
    if src.suffix.lower() in _UNSUPPORTED_SUFFIXES:
        raise ModelConversionError(
            f"3D preview supports STEP models; {src.suffix.lower()} models are not "
            "convertible yet"
        )
    if src.suffix.lower() in _STEP_SUFFIXES:
        return _step_to_glb(src)
    try:
        import trimesh
    except Exception as exc:  # ImportError, or a broken partial install
        raise ModelToolingMissing(
            "3D preview needs the 'trimesh' package (and 'cascadio' for STEP files); "
            "install them to enable 3D model previews"
        ) from exc

    try:
        scene = trimesh.load(str(src), force="scene")
    except Exception as exc:
        # trimesh raises for an unknown loader (e.g. STEP with no cascadio) or a
        # malformed file. Both still surface as 502; the message just says which.
        msg = str(exc).lower()
        if "not supported" in msg or "no loader" in msg or "cascadio" in msg:
            raise ModelToolingMissing(
                f"no 3D loader for {src.suffix or 'this file'}; install 'cascadio' "
                "(STEP) to enable 3D model previews"
            ) from exc
        raise ModelConversionError(f"could not read the 3D model: {exc}") from exc

    if getattr(scene, "is_empty", False):
        raise ModelConversionError("the 3D model has no geometry to show")

    try:
        data = scene.export(file_obj=None, file_type="glb")
    except Exception as exc:
        raise ModelConversionError(
            f"could not encode the 3D model as GLB: {exc}"
        ) from exc

    if not isinstance(data, (bytes, bytearray)) or not bytes(data).startswith(GLB_MAGIC):
        raise ModelConversionError("the 3D exporter did not produce a valid GLB")
    return _state_mesh_frame(bytes(data), src)
