"""Initialize Stockroom's offline TUF trust without exposing private keys.

This command writes one offline root key, three distinct online-role keys, the
public signed root metadata, and a public evidence record into a new directory.
The caller must immediately move the private keys into approved secret stores.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root


class ReleaseTrustError(ValueError):
    """Release trust could not be initialized safely."""


_PRIVATE_KEY_NAMES = {
    "root": "Root.pem",
    "targets": "Targets.pem",
    "snapshot": "Snapshot.pem",
    "timestamp": "Timestamp.pem",
}


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def initialize_release_trust(
    output_directory: Path,
    *,
    root_version: int = 1,
    root_valid_days: int = 3650,
    reference_time: datetime | None = None,
) -> dict[str, object]:
    """Create a new threshold-one TUF root and distinct Ed25519 role keys."""

    if type(root_version) is not int or root_version <= 0:
        raise ReleaseTrustError("root version must be a positive integer")
    if type(root_valid_days) is not int or root_valid_days < 365:
        raise ReleaseTrustError("root validity must be at least 365 days")
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)
    elif reference_time.tzinfo is None:
        raise ReleaseTrustError("reference time must include a timezone")
    reference_time = reference_time.astimezone(timezone.utc)

    output_directory = Path(output_directory).resolve()
    if output_directory.exists():
        if not output_directory.is_dir() or any(output_directory.iterdir()):
            raise ReleaseTrustError("output directory must not exist or must be empty")
    else:
        output_directory.mkdir(parents=True)

    private_keys = {
        role: Ed25519PrivateKey.generate()
        for role in ("root", "targets", "snapshot", "timestamp")
    }
    signers = {role: CryptoSigner(key) for role, key in private_keys.items()}
    root = Root(
        version=root_version,
        expires=reference_time + timedelta(days=root_valid_days),
        consistent_snapshot=True,
    )
    for role, signer in signers.items():
        root.add_key(signer.public_key, role)
    root_metadata = Metadata(root)
    root_metadata.sign(signers["root"])
    root.verify_delegate(
        Root.type,
        root_metadata.signed_bytes,
        root_metadata.signatures,
    )

    private_records: dict[str, dict[str, object]] = {}
    for role, private_key in private_keys.items():
        data = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
        path = output_directory / _PRIVATE_KEY_NAMES[role]
        path.write_bytes(data)
        private_records[role] = {
            "filename": path.name,
            "keyid": signers[role].public_key.keyid,
            "sha256": _sha256(data),
        }

    root_bytes = root_metadata.to_bytes()
    root_path = output_directory / "Root.json"
    root_path.write_bytes(root_bytes)
    evidence: dict[str, object] = {
        "schema": "stockroom-release-trust/1",
        "generated_at": reference_time.isoformat().replace("+00:00", "Z"),
        "root": {
            "consistent_snapshot": root.consistent_snapshot,
            "expires": root.expires.isoformat(),
            "filename": root_path.name,
            "sha256": _sha256(root_bytes),
            "version": root.version,
        },
        "roles": {
            role: {
                "authorized_keyids": sorted(root.roles[role].keyids),
                "generated_keyid": signers[role].public_key.keyid,
                "threshold": root.roles[role].threshold,
            }
            for role in ("root", "targets", "snapshot", "timestamp")
        },
        "private_key_files": private_records,
        "validation": {
            "distinct_role_keys": len(
                {signer.public_key.keyid for signer in signers.values()}
            )
            == 4,
            "root_self_signature": True,
        },
    }
    evidence_path = output_directory / "Release Trust Evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-directory", required=True, type=Path)
    parser.add_argument("--root-version", type=int, default=1)
    parser.add_argument("--root-valid-days", type=int, default=3650)
    args = parser.parse_args()
    evidence = initialize_release_trust(
        args.output_directory,
        root_version=args.root_version,
        root_valid_days=args.root_valid_days,
    )
    root_record = cast(dict[str, object], evidence["root"])
    print(
        json.dumps(
            {
                "root_sha256": root_record["sha256"],
                "root_version": root_record["version"],
                "validated": True,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
