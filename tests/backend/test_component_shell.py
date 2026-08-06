"""The library-root boundary the three shell Manage actions rest on.

Everything below is a refusal test. `Reveal Component Files...` and `Open In...` end with the
operating system acting on a path, so the behaviour worth locking is not that the happy path
resolves - it is that nothing which leaves the active library root ever gets that far.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from stockroom.component_shell import (
    EXPORT_FORMATS,
    ComponentShellError,
    component_directory,
    component_export_directory,
    export_root,
)


def test_component_directory_is_the_components_own_folder_under_the_library(tmp_path: Path):
    library = tmp_path / "Stockroom Library"
    (library / "sourced" / "lm317-ab12").mkdir(parents=True)

    resolved = component_directory(library, "lm317-ab12")

    assert resolved == (library / "sourced" / "lm317-ab12").resolve()


@pytest.mark.parametrize(
    "part_id",
    [
        "..",
        "../..",
        "../../Windows",
        "..\\..\\Windows",
        "lm317/../../..",
        "/Windows",
        "C:\\Windows",
    ],
)
def test_component_directory_refuses_an_id_that_escapes_the_library_root(
    tmp_path: Path,
    part_id: str,
):
    """The exact attack this boundary exists for: a part id that resolves outside the library.

    The API layer also rejects a malformed id and the native host repeats the containment check,
    but this function must refuse on its own - a boundary guarded on one side only is guarded by
    whichever side was not changed last.
    """

    library = tmp_path / "Stockroom Library"
    (library / "sourced").mkdir(parents=True)

    with pytest.raises(ComponentShellError, match="escapes the library root"):
        component_directory(library, part_id)


def test_component_directory_refuses_the_library_root_itself(tmp_path: Path):
    library = tmp_path / "Stockroom Library"
    (library / "sourced").mkdir(parents=True)

    with pytest.raises(ComponentShellError, match="escapes the library root"):
        component_directory(library, "..")


def test_component_directory_refuses_a_blank_component_id(tmp_path: Path):
    with pytest.raises(ComponentShellError, match="component id is invalid"):
        component_directory(tmp_path, "  ")


def test_component_directory_refuses_a_link_that_points_out_of_the_library(tmp_path: Path):
    """A junction planted inside `sourced/` is a redirection out of the root.

    `resolve()` follows it before containment is judged, so the link is caught here rather than
    being followed later by Explorer.
    """

    library = tmp_path / "Stockroom Library"
    (library / "sourced").mkdir(parents=True)
    outside = tmp_path / "Elsewhere"
    outside.mkdir()
    try:
        (library / "sourced" / "escaped").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("this machine does not allow creating directory links")

    with pytest.raises(ComponentShellError, match="escapes the library root"):
        component_directory(library, "escaped")


def test_exports_never_land_inside_the_library():
    """Exports are derived copies. Writing them into the profile would put a growing pile of
    regenerable files into every peer's git history."""

    root = export_root()

    assert root.name == "Component Exports"
    assert "libraries" not in {part.lower() for part in root.parts}


@pytest.mark.parametrize("export_format", EXPORT_FORMATS)
def test_component_export_directory_stays_under_the_export_root(export_format: str):
    resolved = component_export_directory("lm317-ab12", export_format)

    assert export_root().resolve() in resolved.parents
    assert resolved.name == export_format


def test_component_export_directory_refuses_an_unknown_format():
    with pytest.raises(ComponentShellError, match="unsupported export format"):
        component_export_directory("lm317-ab12", "gerber")


@pytest.mark.parametrize("part_id", ["..", "../..", "a/../../.."])
def test_component_export_directory_refuses_an_escaping_component_id(part_id: str):
    with pytest.raises(ComponentShellError, match="escapes the export root"):
        component_export_directory(part_id, "kicad")
