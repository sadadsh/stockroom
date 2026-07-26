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

import json
import struct
import tempfile
from pathlib import Path

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
_STEP_ROUGHNESS = 0.45

# The GLB JSON chunk's type, as the little-endian u32 the container stores it as.
_CHUNK_JSON = 0x4E4F534A


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
            touched = False
            for material in gltf.get("materials", []):
                pbr = material.setdefault("pbrMetallicRoughness", {})
                if "metallicFactor" not in pbr:
                    pbr["metallicFactor"] = _STEP_METALLIC
                    touched = True
                if "roughnessFactor" not in pbr:
                    pbr["roughnessFactor"] = _STEP_ROUGHNESS
                    touched = True
            return _with_gltf_json(data, gltf) if touched else data
        offset += 8 + length
    return data


def _step_to_glb(src: Path) -> bytes:
    """Convert a STEP with cascadio, keeping every byte of its geometry.

    Passing the geometry through is the whole point: cascadio writes one material per STEP
    colour and a NORMAL attribute per primitive, and re-encoding the result through any
    scene model risks losing exactly those (which is what trimesh did). cascadio only
    writes to a path, so it goes to a temp file that is read back and discarded. The one
    edit made on the way out is the surface finish above, which adds two numbers per
    material to the JSON chunk and touches no buffer."""
    try:
        import cascadio
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
    return _state_surface_finish(data)


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
        data = scene.export(file_type="glb")
    except Exception as exc:
        raise ModelConversionError(
            f"could not encode the 3D model as GLB: {exc}"
        ) from exc

    if not isinstance(data, (bytes, bytearray)) or not bytes(data).startswith(GLB_MAGIC):
        raise ModelConversionError("the 3D exporter did not produce a valid GLB")
    return bytes(data)
