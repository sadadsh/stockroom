from pathlib import Path

import pytest

from stockroom.publish import (
    ManifestValidationError,
    PreparedPublicationManifest,
    PreparedTarget,
)


def _digest(character: str) -> str:
    return f"sha256:{character * 64}"


def _manifest(
    staging_root: Path,
    *,
    catalog_sha256: str = _digest("b"),
    machine_sha256: str = _digest("c"),
) -> PreparedPublicationManifest:
    return PreparedPublicationManifest(
        publication_id="pub_example",
        component_id="cmp_example",
        staging_root=staging_root,
        tracked_files=(
            PreparedTarget(
                target_path="Canonical/Example.json",
                sha256=_digest("a"),
            ),
        ),
        machine_local_files=(
            PreparedTarget(
                target_path="Stockroom.DbLib",
                sha256=machine_sha256,
            ),
        ),
        catalog_staged_path="Catalog.sqlite",
        catalog_sha256=catalog_sha256,
        catalog_revision="catalog_revision_example",
        catalog_semantic_digest=_digest("d"),
        commit_message="Publish Example",
    )


@pytest.mark.parametrize(
    "path",
    [
        "../Escape.json",
        "Folder\\Backslash.json",
        "Folder/Trailing.",
        "Folder/Trailing ",
        "CON",
        "con.txt",
        "Folder/NUL.json",
        "Folder/COM1.payload",
        "Folder/lPt9",
        "Folder/COM¹.txt",
    ],
)
def test_target_rejects_noncanonical_or_windows_aliasing_paths(path: str) -> None:
    with pytest.raises(ManifestValidationError, match="canonical relative path"):
        PreparedTarget(target_path=path, sha256=_digest("a"))


@pytest.mark.parametrize(
    "path",
    [
        "Catalog.sqlite",
        "State/Catalog.sqlite-wal",
        "State/Catalog.sqlite-shm",
        "Stockroom.DbLib",
        "State/Other.DbLib",
    ],
)
def test_manifest_rejects_activation_only_paths_from_git(
    tmp_path: Path,
    path: str,
) -> None:
    with pytest.raises(
        ManifestValidationError,
        match="activation-only projection paths",
    ):
        PreparedPublicationManifest(
            publication_id="pub_example",
            component_id="cmp_example",
            staging_root=tmp_path.resolve(),
            tracked_files=(PreparedTarget(path, _digest("a")),),
            machine_local_files=(),
            catalog_staged_path="Prepared/Catalog.sqlite",
            catalog_sha256=_digest("b"),
            catalog_revision="catalog_revision_example",
            catalog_semantic_digest=_digest("c"),
            commit_message="Publish Example",
        )


def test_manifest_rejects_windows_case_collisions(tmp_path: Path) -> None:
    with pytest.raises(ManifestValidationError, match="case collision"):
        PreparedPublicationManifest(
            publication_id="pub_example",
            component_id="cmp_example",
            staging_root=tmp_path.resolve(),
            tracked_files=(
                PreparedTarget("Canonical/Example.json", _digest("a")),
                PreparedTarget("canonical/example.JSON", _digest("b")),
            ),
            machine_local_files=(),
            catalog_staged_path="Catalog.sqlite",
            catalog_sha256=_digest("c"),
            catalog_revision="catalog_revision_example",
            catalog_semantic_digest=_digest("d"),
            commit_message="Publish Example",
        )


def test_workflow_digest_is_independent_of_machine_local_preparation(
    tmp_path: Path,
) -> None:
    left = _manifest(
        (tmp_path / "Machine A").resolve(),
        catalog_sha256=_digest("b"),
        machine_sha256=_digest("c"),
    )
    right = _manifest(
        (tmp_path / "Machine B").resolve(),
        catalog_sha256=_digest("e"),
        machine_sha256=_digest("f"),
    )

    assert left.digest == right.digest
    assert left.local_preparation_digest != right.local_preparation_digest
