"""Unit tests for the 3D model → GLB converter (M6d). The real STEP path is guarded
behind requires_glb_tooling; the failure paths run everywhere."""

from __future__ import annotations

import glob
import shutil

import pytest

from stockroom.kicad.model_convert import (
    GLB_MAGIC,
    ModelConversionError,
    ModelToolingMissing,
    model_to_glb,
)
from tests.backend.conftest import requires_glb_tooling


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


def test_model_to_glb_raises_on_an_unconvertible_file(tmp_path):
    # Tooling present → a garbage STEP is a ModelConversionError; tooling absent → a
    # ModelToolingMissing on import. Either way it is one of the two honest 502 errors,
    # never a bare crash.
    bad = tmp_path / "bad.step"
    bad.write_text("this is not a real STEP file", encoding="utf-8")
    with pytest.raises((ModelConversionError, ModelToolingMissing)):
        model_to_glb(bad)
