"""3D model → GLB conversion for the web 3D preview (M6d).

The library stores each part's 3D model as the KiCad file the user dropped in, which
is normally STEP (a footprint may instead carry a WRL/VRML mesh). The browser's
three.js viewer wants GLB, so this shells STEP through trimesh (which reads it via
cascadio) and emits a single binary glTF. trimesh has no VRML loader, so WRL/VRML
models are not convertible yet and are reported honestly (never a "install cascadio"
misdirection). The stack is OPTIONAL tooling: when trimesh/cascadio are not installed
the caller surfaces an honest 502, never a crash, and the symbol/footprint SVG
previews still work without it."""

from __future__ import annotations

from pathlib import Path

# GLB (binary glTF) starts with the ASCII magic "glTF"; named here so the converter
# and its tests share one contract for "this really is a GLB".
GLB_MAGIC = b"glTF"

# Mesh formats trimesh cannot load here (no VRML loader). A part legitimately stores a
# WRL, so it gets an honest "not convertible yet" message, not a tooling-missing one.
_UNSUPPORTED_SUFFIXES = {".wrl", ".vrml", ".x3d"}


class ModelToolingMissing(RuntimeError):
    """trimesh (and cascadio for STEP) are not installed, so 3D previews cannot be
    produced on this machine. Surfaced as a 502 with guidance, never a 500."""


class ModelConversionError(RuntimeError):
    """The model file is present but could not be turned into a GLB (an unreadable
    STEP, an empty mesh, a format trimesh has no loader for). Honest, not a crash."""


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
