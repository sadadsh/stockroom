"""Stage a verified Stockroom release feed for immutable HTTPS deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import zipfile
from pathlib import Path, PurePosixPath
from tempfile import NamedTemporaryFile
from typing import Any


class ReleaseFeedDeploymentError(ValueError):
    """A release feed cannot be staged without weakening its contract."""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ReleaseFeedDeploymentError(f"invalid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise ReleaseFeedDeploymentError(f"JSON root must be an object: {path.name}")
    return value


def _safe_archive_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if (
        path.is_absolute()
        or not path.parts
        or path.parts[0] not in {"metadata", "targets"}
        or any(part in {"", ".", ".."} for part in path.parts)
        or "\\" in name
    ):
        raise ReleaseFeedDeploymentError(f"unsafe feed archive member: {name}")
    return path


def _extract_feed_archive(
    archive_path: Path,
    output_root: Path,
    *,
    current: bool,
) -> list[dict[str, object]]:
    inventory: list[dict[str, object]] = []
    with zipfile.ZipFile(archive_path) as archive:
        seen: set[str] = set()
        for info in archive.infolist():
            if info.is_dir():
                continue
            relative = _safe_archive_path(info.filename)
            canonical = relative.as_posix()
            if canonical in seen:
                raise ReleaseFeedDeploymentError(f"duplicate feed member: {canonical}")
            seen.add(canonical)
            if not current and canonical == "metadata/timestamp.json":
                continue
            destination = output_root.joinpath(*relative.parts)
            destination.parent.mkdir(parents=True, exist_ok=True)
            with NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{destination.name}.",
                delete=False,
            ) as candidate, archive.open(info) as source:
                candidate_path = Path(candidate.name)
                shutil.copyfileobj(source, candidate)
            try:
                candidate_sha256 = _sha256(candidate_path)
                if destination.exists():
                    if current and canonical == "metadata/timestamp.json":
                        candidate_path.replace(destination)
                    elif _sha256(destination) != candidate_sha256:
                        raise ReleaseFeedDeploymentError(
                            f"immutable feed member conflict: {canonical}"
                        )
                else:
                    candidate_path.replace(destination)
                if current:
                    inventory.append(
                        {
                            "path": canonical,
                            "sha256": candidate_sha256,
                            "size": info.file_size,
                        }
                    )
            finally:
                candidate_path.unlink(missing_ok=True)
    return sorted(inventory, key=lambda item: str(item["path"]))


def stage_release_feed(
    *,
    publish_root: Path,
    output_root: Path,
    expected_feed_base_uri: str,
    previous_feed_archives: tuple[Path, ...] = (),
) -> dict[str, object]:
    """Extract only a verified production feed and its installer artifacts."""

    publish_root = Path(publish_root).resolve(strict=True)
    output_root = Path(output_root).resolve()
    if output_root.exists():
        if not output_root.is_dir() or any(output_root.iterdir()):
            raise ReleaseFeedDeploymentError("output root must not exist or must be empty")
    else:
        output_root.mkdir(parents=True)

    build_evidence_path = publish_root / "Build Evidence.json"
    feed_evidence_path = publish_root / "Release Feed Evidence.json"
    build_evidence = _load_json(build_evidence_path)
    feed_evidence = _load_json(feed_evidence_path)
    if build_evidence.get("mode") != "production":
        raise ReleaseFeedDeploymentError("build evidence is not production evidence")
    signing = build_evidence.get("signing")
    if not isinstance(signing, dict) or signing.get("state") != "authenticode-signed":
        raise ReleaseFeedDeploymentError("build evidence is not Authenticode-signed")
    if feed_evidence.get("schema") != "stockroom-release-feed/1":
        raise ReleaseFeedDeploymentError("release feed evidence schema is invalid")
    deployment = feed_evidence.get("deployment")
    if not isinstance(deployment, dict):
        raise ReleaseFeedDeploymentError("release feed deployment evidence is missing")
    normalized_uri = expected_feed_base_uri.rstrip("/")
    if deployment.get("feed_base_uri") != normalized_uri:
        raise ReleaseFeedDeploymentError("release feed URI differs from deployment target")
    if deployment.get("state") != "staged-not-deployed":
        raise ReleaseFeedDeploymentError("release feed is not in staged-not-deployed state")
    validation = feed_evidence.get("validation")
    if not isinstance(validation, dict) or not validation.get("trusted_updater_round_trip"):
        raise ReleaseFeedDeploymentError("trusted updater round trip is missing")

    archive_record = feed_evidence.get("archive")
    if not isinstance(archive_record, dict):
        raise ReleaseFeedDeploymentError("release feed archive evidence is missing")
    archive_path = publish_root / str(archive_record.get("path", ""))
    if not archive_path.is_file() or _sha256(archive_path) != archive_record.get("sha256"):
        raise ReleaseFeedDeploymentError("release feed archive digest mismatch")

    outputs = build_evidence.get("outputs")
    if not isinstance(outputs, dict):
        raise ReleaseFeedDeploymentError("build outputs evidence is missing")
    required_outputs = {
        "msix": None,
        "appinstaller": "Stockroom.appinstaller",
    }
    copied: list[dict[str, object]] = []
    for key, fixed_name in required_outputs.items():
        record = outputs.get(key)
        if not isinstance(record, dict):
            raise ReleaseFeedDeploymentError(f"{key} output evidence is missing")
        source = publish_root / str(record.get("path", ""))
        if not source.is_file() or _sha256(source) != record.get("sha256"):
            raise ReleaseFeedDeploymentError(f"{key} output digest mismatch")
        destination_name = fixed_name or source.name
        destination = output_root / destination_name
        shutil.copyfile(source, destination)
        copied.append(
            {
                "path": destination_name,
                "sha256": _sha256(destination),
                "size": destination.stat().st_size,
            }
        )

    for previous_archive in previous_feed_archives:
        previous_archive = Path(previous_archive).resolve(strict=True)
        _extract_feed_archive(previous_archive, output_root, current=False)
    actual_inventory = _extract_feed_archive(archive_path, output_root, current=True)

    expected_inventory = feed_evidence.get("repository_inventory")
    if actual_inventory != expected_inventory:
        raise ReleaseFeedDeploymentError("extracted feed inventory differs from evidence")
    (output_root / ".nojekyll").write_bytes(b"")
    receipt: dict[str, object] = {
        "schema": "stockroom-release-feed-deployment/1",
        "feed_base_uri": normalized_uri,
        "release_id": feed_evidence.get("release_id"),
        "metadata_version": feed_evidence.get("metadata_version"),
        "feed_files": len(actual_inventory),
        "historical_feed_archives": len(previous_feed_archives),
        "installer_outputs": copied,
        "validation": {
            "authenticode_signed": True,
            "archive_digest": True,
            "exact_feed_inventory": True,
            "trusted_updater_round_trip": True,
        },
    }
    (output_root / "Deployment Evidence.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--publish-root", required=True, type=Path)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--feed-base-uri", required=True)
    parser.add_argument("--previous-feed", action="append", type=Path, default=[])
    args = parser.parse_args()
    receipt = stage_release_feed(
        publish_root=args.publish_root,
        output_root=args.output_root,
        expected_feed_base_uri=args.feed_base_uri,
        previous_feed_archives=tuple(args.previous_feed),
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
