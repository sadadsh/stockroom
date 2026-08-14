from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from securesystemslib.signer import CryptoSigner
from tuf.api.metadata import Metadata, Root

from packaging.release_feed import _load_production_signer
from packaging.release_trust import ReleaseTrustError, initialize_release_trust


def test_release_trust_creates_distinct_authorized_keys_and_signed_root(
    tmp_path: Path,
) -> None:
    output = tmp_path / "Trust"
    evidence = initialize_release_trust(
        output,
        reference_time=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    root_metadata = Metadata.from_bytes((output / "Root.json").read_bytes())
    assert isinstance(root_metadata.signed, Root)
    root = root_metadata.signed
    root.verify_delegate(Root.type, root_metadata.signed_bytes, root_metadata.signatures)
    assert root.consistent_snapshot
    assert root.version == 1

    keyids: set[str] = set()
    for role in ("root", "targets", "snapshot", "timestamp"):
        signer = _load_production_signer(output / f"{role.title()}.pem")
        assert isinstance(signer, CryptoSigner)
        assert signer.public_key.keyid in root.roles[role].keyids
        assert root.roles[role].threshold == 1
        keyids.add(signer.public_key.keyid)
    assert len(keyids) == 4
    assert evidence["validation"] == {
        "distinct_role_keys": True,
        "root_self_signature": True,
    }


def test_release_trust_refuses_existing_or_weak_output(tmp_path: Path) -> None:
    output = tmp_path / "Trust"
    output.mkdir()
    (output / "keep.txt").write_text("preserve", encoding="utf-8")
    with pytest.raises(ReleaseTrustError, match="must not exist or must be empty"):
        initialize_release_trust(output)
    assert (output / "keep.txt").read_text(encoding="utf-8") == "preserve"

    with pytest.raises(ReleaseTrustError, match="at least 365 days"):
        initialize_release_trust(tmp_path / "Weak", root_valid_days=30)
