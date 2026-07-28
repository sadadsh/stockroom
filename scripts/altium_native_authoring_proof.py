#!/usr/bin/env python3
"""Run the isolated native Altium authoring proof for the qualified S1M slice.

This harness generates the strict canonical input through Stockroom's domain API, then delegates
all native authoring and verification to ``stockroom.altium.native_authoring``. The STEP file is a
transport fixture for proving embedded-model persistence; it is not asserted to be qualified S1M
package geometry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from pathlib import Path

from stockroom.altium.native_authoring import author_native_component
from stockroom.domain import AuthoritativeEvidence, build_two_pin_passive_bundle


def _digest(label: str) -> str:
    return f"sha256:{hashlib.sha256(label.encode()).hexdigest()}"


def build_proof_bundle():
    """Build the exact canonical slice accepted by the native-authoring proof."""

    return build_two_pin_passive_bundle(
        authoritative_manufacturer_key="ON Semiconductor",
        mpn_canonical="S1M",
        functional_kind="diode",
        value="1 A 1000 V",
        package="SMA (DO-214AC)",
        value_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator="fixture://onsemi/S1M/value",
            content_digest=_digest("value"),
        ),
        package_evidence=AuthoritativeEvidence(
            source_kind="qualified_fixture",
            source_locator="fixture://onsemi/S1M/package",
            content_digest=_digest("package"),
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
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory(prefix="stockroom-native-canonical-") as temporary:
        canonical = Path(temporary) / "Canonical.json"
        canonical.write_bytes(build_proof_bundle().canonical_bytes())
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
