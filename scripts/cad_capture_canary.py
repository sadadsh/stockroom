#!/usr/bin/env python3
"""Prove one live CAD provider route through Stockroom's broker, CAS, and API.

The canary creates an isolated Git-backed library and capture state. It never reads or writes the
owner's active library, browser profile, or evidence store. The selected production route is
driven through ``GuidedCaptureSource._supply_automated_route`` because the purpose is to verify one
author route independently; the normal product run deliberately tries every useful route.

Usage:
    uv run python scripts/cad_capture_canary.py \
        --manufacturer "TE Connectivity AMP Connectors" \
        --mpn 5212034-1 \
        --route digikey-traceparts \
        --out "work/Live CAD Canary/TraceParts 5212034-1"
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent / "app" / "backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--manufacturer", required=True)
    parser.add_argument("--mpn", required=True)
    parser.add_argument(
        "--route",
        default="digikey-traceparts",
        help="exact evidence provider key exposed by DigiKey's production route registry",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--headed",
        action="store_true",
        help="show the isolated provider browser; headless is the default",
    )
    return parser.parse_args()


def _safe_component_id(mpn: str) -> str:
    value = "".join(char.casefold() if char.isalnum() else "-" for char in mpn)
    value = "-".join(filter(None, value.split("-")))
    if not value:
        raise ValueError("MPN does not contain a usable component identifier")
    return f"canary-{value}"


def _build_isolated_context(root: Path, manufacturer: str, mpn: str):
    from stockroom.api.context import build_context
    from stockroom.model.part import PartRecord
    from stockroom.model.part_class import RequirementOverride
    from stockroom.store.machine_config import MachineConfig
    from stockroom.store.profile import ProfileStore
    from stockroom.vcs.repo import GitRepo

    libraries_root = root / "Library"
    libraries_root.mkdir(parents=True)
    repo = GitRepo(libraries_root)
    repo.init()
    profile = ProfileStore(libraries_root, repo).create("Main")
    component_id = _safe_component_id(mpn)
    record = PartRecord(
        id=component_id,
        display_name=mpn,
        category="Connectors",
        description="Isolated live CAD capture canary",
        mpn=mpn,
        manufacturer=manufacturer,
        requires_override=RequirementOverride(
            needs=("model",),
            reason="Live canary isolates the provider's mechanical-model route.",
        ),
    )
    record_path = profile.library.parts_dir / f"{component_id}.json"
    record_path.write_text(record.dumps(), encoding="utf-8")
    repo.commit("Seed isolated live CAD capture canary", [record_path])
    kicad_dir = root / "KiCad"
    kicad_dir.mkdir()
    config = MachineConfig(active_profile="Main", sync_enabled=False)
    context = build_context(
        libraries_root,
        kicad_dir=kicad_dir,
        config=config,
        token="live-cad-canary",
    )
    return context, record


def _capture(context, record, root: Path, route_key: str, headed: bool):
    from stockroom.capture.guided import GuidedCaptureSource
    from stockroom.capture.vendors import get_adapter
    from stockroom.evidence import EvidenceStore
    from stockroom.ingest.pipeline import IngestPipeline

    surface = get_adapter("digikey")
    if surface is None:
        raise RuntimeError("the DigiKey production adapter is unavailable")
    route_factory = getattr(surface, "capture_routes", None)
    if not callable(route_factory):
        raise RuntimeError("the DigiKey production adapter exposes no author routes")
    routes = tuple(route_factory())
    route = next(
        (
            candidate
            for candidate in routes
            if getattr(candidate, "evidence_provider_key", "") == route_key
        ),
        None,
    )
    if route is None:
        available = ", ".join(
            getattr(candidate, "evidence_provider_key", "")
            for candidate in routes
        )
        raise ValueError(f"unknown DigiKey route {route_key!r}; available: {available}")
    if not getattr(route, "supplementary_only", False):
        raise ValueError(
            "this canary currently accepts only non-projectable supplementary routes"
        )

    capture_root = root / "Capture"
    evidence_store = EvidenceStore(capture_root / "Evidence")
    source = GuidedCaptureSource(
        lambda: IngestPipeline(context.profile, context.repo, context.cli),
        vendor="digikey",
        download_root=capture_root / "Downloads",
        profile_dir=capture_root / "Browser Profile",
        headless=not headed,
        engine=surface.capability.browser_engine,
        evidence_store=evidence_store,
        operator_authorized=True,
    )
    try:
        session = source._ensure_session()
        url = surface.resolve_url(record.mpn)
        if not url:
            raise RuntimeError(f"DigiKey exposed no CAD-model URL for {record.mpn}")
        outcome = source._supply_automated_route(
            record,
            session,
            route,
            record.manufacturer,
            record.mpn,
            url,
            ["model"],
        )
    finally:
        source.close()
    if outcome.error or outcome.retained < 1:
        raise RuntimeError(
            outcome.error
            or outcome.skipped
            or "the production route retained no supplementary artifact"
        )
    return evidence_store, outcome


def _verify_api(context, record, evidence_store):
    from fastapi.testclient import TestClient

    from stockroom.api.app import create_app
    from stockroom.capture.evidence import exact_identity

    retained = evidence_store.list_supplementary_artifacts(identity=exact_identity(record))
    if len(retained) != 1:
        raise RuntimeError(
            f"expected one exact supplementary manifest, found {len(retained)}"
        )
    manifest = retained[0]
    if not manifest.artifacts:
        raise RuntimeError("the supplementary manifest contains no artifacts")

    with TestClient(
        create_app(context),
        base_url="http://live-cad-canary",
        raise_server_exceptions=False,
        headers={"X-Stockroom-Token": context.token},
    ) as client:
        inventory_response = client.get(
            f"/api/library/parts/{record.id}/cad-variants"
        )
        if inventory_response.status_code != 200:
            raise RuntimeError(
                "supplementary inventory failed: "
                f"{inventory_response.status_code} {inventory_response.text}"
            )
        inventory = inventory_response.json()
        supplementary = inventory.get("supplementary") or []
        if len(supplementary) != 1:
            raise RuntimeError(
                f"API expected one supplementary manifest, found {len(supplementary)}"
            )
        artifact = supplementary[0]["artifacts"][0]
        if supplementary[0].get("canActivate") is not False:
            raise RuntimeError("supplementary evidence incorrectly became activatable")
        response = client.get(artifact["downloadUrl"])
        if response.status_code != 200:
            raise RuntimeError(
                f"original-file download failed: {response.status_code} {response.text}"
            )

    digest = f"sha256:{hashlib.sha256(response.content).hexdigest()}"
    if digest != artifact["evidenceDigest"]:
        raise RuntimeError(
            "downloaded API bytes do not match the retained artifact evidence digest"
        )
    return {
        "inventory": inventory,
        "manifest": manifest,
        "downloaded_bytes": response.content,
        "downloaded_digest": digest,
    }


def main() -> int:
    args = _arguments()
    output = args.out.resolve()
    if output.exists() and any(output.iterdir()):
        raise SystemExit(f"refusing to reuse non-empty canary output: {output}")
    output.mkdir(parents=True, exist_ok=True)
    os.environ["STOCKROOM_CAPTURE_DIR"] = str((output / "Capture").resolve())

    context, record = _build_isolated_context(
        output,
        args.manufacturer.strip(),
        args.mpn.strip(),
    )
    try:
        evidence_store, outcome = _capture(
            context,
            record,
            output,
            args.route.strip(),
            args.headed,
        )
        verified = _verify_api(context, record, evidence_store)
        artifact = verified["inventory"]["supplementary"][0]["artifacts"][0]
        result = {
            "schema": "stockroom.live-cad-capture-canary/1",
            "status": "passed",
            "identity": {
                "manufacturer": record.manufacturer,
                "mpn": record.mpn,
                "partId": record.id,
            },
            "route": args.route,
            "retained": outcome.retained,
            "manifestDigest": verified["manifest"].manifest_digest,
            "artifact": {
                "fileName": artifact["fileName"],
                "sizeBytes": artifact["sizeBytes"],
                "evidenceDigest": artifact["evidenceDigest"],
                "downloadedDigest": verified["downloaded_digest"],
            },
            "checks": {
                "downloadBrokerReceipt": True,
                "stagingToCas": True,
                "supplementaryManifest": True,
                "authenticatedInventory": True,
                "originalBytesMatch": True,
                "projectable": False,
            },
        }
        result_path = output / "Canary Result.json"
        result_path.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        print(json.dumps({**result, "resultPath": str(result_path)}, indent=2))
        return 0
    finally:
        context.close()


if __name__ == "__main__":
    raise SystemExit(main())
