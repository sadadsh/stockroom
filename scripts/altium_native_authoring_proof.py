#!/usr/bin/env python3
"""Run the isolated native Altium authoring proof for the exact supported diode profile.

This harness generates the strict canonical input through Stockroom's domain API, then delegates
all native authoring and verification to ``stockroom.altium.native_authoring``. The STEP file is a
transport fixture for proving embedded-model persistence; it is not asserted to be qualified
package geometry for the requested identity.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from stockroom.altium.native_authoring import author_native_component
from stockroom.domain import (
    AuthoritativeEvidence,
    CanonicalPassiveBundle,
    build_two_pin_passive_bundle,
)


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def build_proof_bundle(
    *,
    manufacturer: str = "ON Semiconductor",
    mpn: str = "S1M",
    value: str = "1 A 1000 V",
) -> CanonicalPassiveBundle:
    """Build an identity-specific instance of the exact accepted native-authoring profile."""

    identity_digest = hashlib.sha256(f"{manufacturer}\0{mpn}".encode()).hexdigest()

    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key=manufacturer,
        mpn_canonical=mpn,
        functional_kind="diode",
        value=value,
        package="SMA (DO-214AC)",
        value_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator=f"fixture://native-proof/{identity_digest}/value",
            content_digest=_digest(f"{manufacturer}\0{mpn}\0value\0{value}"),
        ),
        package_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator=f"fixture://native-proof/{identity_digest}/package",
            content_digest=_digest(f"{manufacturer}\0{mpn}\0package\0SMA (DO-214AC)"),
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--step", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--bootstrap",
        choices=("factory", "workspace"),
        default="factory",
    )
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--manufacturer", default="ON Semiconductor")
    parser.add_argument("--mpn", default="S1M")
    parser.add_argument("--value", default="1 A 1000 V")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="stockroom-native-canonical-") as temporary:
        canonical = Path(temporary) / "Canonical.json"
        canonical.write_bytes(
            build_proof_bundle(
                manufacturer=args.manufacturer,
                mpn=args.mpn,
                value=args.value,
            ).canonical_bytes()
        )
        result = author_native_component(
            canonical,
            args.step,
            args.output,
            bootstrap=args.bootstrap,
            timeout=args.timeout,
        )

    print(
        json.dumps(
            {
                "bootstrap": args.bootstrap,
                "detail": result.detail,
                "evidence": str(result.evidence),
                "output": str(result.output_dir),
                "status": result.status,
            },
            sort_keys=True,
        )
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
