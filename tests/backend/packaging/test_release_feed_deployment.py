from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from packaging.deploy_release_feed import (
    ReleaseFeedDeploymentError,
    stage_release_feed,
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _publish_root(tmp_path: Path, *, signed: bool = True) -> Path:
    publish = tmp_path / "Publish"
    publish.mkdir(parents=True)
    package = publish / "Stockroom_1.2.3.4_x64.msix"
    package.write_bytes(b"signed-msix")
    appinstaller = publish / "Stockroom.appinstaller"
    appinstaller.write_bytes(b"signed-appinstaller")
    feed = publish / "Stockroom_TUF_Feed_1.2.3.4.zip"
    members = {
        "metadata/1.root.json": b"root",
        "metadata/1.targets.json": b"targets",
        "metadata/1.snapshot.json": b"snapshot",
        "metadata/timestamp.json": b"timestamp",
        "targets/abc.Release Manifest.json": b"manifest",
    }
    with zipfile.ZipFile(feed, "w") as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    inventory = [
        {"path": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}
        for name, data in sorted(members.items())
    ]
    feed_evidence = {
        "schema": "stockroom-release-feed/1",
        "release_id": "release-1.2.3.4",
        "metadata_version": 1,
        "archive": {
            "path": feed.name,
            "sha256": _sha256(feed),
            "size": feed.stat().st_size,
        },
        "repository_inventory": inventory,
        "validation": {"trusted_updater_round_trip": True},
        "deployment": {
            "feed_base_uri": "https://sadadsh.github.io/stockroom/windows/x64",
            "state": "staged-not-deployed",
        },
    }
    (publish / "Release Feed Evidence.json").write_text(
        json.dumps(feed_evidence), encoding="utf-8"
    )
    build_evidence = {
        "mode": "production",
        "signing": {"state": "authenticode-signed" if signed else "unsigned"},
        "outputs": {
            "msix": {"path": package.name, "sha256": _sha256(package)},
            "appinstaller": {
                "path": appinstaller.name,
                "sha256": _sha256(appinstaller),
            },
        },
    }
    (publish / "Build Evidence.json").write_text(
        json.dumps(build_evidence), encoding="utf-8"
    )
    return publish


def test_stage_release_feed_extracts_exact_verified_public_tree(tmp_path: Path) -> None:
    output = tmp_path / "Pages"
    receipt = stage_release_feed(
        publish_root=_publish_root(tmp_path),
        output_root=output,
        expected_feed_base_uri="https://sadadsh.github.io/stockroom/windows/x64/",
    )
    assert (output / "metadata/timestamp.json").read_bytes() == b"timestamp"
    assert (output / "targets/abc.Release Manifest.json").read_bytes() == b"manifest"
    assert (output / "Stockroom_1.2.3.4_x64.msix").read_bytes() == b"signed-msix"
    assert (output / "Stockroom.appinstaller").read_bytes() == b"signed-appinstaller"
    assert (output / ".nojekyll").is_file()
    assert receipt["validation"] == {
        "authenticode_signed": True,
        "archive_digest": True,
        "exact_feed_inventory": True,
        "trusted_updater_round_trip": True,
    }


def test_stage_release_feed_refuses_unsigned_or_uri_mismatch(tmp_path: Path) -> None:
    publish = _publish_root(tmp_path, signed=False)
    with pytest.raises(ReleaseFeedDeploymentError, match="not Authenticode-signed"):
        stage_release_feed(
            publish_root=publish,
            output_root=tmp_path / "Unsigned",
            expected_feed_base_uri="https://sadadsh.github.io/stockroom/windows/x64",
        )

    publish = _publish_root(tmp_path / "Other")
    with pytest.raises(ReleaseFeedDeploymentError, match="differs from deployment target"):
        stage_release_feed(
            publish_root=publish,
            output_root=tmp_path / "Wrong URI",
            expected_feed_base_uri="https://example.invalid/windows/x64",
        )
